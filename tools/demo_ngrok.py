"""Local ngrok configuration; credentials never become command arguments."""
import logging
import os
from pathlib import Path
import re

from tools.demo_windows import DemoError, write_private_atomic


def _record(path, required=False):
    import yaml
    if not path.exists():
        return None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError()
        record = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(record, dict):
            raise ValueError()
        agent = record.get("agent", {})
        if not isinstance(agent, dict):
            raise ValueError()
        return record
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        if required:
            raise DemoError(
                "ngrok.yml de la carpeta demo no es una configuracion YAML legible. "
                "Corrijala localmente; no fue reemplazada."
            ) from None
        print("Se omitio una configuracion ngrok de Windows ilegible; no se mostro su contenido.")
        return None


def _token(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 8192 or not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
        return None
    return value


def _record_token(record):
    if not record:
        return None
    return _token(record.get("authtoken")) or _token(record.get("agent", {}).get("authtoken"))


def prepare_ngrok(directory, configure_token=False):
    """Use env > demo YAML > Windows YAML > hidden prompt, then private demo YAML.

    The parent shell is unaffected: only this launcher's environment is sanitized.
    Backend environment snapshots must independently exclude these keys.
    """
    from getpass import getpass
    import yaml
    local_path = directory / "ngrok.yml"
    local_record = _record(local_path, required=True)
    token = None
    if not configure_token:
        environment_token = os.environ.get("NGROK_AUTHTOKEN")
        token = _token(environment_token)
        if environment_token and not token:
            raise DemoError("NGROK_AUTHTOKEN tiene un formato no valido; corrija la variable local sin compartirla.")
        token = token or _record_token(local_record)
        if not token:
            candidates = []
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata:
                candidates.append(Path(local_appdata) / "ngrok" / "ngrok.yml")
            candidates.append(Path.home() / ".config" / "ngrok" / "ngrok.yml")
            for candidate in candidates:
                token = _record_token(_record(candidate))
                if token:
                    break
    if not token:
        token = _token(getpass("Authtoken ngrok (se guarda solo en esta PC; entrada oculta): "))
    if not token:
        raise DemoError("No se recibio un authtoken valido en la entrada local.")

    record = dict(local_record or {"version": "2"})
    version = str(record.get("version", "2"))
    if version not in {"2", "3"}:
        raise DemoError("La version de ngrok.yml debe ser 2 o 3; el archivo anterior se conserva.")
    record["version"] = version
    if version == "3":
        agent = dict(record.get("agent", {}))
        agent["authtoken"] = token
        record["agent"] = agent
        record.pop("authtoken", None)
    else:
        record["authtoken"] = token
    try:
        serialized = yaml.safe_dump(record, allow_unicode=False, sort_keys=False).encode("utf-8")
    except (TypeError, ValueError, yaml.YAMLError):
        raise DemoError("No se pudo preparar ngrok.yml; el archivo anterior se conserva.") from None
    write_private_atomic(local_path, serialized)

    # PyngrokConfig(None) otherwise copies NGROK_AUTHTOKEN into --authtoken.
    # Native ngrok also reads the environment, which must not override this file.
    os.environ.pop("NGROK_AUTHTOKEN", None)
    os.environ.pop("NGROK_API_KEY", None)
    from pyngrok.conf import PyngrokConfig
    config = PyngrokConfig(
        ngrok_path=str(directory / "ngrok.exe"), config_path=str(local_path),
        auth_token=None, api_key=None, startup_timeout=20, request_timeout=5,
    )
    config.auth_token = None
    config.api_key = None
    # Library error strings can contain account details; the launcher renders
    # only allowlisted error codes below, never logs or raw exceptions.
    from pyngrok import ngrok
    logging.getLogger("pyngrok").addHandler(logging.NullHandler())
    logging.getLogger("pyngrok").propagate = False
    logging.getLogger("pyngrok").setLevel(logging.CRITICAL + 1)
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if name.startswith("pyngrok.") and isinstance(logger, logging.Logger):
            logger.disabled = True
    return ngrok, config


def ngrok_error(error):
    """Extract a public error identifier in memory, without rendering its body."""
    codes = set(re.findall(r"ERR_NGROK_\d+", str(error)))
    if "ERR_NGROK_105" in codes:
        return DemoError(
            "ERR_NGROK_105: authtoken rechazado. Reabra con --configure-token "
            "para ingresarlo de forma oculta; no lo escriba en el CMD."
        )
    if "ERR_NGROK_313" in codes:
        return DemoError(
            "ERR_NGROK_313: la cuenta no permite el dominio pedido. "
            "Use --domain con el dominio asignado a su propia cuenta. No se cambio la URL."
        )
    if "ERR_NGROK_334" in codes:
        return DemoError(
            "ERR_NGROK_334: el dominio ya esta activo en otra sesion. "
            "Cierre esa sesion; no se detuvo ningun proceso ajeno ni se habilito pooling."
        )
    return DemoError("Ngrok no pudo abrir el tunel. Revise conectividad, cuenta y dominio localmente.")


def known_ngrok_process(config):
    """Read only pyngrok's in-process registry; never start or discover a daemon.

    This also covers interruption after Popen but before get_ngrok_process returns.
    The registry is an implementation detail of the project's pinned pyngrok.
    """
    from pyngrok import process
    registered = process._current_processes.get(config.ngrok_path)
    return registered.proc if registered is not None else None
