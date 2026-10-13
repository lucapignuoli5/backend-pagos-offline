"""Contrato criptografico y framing NFC compartidos por backend y POS."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


PROTOCOL_VERSION = 2
CURRENCY = "ARS"
MAX_MESSAGE_BYTES = 4 * 1024
DEFAULT_CHUNK_BYTES = 160
MAX_AMOUNT_CENTS = 100_000
MAX_REQUEST_LIFETIME_SECONDS = 120
NONCE_BYTES = 16
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]{22}$")

AID = bytes.fromhex("F222222222")
SELECT_APDU = bytes.fromhex("00A4040005F222222222")
CLA_TFG = 0x80
INS_PUT_REQUEST = 0x10
INS_GET_STATUS = 0x20
INS_GET_RECEIPT = 0x30
INS_PUT_ACK = 0x40
P2_MORE = 0x00
P2_LAST = 0x01
SW_OK = bytes.fromhex("9000")
SW_BAD_DATA = bytes.fromhex("6A80")
SW_NOT_FOUND = bytes.fromhex("6A82")
SW_CONDITIONS_NOT_SATISFIED = bytes.fromhex("6985")


class MessageType(str, Enum):
    PAYMENT_REQUEST = "payment_request"
    PAYMENT_RECEIPT = "payment_receipt"
    PAYMENT_ACK = "payment_ack"


COMMON_FIELDS = {
    "version",
    "type",
    "operation_id",
    "merchant_id",
    "terminal_id",
    "amount_cents",
    "currency",
    "nonce",
    "issued_at",
    "expires_at",
}
REQUEST_FIELDS = COMMON_FIELDS | {"pos_key_id", "pos_key_fingerprint"}
RECEIPT_FIELDS = COMMON_FIELDS | {
    "wallet_id",
    "offline_authorization_id",
    "wallet_key_id",
    "wallet_key_fingerprint",
    "request_digest",
}
ACK_FIELDS = COMMON_FIELDS | {
    "wallet_id",
    "offline_authorization_id",
    "pos_key_id",
    "pos_key_fingerprint",
    "receipt_digest",
    "accepted_at",
    "status",
}


class ProtocolError(ValueError):
    """Mensaje incompatible con el protocolo v2."""


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Serializa exactamente los campos recibidos como JSON canonico UTF-8."""
    try:
        return json.dumps(
            dict(payload),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError("El payload no puede representarse como JSON canonico") from exc


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    encoded = canonical_json(payload).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ProtocolError("El mensaje supera el maximo logico de 4 KiB")
    return encoded


def payload_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def public_key_fingerprint(public_key_der: bytes) -> str:
    return hashlib.sha256(public_key_der).hexdigest()


def encode_public_key(public_key: ec.EllipticCurvePublicKey) -> str:
    _require_p256(public_key)
    der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(der).decode("ascii")


def sign_payload(payload: Mapping[str, Any], private_key: ec.EllipticCurvePrivateKey) -> str:
    _require_p256(private_key.public_key())
    signature = private_key.sign(canonical_bytes(payload), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode("ascii")


def verify_payload_signature(
    payload: Mapping[str, Any], signature_b64: str, public_key_b64: str
) -> bool:
    try:
        public_der = base64.b64decode(public_key_b64, validate=True)
        signature = base64.b64decode(signature_b64, validate=True)
        public_key = serialization.load_der_public_key(public_der)
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            return False
        _require_p256(public_key)
        public_key.verify(signature, canonical_bytes(payload), ec.ECDSA(hashes.SHA256()))
        return True
    except (binascii.Error, InvalidSignature, ProtocolError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class SignedEnvelope:
    payload_bytes: bytes
    payload: dict[str, Any]
    signature_b64: str

    def verify(self, public_key_b64: str) -> bool:
        return verify_exact_signature(self.payload_bytes, self.signature_b64, public_key_b64)


def encode_signed_envelope(payload: Mapping[str, Any], signature_b64: str) -> bytes:
    payload_bytes = canonical_bytes(payload)
    _decode_base64(signature_b64, "signature_b64")
    envelope = {
        "payload_b64": base64.b64encode(payload_bytes).decode("ascii"),
        "signature_b64": signature_b64,
    }
    encoded = canonical_json(envelope).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ProtocolError("El sobre firmado supera el maximo logico de 4 KiB")
    return encoded


def parse_signed_envelope(data: bytes) -> SignedEnvelope:
    if not data or len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Longitud de sobre firmado invalida")
    try:
        text = data.decode("utf-8")
        envelope = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Sobre firmado invalido") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"payload_b64", "signature_b64"}:
        raise ProtocolError("Campos de sobre firmado incompatibles")
    if canonical_json(envelope) != text:
        raise ProtocolError("El sobre firmado no es canonico")
    payload_bytes = _decode_base64(envelope["payload_b64"], "payload_b64")
    _decode_base64(envelope["signature_b64"], "signature_b64")
    payload = parse_canonical_payload(payload_bytes)
    return SignedEnvelope(payload_bytes, payload, envelope["signature_b64"])


def verify_exact_signature(payload_bytes: bytes, signature_b64: str, public_key_b64: str) -> bool:
    try:
        public_der = base64.b64decode(public_key_b64, validate=True)
        signature = base64.b64decode(signature_b64, validate=True)
        public_key = serialization.load_der_public_key(public_der)
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            return False
        _require_p256(public_key)
        public_key.verify(signature, payload_bytes, ec.ECDSA(hashes.SHA256()))
        return True
    except (binascii.Error, InvalidSignature, ProtocolError, TypeError, ValueError):
        return False


def validate_payload(payload: Mapping[str, Any]) -> MessageType:
    if not isinstance(payload, Mapping):
        raise ProtocolError("El payload debe ser un objeto JSON")
    message_type = _message_type(payload.get("type"))
    expected = {
        MessageType.PAYMENT_REQUEST: REQUEST_FIELDS,
        MessageType.PAYMENT_RECEIPT: RECEIPT_FIELDS,
        MessageType.PAYMENT_ACK: ACK_FIELDS,
    }[message_type]
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ProtocolError(f"Campos incompatibles; faltan={missing}, sobran={extra}")

    if payload["version"] != PROTOCOL_VERSION or isinstance(payload["version"], bool):
        raise ProtocolError("Version de protocolo no soportada")
    _canonical_uuid(payload["operation_id"])
    for field in ("merchant_id", "terminal_id"):
        _identifier(payload[field], field)
    amount = payload["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ProtocolError("amount_cents debe ser entero")
    if not 1 <= amount <= MAX_AMOUNT_CENTS:
        raise ProtocolError("amount_cents esta fuera del limite configurado")
    if payload["currency"] != CURRENCY:
        raise ProtocolError("Solo se admite ARS")
    _nonce(payload["nonce"])
    issued_at = _timestamp(payload["issued_at"], "issued_at")
    expires_at = _timestamp(payload["expires_at"], "expires_at")
    if expires_at <= issued_at:
        raise ProtocolError("expires_at debe ser posterior a issued_at")
    if message_type is MessageType.PAYMENT_REQUEST:
        if (expires_at - issued_at).total_seconds() > MAX_REQUEST_LIFETIME_SECONDS:
            raise ProtocolError("La solicitud supera los dos minutos de validez")
        _key_reference(payload, "pos")
    elif message_type is MessageType.PAYMENT_RECEIPT:
        _identifier(payload["wallet_id"], "wallet_id")
        _identifier(payload["offline_authorization_id"], "offline_authorization_id")
        _key_reference(payload, "wallet")
        _digest(payload["request_digest"], "request_digest")
    else:
        _identifier(payload["wallet_id"], "wallet_id")
        _identifier(payload["offline_authorization_id"], "offline_authorization_id")
        _key_reference(payload, "pos")
        _digest(payload["receipt_digest"], "receipt_digest")
        accepted_at = _timestamp(payload["accepted_at"], "accepted_at")
        if accepted_at < issued_at:
            raise ProtocolError("accepted_at no puede preceder a issued_at")
        if accepted_at > expires_at:
            raise ProtocolError("accepted_at no puede ser posterior a expires_at")
        if payload["status"] != "LOCALLY_ACCEPTED":
            raise ProtocolError("Estado de acuse no soportado")
    canonical_bytes(payload)
    return message_type


def parse_canonical_payload(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("El mensaje supera el maximo logico de 4 KiB")
    try:
        text = data.decode("utf-8")
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("JSON UTF-8 invalido") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("El payload debe ser un objeto JSON")
    validate_payload(payload)
    if canonical_json(payload) != text:
        raise ProtocolError("El JSON recibido no es canonico")
    return payload


@dataclass(frozen=True)
class ApduCommand:
    instruction: int
    sequence: int
    is_last: bool
    data: bytes


def build_apdu(instruction: int, sequence: int, is_last: bool, data: bytes = b"") -> bytes:
    if instruction not in {INS_PUT_REQUEST, INS_GET_STATUS, INS_GET_RECEIPT, INS_PUT_ACK}:
        raise ProtocolError("Instruccion APDU no soportada")
    if not 0 <= sequence <= 255:
        raise ProtocolError("Secuencia APDU fuera de rango")
    if len(data) > 255:
        raise ProtocolError("Un APDU corto no admite mas de 255 bytes")
    p2 = P2_LAST if is_last else P2_MORE
    return bytes((CLA_TFG, instruction, sequence, p2, len(data))) + data


def parse_apdu(apdu: bytes) -> ApduCommand:
    if len(apdu) < 5 or apdu[0] != CLA_TFG:
        raise ProtocolError("Cabecera APDU invalida")
    instruction, sequence, p2, length = apdu[1], apdu[2], apdu[3], apdu[4]
    if instruction not in {INS_PUT_REQUEST, INS_GET_STATUS, INS_GET_RECEIPT, INS_PUT_ACK}:
        raise ProtocolError("Instruccion APDU no soportada")
    if p2 not in {P2_MORE, P2_LAST} or len(apdu) != 5 + length:
        raise ProtocolError("Longitud o indicador APDU invalido")
    return ApduCommand(instruction, sequence, p2 == P2_LAST, apdu[5:])


def chunk_message(data: bytes, chunk_size: int = DEFAULT_CHUNK_BYTES) -> list[bytes]:
    if not data or len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Longitud logica de mensaje invalida")
    if not 1 <= chunk_size <= 255:
        raise ProtocolError("Tamano de fragmento invalido")
    return [data[index : index + chunk_size] for index in range(0, len(data), chunk_size)]


def assemble_chunks(chunks: list[bytes]) -> bytes:
    data = b"".join(chunks)
    if not data or len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Longitud logica de mensaje invalida")
    return data


def _message_type(value: Any) -> MessageType:
    try:
        return MessageType(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("Tipo de mensaje no soportado") from exc


def _decode_base64(value: Any, field: str) -> bytes:
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        raise ProtocolError(f"{field} debe ser Base64 sin saltos")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError(f"{field} debe ser Base64 valido") from exc


def _canonical_uuid(value: Any) -> UUID:
    if not isinstance(value, str):
        raise ProtocolError("operation_id debe ser UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ProtocolError("operation_id debe ser UUID") from exc
    if str(parsed) != value or parsed.version != 4:
        raise ProtocolError("operation_id debe ser UUID v4 canonico")
    return parsed


def _identifier(value: Any, field: str) -> None:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ProtocolError(f"{field} es invalido")


def _digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not FINGERPRINT_PATTERN.fullmatch(value):
        raise ProtocolError(f"{field} debe ser SHA-256 hexadecimal")


def _key_reference(payload: Mapping[str, Any], prefix: str) -> None:
    _identifier(payload[f"{prefix}_key_id"], f"{prefix}_key_id")
    value = payload[f"{prefix}_key_fingerprint"]
    if not isinstance(value, str) or not FINGERPRINT_PATTERN.fullmatch(value):
        raise ProtocolError(f"{prefix}_key_fingerprint es invalida")


def _nonce(value: Any) -> None:
    if not isinstance(value, str) or not BASE64URL_PATTERN.fullmatch(value):
        raise ProtocolError("nonce debe contener 128 bits en Base64url sin relleno")
    try:
        decoded = base64.urlsafe_b64decode(value + "==")
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError("nonce invalido") from exc
    if len(decoded) != NONCE_BYTES:
        raise ProtocolError("nonce debe contener 128 bits")


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ProtocolError(f"{field} debe estar en UTC sin fracciones")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ProtocolError(f"{field} es invalido") from exc


def _require_p256(public_key: ec.EllipticCurvePublicKey) -> None:
    if not isinstance(public_key.curve, ec.SECP256R1):
        raise ProtocolError("La clave debe usar ECDSA P-256")
