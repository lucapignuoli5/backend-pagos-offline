from __future__ import annotations

import base64
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import ec

from protocol_v2 import (
    CURRENCY, DEFAULT_CHUNK_BYTES, INS_GET_RECEIPT, INS_GET_STATUS, INS_PUT_ACK,
    INS_PUT_REQUEST, MAX_AMOUNT_CENTS, build_apdu, chunk_message, encode_signed_envelope,
    parse_signed_envelope, payload_digest, sign_payload,
)
from protocol_v3 import (
    INS_GET_AUTHORIZATION, PROTOCOL_VERSION, canonical_bytes as canonical_bytes_v3,
    encode_signed_envelope as encode_signed_envelope_v3,
    parse_select_capabilities, parse_signed_envelope as parse_signed_envelope_v3,
    payload_digest as payload_digest_v3, sign_payload as sign_payload_v3,
    validate_ack_binding, validate_receipt_binding, verify_authorization,
)
from pos_desktop.config import PosConfig
from pos_desktop.database import PosDatabase, PosOperation
from pos_desktop.key_store import PosKeyStore
from pos_desktop.nfc import ApduTransport, require_ok, select_hce
from pos_desktop.issuer_trust import public_key as issuer_public_key


class PosService:
    def __init__(
        self,
        config: PosConfig,
        database: PosDatabase,
        key_store: PosKeyStore,
        transport_factory: Callable[[], ApduTransport],
        now: Callable[[], datetime] | None = None,
    ):
        self.config = config
        self.database = database
        self.key_store = key_store
        self.transport_factory = transport_factory
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.database.migrate()

    def create_payment(self, amount_cents: int) -> PosOperation:
        if isinstance(amount_cents, bool) or not 1 <= amount_cents <= MAX_AMOUNT_CENTS:
            raise ValueError("El importe debe estar entre 1 y 100000 centavos")
        private_key, _, fingerprint = self.key_store.get_or_create(self.config.pos_key_id)
        issued = self.now().astimezone(timezone.utc).replace(microsecond=0)
        expires = issued + timedelta(seconds=120)
        payload = {
            "version": PROTOCOL_VERSION,
            "type": "payment_request",
            "operation_id": str(uuid4()),
            "merchant_id": self.config.merchant_id,
            "terminal_id": self.config.terminal_id,
            "amount_cents": amount_cents,
            "currency": CURRENCY,
            "nonce": base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("="),
            "issued_at": self._timestamp(issued),
            "expires_at": self._timestamp(expires),
            "pos_key_id": self.config.pos_key_id,
            "pos_key_fingerprint": fingerprint,
        }
        envelope = encode_signed_envelope_v3(payload, sign_payload_v3(payload, private_key))
        timestamp = self._timestamp(issued)
        self.database.insert_request(payload, envelope, timestamp)
        return self._required_operation(payload["operation_id"])

    def deliver_request(self, operation_id: str) -> str:
        operation = self._required_operation(operation_id)
        transport = self.transport_factory()
        try:
            transport.connect()
            parse_select_capabilities(select_hce(transport))
            response_body = b""
            chunks = chunk_message(operation.request_envelope, DEFAULT_CHUNK_BYTES)
            for sequence, chunk in enumerate(chunks):
                response_body = require_ok(
                    transport.transceive(
                        build_apdu(INS_PUT_REQUEST, sequence, sequence == len(chunks) - 1, chunk)
                    ),
                    "Entrega de solicitud",
                )
            status = self._parse_status(response_body, operation_id)
            if status != "REQUEST_RECEIVED":
                raise RuntimeError(f"Estado Android inesperado: {status}")
            self.database.mark_request_delivered(operation_id, self._now_text())
            return status
        finally:
            transport.close()

    def collect_receipt(self, operation_id: str) -> str:
        operation = self._required_operation(operation_id)
        transport = self.transport_factory()
        try:
            transport.connect()
            parse_select_capabilities(select_hce(transport))
            if operation.ack_envelope is not None:
                self._send_ack(transport, operation.ack_envelope, operation_id)
                return "LOCALLY_ACCEPTED"

            state = self._get_status(transport, operation_id)
            if state not in {"RESERVED", "DELIVERY_UNCERTAIN", "LOCALLY_ACCEPTED"}:
                self.database.mark_waiting(operation_id, self._now_text())
                return state

            authorization_bytes = self._read_fragmented(
                transport, INS_GET_AUTHORIZATION, operation_id, "Lectura de autorizacion"
            )
            self.database.set_authorization(operation_id, authorization_bytes, self._now_text())
            receipt_bytes = self._read_receipt(transport, operation_id)
            receipt, request, grant = self._verify_receipt(operation, receipt_bytes, authorization_bytes)
            private_key, _, fingerprint = self.key_store.get_or_create(self.config.pos_key_id)
            accepted = self.now().astimezone(timezone.utc).replace(microsecond=0)
            expires = self._parse_timestamp(receipt["expires_at"])
            if accepted > expires:
                raise ValueError("La solicitud vencio antes de aceptar el comprobante")
            ack = {
                key: receipt[key] for key in (
                    "version", "operation_id", "merchant_id", "terminal_id", "amount_cents",
                    "currency", "nonce", "issued_at", "expires_at", "wallet_id",
                    "offline_authorization_id",
                )
            }
            ack.update(
                type="payment_ack",
                pos_key_id=self.config.pos_key_id,
                pos_key_fingerprint=fingerprint,
                receipt_digest=payload_digest_v3(parse_signed_envelope_v3(receipt_bytes)),
                accepted_at=self._timestamp(accepted),
                status="LOCALLY_ACCEPTED",
            )
            ack_bytes = encode_signed_envelope_v3(ack, sign_payload_v3(ack, private_key))
            validate_ack_binding(request, parse_signed_envelope_v3(receipt_bytes), parse_signed_envelope_v3(ack_bytes))
            self.database.accept_receipt_and_ack(
                operation_id, receipt_bytes, ack_bytes, self._timestamp(accepted)
            )
            self._send_ack(transport, ack_bytes, operation_id)
            return "LOCALLY_ACCEPTED"
        finally:
            transport.close()

    def _get_status(self, transport: ApduTransport, operation_id: str) -> str:
        body = require_ok(
            transport.transceive(build_apdu(INS_GET_STATUS, 0, True, operation_id.encode("ascii"))),
            "Consulta de estado",
        )
        return self._parse_status(body, operation_id)

    def _read_receipt(self, transport: ApduTransport, operation_id: str) -> bytes:
        return self._read_fragmented(transport, INS_GET_RECEIPT, operation_id, "Lectura de comprobante")

    def _read_fragmented(self, transport: ApduTransport, instruction: int,
                         operation_id: str, action: str) -> bytes:
        chunks: list[bytes] = []
        for sequence in range(26):
            body = require_ok(
                transport.transceive(
                    build_apdu(instruction, sequence, True, operation_id.encode("ascii"))
                ),
                action,
            )
            if not body:
                raise ValueError("Fragmento de comprobante vacio")
            is_last, chunk = body[0], body[1:]
            if is_last not in {0, 1}:
                raise ValueError("Indicador de fragmento invalido")
            chunks.append(chunk)
            if sum(map(len, chunks)) > 4096:
                raise ValueError("Comprobante demasiado grande")
            if is_last == 1:
                return b"".join(chunks)
        raise ValueError("El comprobante excede la cantidad maxima de fragmentos")

    def _verify_receipt(self, operation: PosOperation, receipt_bytes: bytes,
                        authorization_bytes: bytes) -> tuple[dict, object, object]:
        request = parse_signed_envelope_v3(operation.request_envelope)
        envelope = parse_signed_envelope_v3(receipt_bytes)
        grant = parse_signed_envelope_v3(authorization_bytes)
        receipt = envelope.payload
        public = issuer_public_key(self.database, self.config, grant.payload)
        if not verify_authorization(grant, public, grant.payload["issuer_key_id"]):
            raise ValueError("Autorizacion offline no confiable")
        validate_receipt_binding(request, envelope, grant)
        return receipt, request, grant

    def _send_ack(self, transport: ApduTransport, ack: bytes, operation_id: str) -> None:
        chunks = chunk_message(ack, DEFAULT_CHUNK_BYTES)
        response_body = b""
        for sequence, chunk in enumerate(chunks):
            response_body = require_ok(
                transport.transceive(
                    build_apdu(INS_PUT_ACK, sequence, sequence == len(chunks) - 1, chunk)
                ),
                "Entrega de acuse",
            )
        if self._parse_status(response_body, operation_id) not in {"LOCALLY_ACCEPTED", "SYNCED"}:
            raise RuntimeError("Android no confirmo el acuse")

    @staticmethod
    def _parse_status(body: bytes, operation_id: str) -> str:
        value = body.decode("ascii")
        prefix = f"{operation_id}|"
        if not value.startswith(prefix):
            raise ValueError("Respuesta de estado no corresponde a la operacion")
        return value[len(prefix):]

    def _required_operation(self, operation_id: str) -> PosOperation:
        operation = self.database.get_operation(operation_id)
        if operation is None:
            raise ValueError("Operacion POS no encontrada")
        return operation

    def _now_text(self) -> str:
        return self._timestamp(self.now().astimezone(timezone.utc).replace(microsecond=0))

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

