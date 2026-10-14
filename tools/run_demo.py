"""Load DPAPI configuration only when explicitly requested by the operator."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backend", "pos", "android", "credentials", "tunnel"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--domain", help="Existing reserved ngrok hostname, without https://")
    args = parser.parse_args()
    from pos_desktop.key_store import WindowsDpapiProtector
    directory = args.directory.resolve()
    config = json.loads(WindowsDpapiProtector().unprotect((directory / "config.dpapi").read_bytes()))
    environment = dict(os.environ, **config)
    source = Path(__file__).resolve().parents[1]
    if args.mode == "tunnel":
        from getpass import getpass
        from pyngrok import ngrok
        from pyngrok.conf import PyngrokConfig
        token = os.getenv("NGROK_AUTHTOKEN") or getpass("Authtoken ngrok (entrada oculta): ")
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
        try:
            tunnel = ngrok.connect(addr="http://127.0.0.1:8000", proto="http",
                                   bind_tls=True, pyngrok_config=tunnel_config, **options)
            url = tunnel.public_url
            if not url.startswith("https://"):
                raise RuntimeError("Tunnel did not return HTTPS")
            config["API_BASE_URL"] = url.rstrip("/") + "/"
            config["TFG_BACKEND_URL"] = url.rstrip("/")
            protected = WindowsDpapiProtector().protect(json.dumps(config).encode())
            (directory / "config.dpapi").write_bytes(protected)
            print("URL HTTPS guardada en la configuracion local:", url)
            print("Mantenga esta ventana abierta. Compile Android en otra terminal.")
            input("Enter para cerrar el tunel: ")
        finally:
            # Dedicated executable path: do not stop an unrelated ngrok process.
            ngrok.kill(pyngrok_config=tunnel_config)
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
        command = [str(android / "gradlew.bat"), ":app:assembleDebug", ":app:assembleDebugAndroidTest", "--console=plain"]
        cwd = android
    elif args.mode == "backend":
        command = [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
        cwd = source
    else:
        command = [sys.executable, "-m", "pos_desktop.app"]
        cwd = source
    raise SystemExit(subprocess.call(command, cwd=cwd, env=environment))


if __name__ == "__main__":
    main()
