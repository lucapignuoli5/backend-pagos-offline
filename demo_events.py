"""Allowlisted operational events. Never log credentials or signed envelopes."""
import json
import logging
from decimal import Decimal

_FIELDS = {
    "usuario_id", "rol", "billetera", "autorizacion", "operacion",
    "comercio", "terminal", "centavos", "cantidad", "envio", "estado",
    "definitivo", "codigo", "metodo", "ruta", "http",
}
_LOGGER = logging.getLogger("payments.events")


def event(name, **fields):
    rendered = []
    for key, value in fields.items():
        if key not in _FIELDS or value is None:
            continue
        if key == "centavos" and type(value) is int:
            rendered.append("importe_ARS=" + format(Decimal(value) / 100, ".2f"))
        elif type(value) in (int, bool):
            rendered.append(f"{key}={value}")
        elif isinstance(value, str):
            # JSON quoting escapes newlines/control characters; cap diagnostic input.
            rendered.append(f"{key}=" + json.dumps(value[:120], ensure_ascii=True))
    _LOGGER.info("%s", name + " | " + " ".join(rendered))


class SafeFormatter(logging.Formatter):
    """Server exceptions show their class, never SQL parameters/request values."""
    _LIFECYCLE = (
        "Started server process", "Waiting for application startup",
        "Application startup complete", "Uvicorn running on",
        "Shutting down", "Waiting for application shutdown",
        "Application shutdown complete", "Finished server process",
    )

    def format(self, record):
        if record.name == "payments.events":
            return super().format(record)
        if record.exc_info:
            message = "ERROR INTERNO: " + record.exc_info[0].__name__
        else:
            text = record.getMessage()
            message = text if text.startswith(self._LIFECYCLE) else "AVISO DEL SERVIDOR: " + record.levelname
        safe = logging.LogRecord(record.name, record.levelno, "", 0, message, (), None)
        safe.created = record.created
        return super().format(safe)
