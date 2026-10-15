"""Load DPAPI configuration only when explicitly requested by the operator."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backend", "pos", "android", "android-config", "credentials", "tunnel", "start"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--domain", help="Existing reserved ngrok hostname, without https://")
    args = parser.parse_args()
    from pos_desktop.key_store import WindowsDpapiProtector
    directory = args.directory.resolve()
    config = json.loads(WindowsDpapiProtector().unprotect((directory / "config.dpapi").read_bytes()))
    environment = dict(os.environ, **config)
    environment["DEMO_DEVICE_LOGIN_ENABLED"] = "true"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    source = Path(__file__).resolve().parents[1]
    if args.mode in {"android", "android-config"}:
        # Public configuration only: Studio and the command line use the same trust root.
        public = {name: config[name] for name in (
            "API_BASE_URL", "ISSUER_PUBLIC_KEY_B64", "ISSUER_KEY_ID", "ISSUER_TRUST_JSON")}
        public["DEMO_ISOLATED_INSTALL"] = "true"
        target = source.parent / "Prototipo Pagos Offline Android" / "demo.local.properties"
        target.write_text("\n".join(name + "=" + value.replace("\\", "\\\\")
            for name, value in public.items()) + "\n", encoding="ascii")
        if args.mode == "android-config":
            print("Configuracion publica de Android Studio preparada; no contiene contrasenas.")
            return
    backend_command = [
        sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000",
        "--no-access-log", "--log-config", str(source / "demo_log_config.json"),
    ]
    if args.mode in {"tunnel", "start"}:
        from getpass import getpass
        from pyngrok import ngrok
        from pyngrok.conf import PyngrokConfig
        token = os.getenv("NGROK_AUTHTOKEN")
        if not token:
            import yaml
            existing = Path(os.environ["LOCALAPPDATA"]) / "ngrok" / "ngrok.yml"
            if existing.is_file():
                record = yaml.safe_load(existing.read_text(encoding="utf-8")) or {}
                agent = record.get("agent") or {}
                token = record.get("authtoken") or agent.get("authtoken")
        if not token:
            token = getpass("Authtoken ngrok (entrada oculta): ")
        if not token:
            parser.error("Authtoken required; retrieve it from your own ngrok account")
        tunnel_config = PyngrokConfig(
            ngrok_path=str(directory / "ngrok.exe"),
            config_path=str(directory / "ngrok.yml"),
            auth_token=token,
        )
        configured_domain = urlparse(config["API_BASE_URL"]).hostname
        domain = args.domain or (configured_domain if configured_domain != "example.invalid" else None)
        if domain and ("/" in domain or ":" in domain or not domain.isascii()):
            parser.error("--domain must be a hostname without scheme, port or path")
        options = {"domain": domain} if domain else {}
        backend = None
        log = None
        relay = None
        try:
            if args.mode == "start":
                log = (directory / "backend.log").open("a", encoding="utf-8")
                backend = subprocess.Popen(
                    backend_command,
                    cwd=source, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                def show_events():
                    for line in backend.stdout:
                        log.write(line)
                        log.flush()
                        sys.stdout.write(line)
                        sys.stdout.flush()
                relay = threading.Thread(target=show_events, daemon=True)
                relay.start()
            tunnel = ngrok.connect(addr="http://127.0.0.1:8000", proto="http",
                                   bind_tls=True, pyngrok_config=tunnel_config, **options)
            url = tunnel.public_url
            if not url.startswith("https://"):
                raise RuntimeError("Tunnel did not return HTTPS")
            if backend is not None and backend.poll() is not None:
                raise RuntimeError("Backend no pudo iniciar; consulte backend.log")
            config["API_BASE_URL"] = url.rstrip("/") + "/"
            config["TFG_BACKEND_URL"] = url.rstrip("/")
            protected = WindowsDpapiProtector().protect(json.dumps(config).encode())
            (directory / "config.dpapi").write_bytes(protected)
            print("URL HTTPS guardada en la configuracion local:", url)
            print("Mantenga esta ventana abierta durante el login y la sincronizacion.")
            print("El APK debe usar esta misma URL. El pago QR requiere ambos telefonos en la misma Wi-Fi.")
            print("Consola en vivo: login, autorizaciones, recargas y conciliacion.")
            print("Pagos offline entre telefonos aparecen aqui al sincronizar, no durante el intercambio local.")
            print("Presione Enter para cerrar la demostracion.")
            input()
        finally:
            # Dedicated executable path: do not stop an unrelated ngrok process.
            try:
                ngrok.kill(pyngrok_config=tunnel_config)
            finally:
                if backend is not None:
                    backend.terminate()
                    backend.wait()
                    if relay is not None:
                        relay.join(timeout=5)
                    backend.stdout.close()
                if log is not None:
                    log.close()
        return
    if args.mode == "credentials":
        # An explicit user action copies only demo login data, never JWT/private keys.
        clipboard = "Usuario: " + config["DEMO_MERCHANT_USERNAME"] + "\nContraseña: " + config["DEMO_MERCHANT_PASSWORD"]
        subprocess.run(["clip.exe"], input=clipboard, text=True, check=True)
        print("Credenciales del comercio copiadas al portapapeles. No compartir.")
        return
    if args.mode == "android":
        android = source.parent / "Prototipo Pagos Offline Android"
        environment["JAVA_HOME"] = r"C:\Program Files\Android\Android Studio\jbr"
        environment["ANDROID_HOME"] = str(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
        environment["DEMO_ISOLATED_INSTALL"] = "true"
        command = [str(android / "gradlew.bat"), ":app:assembleDebug", ":app:assembleDebugAndroidTest", "--console=plain"]
        cwd = android
    elif args.mode == "backend":
        command = backend_command
        cwd = source
    else:
        command = [sys.executable, "-m", "pos_desktop.app"]
        cwd = source
    raise SystemExit(subprocess.call(command, cwd=cwd, env=environment))


if __name__ == "__main__":
    main()
