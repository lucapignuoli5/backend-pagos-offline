import base64
import binascii
from hashlib import sha256

from ecdsa import BadSignatureError, NIST256p, SECP256k1, VerifyingKey
from ecdsa.util import sigdecode_der, sigdecode_string


SUPPORTED_CURVES = (SECP256k1, NIST256p)


def verify_payment_contract_signature(
    contract_json: str,
    signature: str,
    public_key_pem: str,
) -> bool:
    try:
        public_key = VerifyingKey.from_pem(public_key_pem)
    except ValueError:
        return False

    if public_key.curve not in SUPPORTED_CURVES:
        return False

    try:
        signature_bytes = _decode_signature(signature)
    except ValueError:
        return False

    payload = contract_json.encode("utf-8")

    for decoder in (sigdecode_der, sigdecode_string):
        try:
            if public_key.verify(
                signature_bytes,
                payload,
                hashfunc=sha256,
                sigdecode=decoder,
            ):
                return True
        except (BadSignatureError, ValueError):
            continue

    return False


def _decode_signature(signature: str) -> bytes:
    normalized_signature = signature.strip()

    try:
        return bytes.fromhex(normalized_signature)
    except ValueError:
        pass

    try:
        return base64.b64decode(normalized_signature, validate=True)
    except binascii.Error as exc:
        raise ValueError("La firma debe estar codificada en hexadecimal o Base64") from exc
