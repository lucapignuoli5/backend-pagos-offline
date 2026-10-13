from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from protocol_v2 import encode_public_key, public_key_fingerprint
from pos_desktop.database import PosDatabase


class SecretProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...
    def unprotect(self, value: bytes) -> bytes: ...


class WindowsDpapiProtector:
    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("DPAPI solo esta disponible en Windows")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    def protect(self, value: bytes) -> bytes:
        return self._transform(value, self._crypt32.CryptProtectData)

    def unprotect(self, value: bytes) -> bytes:
        return self._transform(value, self._crypt32.CryptUnprotectData)

    def _transform(self, value: bytes, function) -> bytes:
        source_buffer = ctypes.create_string_buffer(value)
        source = self._Blob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
        target = self._Blob()
        if not function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            self._kernel32.LocalFree(target.pbData)


class PosKeyStore:
    def __init__(self, database: PosDatabase, protector: SecretProtector):
        self.database = database
        self.protector = protector

    def get_or_create(self, key_id: str) -> tuple[ec.EllipticCurvePrivateKey, str, str]:
        row = self.database.get_identity(key_id)
        if row is not None:
            private_key = serialization.load_der_private_key(
                self.protector.unprotect(bytes(row["protected_private_key"])), password=None
            )
            if not isinstance(private_key, ec.EllipticCurvePrivateKey):
                raise RuntimeError("La identidad POS almacenada no es EC")
            return private_key, row["public_key_b64"], row["fingerprint"]

        private_key = ec.generate_private_key(ec.SECP256R1())
        private_der = private_key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        public_b64 = encode_public_key(private_key.public_key())
        fingerprint = public_key_fingerprint(base64.b64decode(public_b64))
        self.database.save_identity(
            key_id, public_b64, fingerprint, self.protector.protect(private_der),
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        return private_key, public_b64, fingerprint

