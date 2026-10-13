from __future__ import annotations

from typing import Protocol

from protocol_v2 import SELECT_APDU, SW_OK


class ApduTransport(Protocol):
    def connect(self) -> None: ...
    def transceive(self, apdu: bytes) -> bytes: ...
    def close(self) -> None: ...


class PcscTransport:
    """Adaptador del ACR122U. El import de pyscard es tardio para permitir simulacion."""

    def __init__(self, reader_name: str | None = None):
        self.reader_name = reader_name
        self._connection = None

    def connect(self) -> None:
        try:
            from smartcard.System import readers
        except ImportError as exc:
            raise RuntimeError("pyscard no esta instalado") from exc
        available = list(readers())
        if self.reader_name:
            available = [reader for reader in available if self.reader_name in str(reader)]
        if not available:
            raise RuntimeError("No se encontro el lector PC/SC configurado")
        self._connection = available[0].createConnection()
        self._connection.connect()

    def transceive(self, apdu: bytes) -> bytes:
        if self._connection is None:
            raise RuntimeError("El lector no esta conectado")
        data, sw1, sw2 = self._connection.transmit(list(apdu))
        return bytes(data + [sw1, sw2])

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.disconnect()
            finally:
                self._connection = None


def select_hce(transport: ApduTransport) -> bytes:
    response = transport.transceive(SELECT_APDU)
    if not response.endswith(SW_OK):
        raise RuntimeError("Android HCE rechazo SELECT")
    return response[:-2]


def require_ok(response: bytes, action: str) -> bytes:
    if len(response) < 2 or response[-2:] != SW_OK:
        status = response[-2:].hex().upper() if len(response) >= 2 else "SIN_SW"
        raise RuntimeError(f"{action} fallo con estado {status}")
    return response[:-2]

