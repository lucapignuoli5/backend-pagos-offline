"""Explicit issuer identity: encrypted external file, pinned public fingerprint."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping, Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pos_desktop.key_store import SecretProtector, WindowsDpapiProtector


def _external(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    source = Path(__file__).resolve().parent
    if resolved.is_relative_to(source) or any((p / '.git').exists() for p in resolved.parents):
        raise ValueError('Issuer private identity must be outside Git repositories')
    return resolved


class IssuerIdentity:
    def __init__(self, key_id: str, private_key: ec.EllipticCurvePrivateKey):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,119}', key_id):
            raise ValueError('Invalid issuer key ID')
        if not isinstance(private_key.curve, ec.SECP256R1):
            raise ValueError('Issuer key must be P-256')
        self.key_id = key_id
        self._private_key = private_key
        public = private_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.public_key_b64 = base64.b64encode(public).decode('ascii')
        self.fingerprint = hashlib.sha256(public).hexdigest()

    @classmethod
    def create_external(cls, path: Path, key_id: str, protector: SecretProtector | None = None) -> 'IssuerIdentity':
        target = _external(path)
        identity = cls(key_id, ec.generate_private_key(ec.SECP256R1()))
        protector = protector or WindowsDpapiProtector()
        private = identity._private_key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        protected = protector.protect(private)
        if protected == private:
            raise ValueError('Identity protector returned plaintext')
        record = {'key_id': identity.key_id, 'public_key_b64': identity.public_key_b64,
                  'fingerprint': identity.fingerprint, 'protected_private_key_b64': base64.b64encode(protected).decode('ascii')}
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            json.dump(record, stream, sort_keys=True, separators=(',', ':'))
        return identity

    @classmethod
    def load_external(cls, path: Path, expected_fingerprint: str, protector: SecretProtector | None = None) -> 'IssuerIdentity':
        target = _external(path)
        if not re.fullmatch(r'[0-9a-f]{64}', expected_fingerprint):
            raise ValueError('A trusted issuer fingerprint is required')
        record = json.loads(target.read_text(encoding='utf-8'))
        if set(record) != {'key_id', 'public_key_b64', 'fingerprint', 'protected_private_key_b64'}:
            raise ValueError('Invalid issuer identity file')
        protector = protector or WindowsDpapiProtector()
        protected = base64.b64decode(record['protected_private_key_b64'], validate=True)
        key = serialization.load_der_private_key(protector.unprotect(protected), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError('Issuer key must be EC')
        identity = cls(record['key_id'], key)
        if identity.fingerprint != expected_fingerprint or record['fingerprint'] != expected_fingerprint or identity.public_key_b64 != record['public_key_b64']:
            raise ValueError('Issuer identity does not match its trusted public key')
        return identity

    def sign_envelope(self, payload: Mapping[str, Any]) -> bytes:
        from protocol_v3 import encode_signed_envelope, sign_payload
        return encode_signed_envelope(payload, sign_payload(payload, self._private_key))

    def public_record(self) -> dict[str, str]:
        return {'key_id': self.key_id, 'public_key_b64': self.public_key_b64, 'fingerprint': self.fingerprint}
