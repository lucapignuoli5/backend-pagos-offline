from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric import ec

from protocol_v2 import (
    DEFAULT_CHUNK_BYTES, INS_GET_RECEIPT, INS_GET_STATUS, INS_PUT_ACK, INS_PUT_REQUEST,
    SELECT_APDU, SW_BAD_DATA, SW_CONDITIONS_NOT_SATISFIED, SW_NOT_FOUND, SW_OK,
    build_apdu, chunk_message, parse_apdu,
)
from protocol_v3 import (
    INS_GET_AUTHORIZATION, encode_public_key, encode_select_capabilities,
    encode_signed_envelope, parse_signed_envelope, payload_digest,
    public_key_fingerprint, sign_payload, timestamp, validate_ack_binding,
    validate_receipt_binding,
)


class AndroidHceSimulator:
    """Doble de Android para pruebas; no acredita compatibilidad ISO-DEP fisica."""

    def __init__(
        self, wallet_id: str = "wallet-simulator",
        authorization_id: str = "authorization-simulator",
        wallet_key_id: str = "wallet-key-simulator",
    ):
        self.wallet_id = wallet_id
        self.authorization_id = authorization_id
        self.wallet_key_id = wallet_key_id
        self.wallet_private_key = ec.generate_private_key(ec.SECP256R1())
        self.wallet_public_key_b64 = encode_public_key(self.wallet_private_key.public_key())
        self.wallet_fingerprint = public_key_fingerprint(base64.b64decode(self.wallet_public_key_b64))
        self.issuer_key_id = "issuer-simulator"
        self.issuer_private_key = ec.generate_private_key(ec.SECP256R1())
        self.issuer_public_key_b64 = encode_public_key(self.issuer_private_key.public_key())
        issued = datetime.now(timezone.utc).replace(microsecond=0)
        grant = {
            "version": 3, "type": "offline_authorization", "authorization_id": authorization_id,
            "wallet_id": wallet_id, "wallet_key_id": wallet_key_id,
            "wallet_key_fingerprint": self.wallet_fingerprint,
            "wallet_public_key_b64": self.wallet_public_key_b64, "currency": "ARS",
            "max_payment_cents": 100000, "max_payments": 10,
            "authorized_total_cents": 1000000, "max_request_lifetime_seconds": 120,
            "issued_at": timestamp(issued), "spend_expires_at": timestamp(issued + timedelta(hours=24)),
            "issuer_key_id": self.issuer_key_id,
            "issuer_key_fingerprint": public_key_fingerprint(base64.b64decode(self.issuer_public_key_b64)),
        }
        self.authorization_envelope = encode_signed_envelope(grant, sign_payload(grant, self.issuer_private_key))
        self.trusted_pos_keys: dict[tuple[str, str], str] = {}
        self.requests: dict[str, bytes] = {}
        self.receipts: dict[str, bytes] = {}
        self.acks: dict[str, bytes] = {}
        self._fragments: dict[int, list[bytes]] = {}
        self._response_cache: dict[bytes, bytes] = {}

    def trust_pos_key(self, key_id: str, fingerprint: str, public_key_b64: str) -> None:
        self.trusted_pos_keys[(key_id, fingerprint)] = public_key_b64

    def connect(self) -> None:
        return None

    def close(self) -> None:
        self._fragments.clear()
        self._response_cache.clear()

    def transceive(self, apdu: bytes) -> bytes:
        if apdu in {SELECT_APDU, SELECT_APDU + b"\x00"}:
            return encode_select_capabilities() + SW_OK
        cached = self._response_cache.get(apdu)
        if cached is not None:
            return cached
        response = self._process(apdu)
        self._response_cache[bytes(apdu)] = response
        return response

    def _process(self, apdu: bytes) -> bytes:
        try:
            command = parse_apdu(apdu)
            if command.instruction in {INS_PUT_REQUEST, INS_PUT_ACK}:
                return self._accept_fragment(command.instruction, command.sequence, command.is_last, command.data)
            operation_id = command.data.decode("ascii")
            if command.instruction == INS_GET_STATUS:
                if command.sequence != 0 or not command.is_last:
                    return SW_BAD_DATA
                return self._status(operation_id)
            if command.instruction == INS_GET_RECEIPT:
                receipt = self.receipts.get(operation_id)
                if receipt is None:
                    return SW_CONDITIONS_NOT_SATISFIED
                chunks = chunk_message(receipt)
                if command.sequence >= len(chunks):
                    return SW_NOT_FOUND
                return bytes((1 if command.sequence == len(chunks) - 1 else 0,)) + chunks[command.sequence] + SW_OK
            if command.instruction == INS_GET_AUTHORIZATION:
                if operation_id not in self.receipts:
                    return SW_CONDITIONS_NOT_SATISFIED
                chunks = chunk_message(self.authorization_envelope)
                if command.sequence >= len(chunks):
                    return SW_NOT_FOUND
                return bytes((1 if command.sequence == len(chunks) - 1 else 0,)) + chunks[command.sequence] + SW_OK
            return SW_BAD_DATA
        except (UnicodeDecodeError, ValueError):
            return SW_BAD_DATA

    def confirm(self, operation_id: str) -> bytes:
        request_envelope = self.requests[operation_id]
        request_signed = parse_signed_envelope(request_envelope)
        request = request_signed.payload
        grant = parse_signed_envelope(self.authorization_envelope)
        confirmed = min(datetime.now(timezone.utc).replace(microsecond=0),
                        datetime.fromisoformat(request["expires_at"].replace("Z", "+00:00")))
        receipt = {
            key: request[key] for key in (
                "version", "operation_id", "merchant_id", "terminal_id", "amount_cents",
                "currency", "nonce", "issued_at", "expires_at",
            )
        }
        receipt.update(
            type="payment_receipt",
            wallet_id=self.wallet_id,
            offline_authorization_id=self.authorization_id,
            wallet_key_id=self.wallet_key_id,
            wallet_key_fingerprint=self.wallet_fingerprint,
            request_digest=payload_digest(request_signed),
            authorization_digest=payload_digest(grant),
            issuance_index=1,
            confirmed_at=timestamp(confirmed),
        )
        envelope = encode_signed_envelope(receipt, sign_payload(receipt, self.wallet_private_key))
        validate_receipt_binding(request_signed, parse_signed_envelope(envelope), grant)
        self.receipts[operation_id] = envelope
        return envelope

    def _accept_fragment(self, instruction: int, sequence: int, is_last: bool, data: bytes) -> bytes:
        chunks = self._fragments.setdefault(instruction, [])
        if sequence != len(chunks):
            return SW_BAD_DATA
        chunks.append(bytes(data))
        if sum(map(len, chunks)) > 4096:
            self._fragments.pop(instruction, None)
            return SW_BAD_DATA
        if not is_last:
            return SW_OK
        envelope_bytes = b"".join(chunks)
        self._fragments.pop(instruction, None)
        envelope = parse_signed_envelope(envelope_bytes)
        payload = envelope.payload
        if instruction == INS_PUT_REQUEST:
            public_key = self.trusted_pos_keys.get(
                (payload["pos_key_id"], payload["pos_key_fingerprint"])
            )
            if public_key is None:
                return SW_CONDITIONS_NOT_SATISFIED
            if not envelope.verify(public_key):
                return SW_BAD_DATA
            operation_id = payload["operation_id"]
            existing = self.requests.get(operation_id)
            if existing is not None and existing != envelope_bytes:
                return SW_BAD_DATA
            self.requests[operation_id] = envelope_bytes
            return f"{operation_id}|REQUEST_RECEIVED".encode("ascii") + SW_OK

        public_key = self.trusted_pos_keys.get(
            (payload["pos_key_id"], payload["pos_key_fingerprint"])
        )
        if public_key is None or not envelope.verify(public_key):
            return SW_BAD_DATA
        operation_id = payload["operation_id"]
        receipt = parse_signed_envelope(self.receipts[operation_id])
        validate_ack_binding(parse_signed_envelope(self.requests[operation_id]), receipt, envelope)
        existing = self.acks.get(operation_id)
        if existing is not None and existing != envelope_bytes:
            return SW_BAD_DATA
        self.acks[operation_id] = envelope_bytes
        return f"{operation_id}|LOCALLY_ACCEPTED".encode("ascii") + SW_OK

    def _status(self, operation_id: str) -> bytes:
        if operation_id in self.acks:
            state = "LOCALLY_ACCEPTED"
        elif operation_id in self.receipts:
            state = "RESERVED"
        elif operation_id in self.requests:
            state = "REQUEST_RECEIVED"
        else:
            return SW_NOT_FOUND
        return f"{operation_id}|{state}".encode("ascii") + SW_OK


class SimulatorTransport:
    def __init__(self, simulator: AndroidHceSimulator):
        self.simulator = simulator

    def connect(self) -> None:
        self.simulator.connect()

    def transceive(self, apdu: bytes) -> bytes:
        return self.simulator.transceive(apdu)

    def close(self) -> None:
        self.simulator.close()

