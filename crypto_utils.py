import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature


def verify_payment_contract_signature(
    payload_str: str | None = None,
    signature_b64: str | None = None,
    public_key_b64: str | None = None,
    contract_json: str | None = None,
    signature: str | None = None,
    public_key_pem: str | None = None,
) -> bool:
    payload = payload_str if payload_str is not None else contract_json
    sig = signature_b64 if signature_b64 is not None else signature
    pub = public_key_b64 if public_key_b64 is not None else public_key_pem
    if payload is None or sig is None or pub is None:
        return False
    try:
        pub_clean = pub.strip()
        if "BEGIN PUBLIC KEY" in pub_clean:
            public_key = serialization.load_pem_public_key(pub_clean.encode("utf-8"))
        else:
            pub_key_bytes = base64.b64decode(pub_clean, validate=True)
            public_key = serialization.load_der_public_key(pub_key_bytes)

        signature_bytes = base64.b64decode(sig.strip(), validate=True)

        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            return False

        public_key.verify(
            signature_bytes,
            payload.encode("utf-8"),
            ec.ECDSA(hashes.SHA256())
        )
        return True

    except (InvalidSignature, ValueError, TypeError):
        return False
