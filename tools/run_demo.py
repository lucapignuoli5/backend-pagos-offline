"""Load DPAPI configuration only when explicitly requested by the operator."""
import argparse
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from urllib.parse import urlparse

from tools.demo_windows import (
    DemoError, FileLock, contain_children_until_exit, endpoint_lock_path,
    ngrok_native_stderr_to_null, write_private_atomic,
)


_LAUNCHER_ONLY = {"NGROK_AUTHTOKEN", "NGROK_API_KEY", "NGROK_DOMAIN"}


def _hostname(value):
    if not isinstance(value, str) or not value or len(value) > 253 or not value.isascii():
        raise DemoError("--domain debe ser un hostname ASCII, sin esquema, puerto ni ruta.")
    labels = value.split(".")
    if len(labels) < 2 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", p)
                              for p in labels):
        raise DemoError("--domain debe ser un hostname valido, sin esquema, puerto ni ruta.")
    return value.lower()


def _domain(config, explicit):
    if explicit:
        return _hostname(explicit)
    if config.get("NGROK_DOMAIN"):
        return _hostname(config["NGROK_DOMAIN"])
    # Legacy API_BASE_URL is an exact candidate, never proof of a reservation.
    # If ngrok rejects it we stop; we do not silently replace an APK's URL.
    try:
        parsed = urlparse(config["API_BASE_URL"])
        valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment
                 and parsed.port in (None, 443) and parsed.path in ("", "/"))
    except ValueError:
        valid = False
    if not valid:
        raise DemoError("La URL demo no es HTTPS valida. Configure el dominio con --domain.")
    if parsed.hostname == "example.invalid":
        return None  # A newly prepared demo has no URL yet; build Android afterwards.
    return _hostname(parsed.hostname)


def _configuration(directory, source):
    from pos_desktop.key_store import WindowsDpapiProtector
    if (not directory.is_dir() or directory.is_relative_to(source)
            or (directory / ".git").exists()
            or any((parent / ".git").exists() for parent in directory.parents)):
        raise DemoError("Seleccione una carpeta demo existente y externa a los repositorios Git.")
    protected_path = directory / "config.dpapi"
    if protected_path.is_symlink() or not protected_path.is_file():
        raise DemoError("No se encontro config.dpapi local en la carpeta demo indicada.")
    protector = WindowsDpapiProtector()
    try:
        config = json.loads(protector.unprotect(protected_path.read_bytes()))
        if not isinstance(config, dict) or any(not isinstance(v, str) for v in config.values()):
            raise ValueError()
    except Exception:
        raise DemoError(
            "No se pudo abrir la configuracion demo con esta cuenta Windows. "
            "No copie identidades de otra computadora ni reemplace la base existente."
        ) from None
    return config, protector


def _backend_database(config, directory):
    # Never let a missing configuration select database.py's repository fallback.
    url = config.get("DATABASE_URL", "")
    if not url.startswith("sqlite:///") or "?" in url or "#" in url:
        raise DemoError("La demo requiere una base SQLite externa seleccionada explicitamente.")
    path = Path(url[len("sqlite:///"):]).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise DemoError("La base SQLite configurada no existe dentro de esta carpeta demo.")


@contextmanager
def _closing_signals():
    previous = {}
    for name in ("SIGINT", "SIGBREAK"):
        event = getattr(signal, name, None)
        if event is not None:
            previous[event] = signal.signal(event, signal.SIG_IGN)
    try:
        yield
    finally:
        for event, handler in previous.items():
            signal.signal(event, handler)


def _run_services(args, config, protector, environment, source, directory):
    from tools.demo_process import (
        OwnedBackend, require_backend_listener, require_free_backend_port,
        stop_owned_process, watch,
    )
    backend_command = [
        sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000",
        "--no-access-log", "--log-config", str(source / "demo_log_config.json"),
        "--timeout-graceful-shutdown", "10",
    ]
    backend = None
    tunnel_config = None
    ngrok_process = None
    with ExitStack() as locks:
        if args.mode in {"backend", "start"}:
            locks.enter_context(FileLock(endpoint_lock_path(), "backend 127.0.0.1:8000"))
            locks.enter_context(FileLock(directory / ".backend.lock", "backend de esta demo"))
            _backend_database(config, directory)
            require_free_backend_port()
        if args.mode in {"tunnel", "start"}:
            locks.enter_context(FileLock(directory / ".tunnel.lock", "tunel de esta demo"))
        # Failing containment stops before either Popen or pyngrok can spawn.
        contain_children_until_exit()
        try:
            ngrok = None
            domain = None
            if args.mode in {"tunnel", "start"}:
                from tools.demo_ngrok import prepare_ngrok
                domain = _domain(config, args.domain)
                if args.mode == "tunnel":
                    require_backend_listener()
                ngrok, tunnel_config = prepare_ngrok(directory, args.configure_token)
            if args.mode in {"backend", "start"}:
                backend = OwnedBackend(backend_command, source, environment, directory)
                backend.wait_ready()
            if ngrok is not None:
                from tools.demo_ngrok import ngrok_error
                try:
                    # Pyngrok redirects stdout but leaves native stderr inherited.
                    # Its account/error output must not bypass our safe messages.
                    with ngrok_native_stderr_to_null():
                        ngrok_process = ngrok.get_ngrok_process(tunnel_config).proc
                        options = {"domain": domain} if domain else {}
                        tunnel = ngrok.connect(
                            addr="http://127.0.0.1:8000", proto="http", bind_tls=True,
                            pyngrok_config=tunnel_config, **options,
                        )
                except DemoError:
                    raise
                except Exception as error:
                    raise ngrok_error(error) from None
                parsed = urlparse(tunnel.public_url)
                if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                        or parsed.query or parsed.fragment or parsed.port not in (None, 443)
                        or parsed.path not in ("", "/")):
                    raise DemoError("Ngrok no devolvio una URL HTTPS de raiz valida; no se cambio la configuracion.")
                if domain and parsed.hostname.lower() != domain:
                    raise DemoError("El tunel no coincide con el dominio pedido; no se cambio la URL del APK.")
                if backend is not None:
                    backend.check()
                if ngrok_process.poll() is not None:
                    raise DemoError("Ngrok termino durante la preparacion; no se cambio la URL.")
                url = "https://" + parsed.hostname.lower()
                previous_url = config.get("API_BASE_URL", "").rstrip("/")
                updated = dict(config)
                updated["API_BASE_URL"] = url + "/"
                updated["TFG_BACKEND_URL"] = url
                if args.domain:
                    updated["NGROK_DOMAIN"] = domain
                protected = protector.protect(json.dumps(updated).encode("utf-8"))
                write_private_atomic(directory / "config.dpapi", protected)
                print("Tunel HTTPS abierto; URL guardada en la configuracion local:", url)
                if previous_url != url:
                    print("La URL cambio: regenere android-config y compile el APK antes de usarlo.")
                if backend is None:
                    print("Modo tunnel: esta ventana solo administra ngrok; el backend se mantiene por separado.")
                print("Mantenga esta ventana abierta durante el login y la sincronizacion.")
                print("El APK debe usar esta misma URL. El QR automatico requiere Wi-Fi activado en el cliente.")
                print("Consola en vivo: login, autorizaciones, recargas y conciliacion.")
                print("Los pagos offline aparecen en el servidor al sincronizar.")
                print("Presione Enter para cerrar esta demostracion.")
            else:
                print("Backend propio listo en 127.0.0.1:8000. Presione Ctrl+C para cerrarlo.")
            watch(backend, ngrok_process, enter_to_close=args.mode != "backend")
        finally:
            with _closing_signals():
                try:
                    if tunnel_config is not None:
                        from tools.demo_ngrok import known_ngrok_process
                        owned = ngrok_process or known_ngrok_process(tunnel_config)
                        stop_owned_process(owned)
                finally:
                    if backend is not None:
                        backend.stop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backend", "pos", "android", "android-config", "credentials", "tunnel", "start"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--domain", help="Existing reserved ngrok hostname, without https://")
    parser.add_argument("--configure-token", action="store_true", help="Replace the local ngrok token using hidden input")
    args = parser.parse_args(argv)
    if (args.domain or args.configure_token) and args.mode not in {"start", "tunnel"}:
        parser.error("--domain y --configure-token corresponden a start o tunnel")
    directory = args.directory.expanduser().resolve()
    source = Path(__file__).resolve().parents[1]
    config, protector = _configuration(directory, source)
    # This snapshot is made before ngrok configuration. Exclude credentials here
    # as well as from os.environ in prepare_ngrok, including legacy DPAPI keys.
    environment = {key: value for key, value in dict(os.environ, **config).items()
                   if key.upper() not in _LAUNCHER_ONLY}
    environment["DEMO_DEVICE_LOGIN_ENABLED"] = "true"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    if args.mode in {"android", "android-config"}:
        public = {name: config[name] for name in (
            "API_BASE_URL", "ISSUER_PUBLIC_KEY_B64", "ISSUER_KEY_ID", "ISSUER_TRUST_JSON")}
        public["DEMO_ISOLATED_INSTALL"] = "true"
        target = source.parent / "Prototipo Pagos Offline Android" / "demo.local.properties"
        target.write_text("\n".join(name + "=" + value.replace("\\", "\\\\")
                                   for name, value in public.items()) + "\n", encoding="ascii")
        if args.mode == "android-config":
            print("Configuracion publica de Android Studio preparada; no contiene contrasenas.")
            return 0
    if args.mode in {"backend", "start", "tunnel"}:
        # Ctrl+Break on the launcher itself follows the same orderly close as Ctrl+C.
        if hasattr(signal, "SIGBREAK"):
            def request_close(*_):
                raise KeyboardInterrupt()
            signal.signal(signal.SIGBREAK, request_close)
        return _run_services(args, config, protector, environment, source, directory)
    if args.mode == "credentials":
        clipboard = "Usuario: " + config["DEMO_MERCHANT_USERNAME"] + "\nContraseña: " + config["DEMO_MERCHANT_PASSWORD"]
        subprocess.run(["clip.exe"], input=clipboard, text=True, check=True, env=environment)
        print("Credenciales del comercio copiadas al portapapeles. No compartir.")
        return 0
    if args.mode == "android":
        android = source.parent / "Prototipo Pagos Offline Android"
        environment["JAVA_HOME"] = r"C:\Program Files\Android\Android Studio\jbr"
        environment["ANDROID_HOME"] = str(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
        environment["DEMO_ISOLATED_INSTALL"] = "true"
        command = [str(android / "gradlew.bat"), ":app:assembleDebug", ":app:assembleDebugAndroidTest", "--console=plain"]
        cwd = android
    else:
        command = [sys.executable, "-m", "pos_desktop.app"]
        cwd = source
    return subprocess.call(command, cwd=cwd, env=environment)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Cierre solicitado; la demo de esta ventana termino.")
        raise SystemExit(0)
    except DemoError as error:
        print("No se pudo mantener la demostracion: " + str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        # No tracebacks: configuration and provider exceptions may include secrets.
        print("No se pudo completar la accion demo (" + type(error).__name__ + "). Revise su configuracion local.", file=sys.stderr)
        raise SystemExit(1)
