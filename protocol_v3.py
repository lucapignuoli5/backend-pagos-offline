"""Pure v3 wire contract. No database, network, filesystem or application imports."""
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

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

PROTOCOL_VERSION = 3
MAX_MESSAGE_BYTES = 4096
DEFAULT_CHUNK_BYTES = 160
INS_GET_AUTHORIZATION = 0x50
MAX_INT64 = 2**63 - 1
MAX_REQUEST_LIFETIME_SECONDS = 120
CURRENCY = "ARS"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", re.ASCII)
P256_ORDER = int("ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551", 16)


class ProtocolError(ValueError):
    """Invalid or incompatible v3 evidence."""


class MessageType(str, Enum):
    PAYMENT_REQUEST = "payment_request"
    OFFLINE_AUTHORIZATION = "offline_authorization"
    PAYMENT_RECEIPT = "payment_receipt"
    PAYMENT_ACK = "payment_ack"
    OFFLINE_AUTHORIZATION_CLOSE = "offline_authorization_close"
    PAYMENT_RESOLUTION = "payment_resolution"
    KEY_REGISTRATION = "key_registration"


@dataclass(frozen=True)
class SelectCapabilities:
    max_message_bytes: int
    chunk_bytes: int
    authorization_instruction: int = INS_GET_AUTHORIZATION


COMMON_FIELDS = {"version", "type", "operation_id", "merchant_id", "terminal_id",
                 "amount_cents", "currency", "nonce", "issued_at", "expires_at"}
REQUEST_FIELDS = COMMON_FIELDS | {"pos_key_id", "pos_key_fingerprint"}
AUTHORIZATION_FIELDS = {"version", "type", "authorization_id", "wallet_id", "wallet_key_id",
                        "wallet_key_fingerprint", "wallet_public_key_b64", "currency",
                        "max_payment_cents", "max_payments", "authorized_total_cents",
                        "max_request_lifetime_seconds", "issued_at", "spend_expires_at",
                        "issuer_key_id", "issuer_key_fingerprint"}
RECEIPT_FIELDS = COMMON_FIELDS | {"wallet_id", "offline_authorization_id", "wallet_key_id",
                               "wallet_key_fingerprint", "request_digest", "authorization_digest",
                               "issuance_index", "confirmed_at"}
ACK_FIELDS = COMMON_FIELDS | {"wallet_id", "offline_authorization_id", "pos_key_id",
                           "pos_key_fingerprint", "receipt_digest", "accepted_at", "status"}
CLOSE_FIELDS = {"version", "type", "closure_id", "authorization_id", "wallet_id", "wallet_key_id",
                "wallet_key_fingerprint", "authorization_digest", "final_issuance_index",
                "emitted_total_cents", "manifest_digest", "issued_at"}
RESOLUTION_FIELDS = {"version", "type", "operation_id", "wallet_id", "merchant_id", "terminal_id",
                     "amount_cents", "currency", "offline_authorization_id", "authorization_digest",
                     "request_digest", "receipt_digest", "operation_status", "code",
                     "resolution_revision", "resolved_at", "issuer_key_id", "issuer_key_fingerprint"}
KEY_REGISTRATION_FIELDS = {"version", "type", "key_id", "purpose", "owner_user_id", "scope_id",
                           "fingerprint", "nonce", "issued_at"}
FIELDS = {MessageType.PAYMENT_REQUEST: REQUEST_FIELDS,
          MessageType.OFFLINE_AUTHORIZATION: AUTHORIZATION_FIELDS,
          MessageType.PAYMENT_RECEIPT: RECEIPT_FIELDS, MessageType.PAYMENT_ACK: ACK_FIELDS,
          MessageType.OFFLINE_AUTHORIZATION_CLOSE: CLOSE_FIELDS,
          MessageType.PAYMENT_RESOLUTION: RESOLUTION_FIELDS,
          MessageType.KEY_REGISTRATION: KEY_REGISTRATION_FIELDS}
MANIFEST_FIELDS = {"issuance_index", "operation_id", "amount_cents", "receipt_digest"}


def _validate_json_value(value: Any) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ProtocolError("Invalid UTF-8 string") from exc
    elif type(value) is int:
        if not -MAX_INT64 - 1 <= value <= MAX_INT64:
            raise ProtocolError("Integer outside int64")
    elif isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ProtocolError("JSON object keys must be strings")
        for key, child in value.items():
            _validate_json_value(key)
            _validate_json_value(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_json_value(child)
    else:
        raise ProtocolError("Only strings, int64, objects and arrays are allowed")


def canonical_bytes(value: Any) -> bytes:
    """Sorted keys, literal UTF-8, no HTML escaping, floats, booleans or null."""
    try:
        _validate_json_value(value)
        data = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProtocolError("Invalid canonical JSON") from exc
    if not data or len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Message exceeds 4096 bytes")
    return data


def canonical_json(value: Any) -> str:
    return canonical_bytes(value).decode("utf-8")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("Duplicate JSON field")
        result[key] = value
    return result


def _reject_number(value: str) -> Any:
    raise ProtocolError("Floats and nonfinite numbers are forbidden")


def _parse_json(data: bytes) -> Any:
    if not isinstance(data, bytes) or not data or len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Invalid message length")
    try:
        value = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs,
                           parse_float=_reject_number, parse_constant=_reject_number)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("Invalid JSON UTF-8") from exc
    if canonical_bytes(value) != data:
        raise ProtocolError("Message is not canonical")
    return value


def decode_base64(value: Any, field: str = "base64") -> bytes:
    if not isinstance(value, str) or not value or not value.isascii():
        raise ProtocolError(f"Invalid {field}")
    try:
        result = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError(f"Invalid {field}") from exc
    if base64.b64encode(result).decode("ascii") != value:
        raise ProtocolError(f"Noncanonical {field}")
    return result


def public_key_fingerprint(public_key_der: bytes) -> str:
    return hashlib.sha256(public_key_der).hexdigest()


def decode_public_key(public_key_b64: str) -> ec.EllipticCurvePublicKey:
    data = decode_base64(public_key_b64, "public key")
    try:
        key = serialization.load_der_public_key(data)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise ProtocolError("Invalid DER public key") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ProtocolError("Public key must use P-256")
    if key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != data:
        raise ProtocolError("Public key must use canonical SPKI DER")
    return key


def encode_public_key(public_key: ec.EllipticCurvePublicKey) -> str:
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(public_key.curve, ec.SECP256R1):
        raise ProtocolError("Public key must use P-256")
    data = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(data).decode("ascii")


def _signature_bytes(signature_b64: str) -> bytes:
    data = decode_base64(signature_b64, "signature")
    try:
        r, s = utils.decode_dss_signature(data)
    except ValueError as exc:
        raise ProtocolError("Signature must use canonical DER") from exc
    if not 1 <= r < P256_ORDER or not 1 <= s < P256_ORDER or utils.encode_dss_signature(r, s) != data:
        raise ProtocolError("Invalid P-256 DER signature")
    return data


def verify_exact_signature(payload_bytes: bytes, signature_b64: str, public_key_b64: str) -> bool:
    try:
        key = decode_public_key(public_key_b64)
        key.verify(_signature_bytes(signature_b64), payload_bytes, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ProtocolError, TypeError, ValueError):
        return False


def payload_digest(payload: bytes | Mapping[str, Any] | "SignedEnvelope") -> str:
    """Use original payload bytes for received evidence; mappings are producer-only."""
    if isinstance(payload, SignedEnvelope):
        data = payload.payload_bytes
    elif isinstance(payload, bytes):
        data = payload
    else:
        data = canonical_bytes(payload)
    if not data or len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Invalid payload length")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SignedEnvelope:
    payload_bytes: bytes
    payload: dict[str, Any]
    signature_b64: str

    def verify(self, public_key_b64: str) -> bool:
        return verify_exact_signature(self.payload_bytes, self.signature_b64, public_key_b64)


def sign_payload(payload: Mapping[str, Any], private_key: ec.EllipticCurvePrivateKey) -> str:
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(private_key.curve, ec.SECP256R1):
        raise ProtocolError("Private key must use P-256")
    validate_payload(payload)
    signature = private_key.sign(canonical_bytes(payload), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode("ascii")


def encode_signed_envelope(payload: bytes | Mapping[str, Any], signature_b64: str) -> bytes:
    data = payload if isinstance(payload, bytes) else canonical_bytes(payload)
    parse_canonical_payload(data)
    _signature_bytes(signature_b64)
    return canonical_bytes({"payload_b64": base64.b64encode(data).decode("ascii"),
                            "signature_b64": signature_b64})


def parse_signed_envelope(data: bytes) -> SignedEnvelope:
    envelope = _parse_json(data)
    if not isinstance(envelope, dict) or set(envelope) != {"payload_b64", "signature_b64"}:
        raise ProtocolError("Invalid envelope fields")
    payload_bytes = decode_base64(envelope["payload_b64"], "payload_b64")
    _signature_bytes(envelope["signature_b64"])
    return SignedEnvelope(payload_bytes, parse_canonical_payload(payload_bytes), envelope["signature_b64"])


def parse_canonical_payload(data: bytes) -> dict[str, Any]:
    payload = _parse_json(data)
    validate_payload(payload)
    return payload


def _identifier(value: Any, field: str) -> None:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ProtocolError(f"Invalid {field}")


def _digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or not DIGEST_PATTERN.fullmatch(value):
        raise ProtocolError(f"Invalid {field}")


def _integer(value: Any, field: str, minimum: int = 1, maximum: int = MAX_INT64) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolError(f"Invalid integer {field}")


def _uuid(value: Any, field: str) -> None:
    try:
        parsed = UUID(value) if isinstance(value, str) else None
    except ValueError as exc:
        raise ProtocolError(f"Invalid {field}") from exc
    if parsed is None or parsed.version != 4 or str(parsed) != value:
        raise ProtocolError(f"Invalid UUID v4 {field}")


def parse_timestamp(value: Any, field: str = "timestamp") -> datetime:
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value):
        raise ProtocolError(f"Invalid UTC seconds {field}")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ProtocolError(f"Invalid {field}") from exc


def timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProtocolError("Timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nonce(value: Any) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{22}", value):
        raise ProtocolError("Nonce must contain 128 bits")
    data = base64.urlsafe_b64decode(value + "==")
    if len(data) != 16 or base64.urlsafe_b64encode(data).decode("ascii").rstrip("=") != value:
        raise ProtocolError("Nonce must use canonical Base64url")


def validate_payload(payload: Mapping[str, Any]) -> MessageType:
    if not isinstance(payload, Mapping):
        raise ProtocolError("Payload must be an object")
    try:
        kind = MessageType(payload.get("type"))
    except (ValueError, TypeError) as exc:
        raise ProtocolError("Unsupported message type") from exc
    if set(payload) != FIELDS[kind]:
        raise ProtocolError("Missing or unknown payload fields")
    if type(payload["version"]) is not int or payload["version"] != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported protocol version")
    for field in ("operation_id", "closure_id"):
        if field in payload:
            _uuid(payload[field], field)
    for field in ("authorization_id", "offline_authorization_id", "wallet_id", "merchant_id",
                  "terminal_id", "wallet_key_id", "pos_key_id", "issuer_key_id", "key_id", "scope_id", "code"):
        if field in payload:
            _identifier(payload[field], field)
    for field in ("wallet_key_fingerprint", "pos_key_fingerprint", "issuer_key_fingerprint", "fingerprint",
                  "request_digest", "receipt_digest", "authorization_digest", "manifest_digest"):
        if field in payload:
            _digest(payload[field], field)
    for field in ("amount_cents", "max_payment_cents", "max_payments", "authorized_total_cents",
                  "issuance_index", "resolution_revision", "owner_user_id"):
        if field in payload:
            _integer(payload[field], field)
    for field in ("final_issuance_index", "emitted_total_cents"):
        if field in payload:
            _integer(payload[field], field, minimum=0)
    if "currency" in payload and payload["currency"] != CURRENCY:
        raise ProtocolError("Only ARS is supported")
    if "nonce" in payload:
        _nonce(payload["nonce"])
    times = {field: parse_timestamp(payload[field], field) for field in
             ("issued_at", "expires_at", "confirmed_at", "accepted_at", "spend_expires_at", "resolved_at")
             if field in payload}
    if "expires_at" in times:
        lifetime = (times["expires_at"] - times["issued_at"]).total_seconds()
        if not 0 < lifetime <= MAX_REQUEST_LIFETIME_SECONDS:
            raise ProtocolError("Request lifetime must be at most 120 seconds")
    if "confirmed_at" in times and not times["issued_at"] <= times["confirmed_at"] <= times["expires_at"]:
        raise ProtocolError("Confirmation outside request window")
    if "accepted_at" in times and not times["issued_at"] <= times["accepted_at"] <= times["expires_at"]:
        raise ProtocolError("Acceptance outside request window")
    if kind is MessageType.OFFLINE_AUTHORIZATION:
        if times["spend_expires_at"] <= times["issued_at"]:
            raise ProtocolError("Invalid issuance window")
        _integer(payload["max_request_lifetime_seconds"], "max_request_lifetime_seconds", maximum=120)
        if payload["max_payment_cents"] * payload["max_payments"] > MAX_INT64:
            raise ProtocolError("Authorization multiplication overflow")
        if payload["authorized_total_cents"] > payload["max_payment_cents"] * payload["max_payments"]:
            raise ProtocolError("Authorization total exceeds its limits")
        key = decode_public_key(payload["wallet_public_key_b64"])
        if public_key_fingerprint(decode_base64(encode_public_key(key))) != payload["wallet_key_fingerprint"]:
            raise ProtocolError("Wallet public key fingerprint mismatch")
    elif kind is MessageType.PAYMENT_ACK and payload["status"] != "LOCALLY_ACCEPTED":
        raise ProtocolError("Unsupported acknowledgement state")
    elif kind is MessageType.PAYMENT_RESOLUTION:
        if payload["operation_status"] not in ("ACCEPTED", "REJECTED"):
            raise ProtocolError("Resolution must be final")
    elif kind is MessageType.KEY_REGISTRATION and payload["purpose"] not in ("wallet", "pos"):
        raise ProtocolError("Unsupported key purpose")
    canonical_bytes(payload)
    return kind


def _require_kind(envelope: SignedEnvelope, kind: MessageType) -> None:
    if validate_payload(envelope.payload) is not kind or canonical_bytes(envelope.payload) != envelope.payload_bytes:
        raise ProtocolError("Unexpected envelope type or changed payload")


def verify_authorization(grant: SignedEnvelope, issuer_public_b64: str,
                         expected_issuer_key_id: str | None = None) -> bool:
    try:
        _require_kind(grant, MessageType.OFFLINE_AUTHORIZATION)
        fingerprint = public_key_fingerprint(decode_base64(issuer_public_b64))
        return (grant.payload["issuer_key_fingerprint"] == fingerprint
                and (expected_issuer_key_id is None or grant.payload["issuer_key_id"] == expected_issuer_key_id)
                and grant.verify(issuer_public_b64))
    except ProtocolError:
        return False


def verify_pos_signer(envelope: SignedEnvelope, public_key_b64: str, key_id: str,
                      fingerprint: str, merchant_id: str, terminal_id: str) -> bool:
    """The supplied scope must come from a trusted catalog, not the message."""
    try:
        kind = validate_payload(envelope.payload)
        if kind not in (MessageType.PAYMENT_REQUEST, MessageType.PAYMENT_ACK):
            return False
        _require_kind(envelope, kind)
        ep = envelope.payload
        return (ep["pos_key_id"] == key_id and ep["pos_key_fingerprint"] == fingerprint
                and public_key_fingerprint(decode_base64(public_key_b64)) == fingerprint
                and ep["merchant_id"] == merchant_id and ep["terminal_id"] == terminal_id
                and envelope.verify(public_key_b64))
    except ProtocolError:
        return False


def encode_select_capabilities(max_message_bytes: int = MAX_MESSAGE_BYTES,
                               chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> bytes:
    payload = {"protocol_version": PROTOCOL_VERSION, "max_message_bytes": max_message_bytes,
               "chunk_bytes": chunk_bytes, "authorization_instruction": INS_GET_AUTHORIZATION}
    data = canonical_bytes(payload)
    parse_select_capabilities(data)
    return data


def parse_select_capabilities(data: bytes) -> SelectCapabilities:
    """Parse SELECT body (excluding SW). Never treats SELECT as payment evidence."""
    payload = _parse_json(data)
    if not isinstance(payload, dict) or set(payload) != {"protocol_version", "max_message_bytes", "chunk_bytes", "authorization_instruction"}:
        raise ProtocolError("Invalid SELECT capability fields")
    _integer(payload["protocol_version"], "protocol_version", minimum=3, maximum=3)
    _integer(payload["max_message_bytes"], "max_message_bytes", minimum=MAX_MESSAGE_BYTES, maximum=MAX_MESSAGE_BYTES)
    _integer(payload["chunk_bytes"], "chunk_bytes", maximum=DEFAULT_CHUNK_BYTES)
    _integer(payload["authorization_instruction"], "authorization_instruction", minimum=INS_GET_AUTHORIZATION, maximum=INS_GET_AUTHORIZATION)
    return SelectCapabilities(payload["max_message_bytes"], payload["chunk_bytes"], payload["authorization_instruction"])


def validate_receipt_binding(request: SignedEnvelope, receipt: SignedEnvelope, grant: SignedEnvelope) -> None:
    """Bindings only: callers must separately verify POS and issuer signatures/trust."""
    _require_kind(request, MessageType.PAYMENT_REQUEST)
    _require_kind(receipt, MessageType.PAYMENT_RECEIPT)
    _require_kind(grant, MessageType.OFFLINE_AUTHORIZATION)
    for field in COMMON_FIELDS - {"type"}:
        if request.payload[field] != receipt.payload[field]:
            raise ProtocolError(f"Request/receipt mismatch: {field}")
    rp, gp = receipt.payload, grant.payload
    if rp["request_digest"] != payload_digest(request) or rp["authorization_digest"] != payload_digest(grant):
        raise ProtocolError("Receipt digest mismatch")
    if rp["offline_authorization_id"] != gp["authorization_id"]:
        raise ProtocolError("Authorization identity mismatch")
    for field in ("wallet_id", "wallet_key_id", "wallet_key_fingerprint", "currency"):
        if rp[field] != gp[field]:
            raise ProtocolError(f"Authorization scope mismatch: {field}")
    if rp["amount_cents"] > gp["max_payment_cents"] or rp["amount_cents"] > gp["authorized_total_cents"]:
        raise ProtocolError("Payment exceeds authorization")
    if rp["issuance_index"] > gp["max_payments"]:
        raise ProtocolError("Issuance index exceeds authorization")
    start = parse_timestamp(gp["issued_at"])
    end = parse_timestamp(gp["spend_expires_at"])
    issued = parse_timestamp(rp["issued_at"])
    expires = parse_timestamp(rp["expires_at"])
    confirmed = parse_timestamp(rp["confirmed_at"])
    if not start <= issued <= confirmed <= expires <= end:
        raise ProtocolError("Payment outside authorization issuance window")
    if (expires - issued).total_seconds() > gp["max_request_lifetime_seconds"]:
        raise ProtocolError("Request exceeds signed lifetime")
    if not receipt.verify(gp["wallet_public_key_b64"]):
        raise ProtocolError("Receipt signature does not match authorization key")


def validate_ack_binding(request: SignedEnvelope, receipt: SignedEnvelope, ack: SignedEnvelope) -> None:
    _require_kind(request, MessageType.PAYMENT_REQUEST)
    _require_kind(receipt, MessageType.PAYMENT_RECEIPT)
    _require_kind(ack, MessageType.PAYMENT_ACK)
    for field in COMMON_FIELDS - {"type"}:
        if request.payload[field] != receipt.payload[field] or receipt.payload[field] != ack.payload[field]:
            raise ProtocolError(f"Acknowledgement mismatch: {field}")
    for field in ("wallet_id", "offline_authorization_id"):
        if receipt.payload[field] != ack.payload[field]:
            raise ProtocolError(f"Acknowledgement scope mismatch: {field}")
    for field in ("pos_key_id", "pos_key_fingerprint"):
        if request.payload[field] != ack.payload[field]:
            raise ProtocolError("Acknowledgement must use request POS identity")
    if receipt.payload["request_digest"] != payload_digest(request) or ack.payload["receipt_digest"] != payload_digest(receipt):
        raise ProtocolError("Acknowledgement digest mismatch")
    if parse_timestamp(ack.payload["accepted_at"]) < parse_timestamp(receipt.payload["confirmed_at"]):
        raise ProtocolError("Acknowledgement precedes confirmation")


def parse_close_manifest(data: bytes) -> list[dict[str, Any]]:
    manifest = _parse_json(data)
    if not isinstance(manifest, list):
        raise ProtocolError("Manifest must be an array")
    operation_ids: set[str] = set()
    for index, entry in enumerate(manifest, start=1):
        if not isinstance(entry, dict) or set(entry) != MANIFEST_FIELDS:
            raise ProtocolError("Invalid manifest fields")
        _integer(entry["issuance_index"], "issuance_index")
        if entry["issuance_index"] != index:
            raise ProtocolError("Manifest indices must be consecutive")
        _uuid(entry["operation_id"], "operation_id")
        if entry["operation_id"] in operation_ids:
            raise ProtocolError("Duplicate manifest operation")
        operation_ids.add(entry["operation_id"])
        _integer(entry["amount_cents"], "amount_cents")
        _digest(entry["receipt_digest"], "receipt_digest")
    return manifest


def validate_close_manifest(close: SignedEnvelope, grant: SignedEnvelope, manifest_bytes: bytes) -> list[dict[str, Any]]:
    """Pure closure consistency; does not prove completeness of a mutable wallet."""
    _require_kind(close, MessageType.OFFLINE_AUTHORIZATION_CLOSE)
    _require_kind(grant, MessageType.OFFLINE_AUTHORIZATION)
    cp, gp = close.payload, grant.payload
    for field in ("authorization_id", "wallet_id", "wallet_key_id", "wallet_key_fingerprint"):
        if cp[field] != gp[field]:
            raise ProtocolError(f"Closure scope mismatch: {field}")
    if cp["authorization_digest"] != payload_digest(grant) or cp["manifest_digest"] != payload_digest(manifest_bytes):
        raise ProtocolError("Closure digest mismatch")
    manifest = parse_close_manifest(manifest_bytes)
    total = sum(entry["amount_cents"] for entry in manifest)
    if (len(manifest) != cp["final_issuance_index"] or len(manifest) > gp["max_payments"]
            or total != cp["emitted_total_cents"] or total > gp["authorized_total_cents"]
            or any(entry["amount_cents"] > gp["max_payment_cents"] for entry in manifest)):
        raise ProtocolError("Closure totals or limits mismatch")
    if parse_timestamp(cp["issued_at"]) < parse_timestamp(gp["issued_at"]):
        raise ProtocolError("Closure precedes authorization")
    if not close.verify(gp["wallet_public_key_b64"]):
        raise ProtocolError("Closure signature does not match wallet")
    return manifest
