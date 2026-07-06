import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature


def verify_payment_contract_signature(
    payload_str: str,
    signature_b64: str,
    public_key_b64: str,
) -> bool:
    try:
        # 1. Decodificar la clave pública de Base64 a bytes (DER)
        pub_key_bytes = base64.b64decode(public_key_b64)
        public_key = serialization.load_der_public_key(pub_key_bytes)

        # 2. Decodificar la firma de Base64 a bytes
        signature_bytes = base64.b64decode(signature_b64)

        # 3. Verificar la firma usando SHA256 y curva elíptica ECDSA
        public_key.verify(
            signature_bytes,
            payload_str.encode('utf-8'),
            ec.ECDSA(hashes.SHA256())
        )
        return True
        
    except (InvalidSignature, ValueError, TypeError) as e:
        print(f"Error de verificación criptográfica: {e}")
        return False
