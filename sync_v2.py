from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

import models
import schemas
from clock import utc_now
from auth import get_current_user
from database import get_db
from protocol_v2 import (
    MessageType,
    ProtocolError,
    parse_signed_envelope,
    payload_digest,
)


router = APIRouter(prefix="/api/offline-payments")
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[models.User, Depends(get_current_user)]


@router.post("/sync", response_model=schemas.OfflinePaymentSyncV2Response)
def sync_offline_payments_v2(
    request: schemas.OfflinePaymentSyncV2Request,
    db: DbSession,
    user: CurrentUser,
) -> schemas.OfflinePaymentSyncV2Response:
    results = [process_evidence(db, user, evidence) for evidence in request.operations]
    return schemas.OfflinePaymentSyncV2Response(results=results)


@router.get("/{operation_id}", response_model=schemas.OfflinePaymentStatusResponse)
def get_offline_payment_v2(
    operation_id: str,
    db: DbSession,
    user: CurrentUser,
) -> schemas.OfflinePaymentStatusResponse:
    payment = db.get(models.OfflinePaymentV2, operation_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Operacion no encontrada")
    _authorize_participant(db, user, payment.wallet_id, payment.terminal_id)
    return schemas.OfflinePaymentStatusResponse(
        operation_id=payment.operation_id,
        status=payment.state,
        code=payment.rejection_code,
    )


def process_evidence_core(
    db: Session,
    user: models.User,
    evidence: schemas.OfflinePaymentEvidence,
) -> schemas.OfflinePaymentResultV2:
    operation_id = evidence.operation_id
    try:
        request_wire = _decode_wire(evidence.request_envelope_b64)
        receipt_wire = _decode_wire(evidence.receipt_envelope_b64)
        ack_wire = _decode_wire(evidence.ack_envelope_b64) if evidence.ack_envelope_b64 else None
        request = parse_signed_envelope(request_wire)
        receipt = parse_signed_envelope(receipt_wire)
        if request.payload.get("operation_id") != operation_id or receipt.payload.get("operation_id") != operation_id:
            return _result(operation_id, "REJECTED", "OPERATION_ID_MISMATCH")

        existing = db.get(models.OfflinePaymentV2, operation_id)
        if existing is not None and (
            existing.request_envelope != request_wire or existing.receipt_envelope != receipt_wire
        ):
            db.rollback()
            return _result(operation_id, "CONFLICT", "CONTENT_MISMATCH")
        if existing is not None and existing.ack_envelope is not None and ack_wire is not None:
            if existing.ack_envelope != ack_wire:
                db.rollback()
                return _result(operation_id, "CONFLICT", "ACK_MISMATCH")

        if existing is not None and existing.state in {"ACCEPTED", "REJECTED"}:
            _authorize_participant(db, user, existing.wallet_id, existing.terminal_id)
            return _result(operation_id, existing.state, existing.rejection_code)

        context = _validate_evidence(db, request, receipt, ack_wire)
        _authorize_participant(db, user, context.wallet.id, context.terminal.id)

        payment = existing
        if payment is None:
            payment = models.OfflinePaymentV2(
                operation_id=operation_id,
                wallet_id=context.wallet.id,
                merchant_id=request.payload["merchant_id"],
                terminal_id=context.terminal.id,
                authorization_id=context.authorization.id,
                amount_cents=request.payload["amount_cents"],
                currency=request.payload["currency"],
                nonce=request.payload["nonce"],
                request_envelope=request_wire,
                receipt_envelope=receipt_wire,
                ack_envelope=ack_wire,
                state="PENDING_EVIDENCE" if ack_wire is None else "VALIDATED",
            )
            db.add(payment)
            db.flush()
        elif ack_wire is not None and payment.ack_envelope is None:
            payment.ack_envelope = ack_wire
            payment.state = "VALIDATED"

        if payment.state == "ACCEPTED":
            db.commit()
            return _result(operation_id, "ACCEPTED")
        if payment.state == "REJECTED":
            db.commit()
            return _result(operation_id, "REJECTED", payment.rejection_code)
        if ack_wire is None:
            db.commit()
            return _result(operation_id, "PENDING_EVIDENCE", "ACK_REQUIRED")

        return _apply_payment(db, payment, context)
    except HTTPException:
        db.rollback()
        raise
    except (ProtocolError, ValueError, TypeError, KeyError, binascii.Error):
        db.rollback()
        return _result(operation_id, "REJECTED", "INVALID_EVIDENCE")
    except IntegrityError:
        db.rollback()
        concurrent = db.get(models.OfflinePaymentV2, operation_id)
        if concurrent is not None:
            if concurrent.request_envelope == _safe_decode(evidence.request_envelope_b64) and concurrent.receipt_envelope == _safe_decode(evidence.receipt_envelope_b64):
                return _result(operation_id, concurrent.state if concurrent.state in {"ACCEPTED", "REJECTED"} else "PENDING_EVIDENCE", concurrent.rejection_code)
            return _result(operation_id, "CONFLICT", "CONTENT_MISMATCH")
        nonce = request.payload.get("nonce") if "request" in locals() else None
        reused_nonce = nonce is not None and db.query(models.OfflinePaymentV2).filter(
            models.OfflinePaymentV2.nonce == nonce
        ).first() is not None
        if reused_nonce:
            return _result(operation_id, "CONFLICT", "NONCE_REUSED")
        return _result(operation_id, "RETRYABLE_ERROR", "DATABASE_CONSTRAINT_OR_FAILURE")
    except OperationalError:
        db.rollback()
        return _result(operation_id, "RETRYABLE_ERROR", "DATABASE_BUSY")
    except Exception:
        db.rollback()
        return _result(operation_id, "RETRYABLE_ERROR", "INTERNAL_ERROR")


class EvidenceContext:
    def __init__(self, wallet, merchant_wallet, terminal, authorization):
        self.wallet = wallet
        self.merchant_wallet = merchant_wallet
        self.terminal = terminal
        self.authorization = authorization


def _validate_evidence(db: Session, request, receipt, ack_wire: bytes | None) -> EvidenceContext:
    if request.payload["type"] != MessageType.PAYMENT_REQUEST.value:
        raise ValueError("request type")
    if receipt.payload["type"] != MessageType.PAYMENT_RECEIPT.value:
        raise ValueError("receipt type")
    _same_fields(request.payload, receipt.payload)
    if receipt.payload["request_digest"] != payload_digest(request.payload):
        raise ValueError("request digest")

    pos_key = db.get(models.RegisteredKey, request.payload["pos_key_id"])
    if pos_key is None or pos_key.revoked or pos_key.purpose != "pos" or pos_key.fingerprint != request.payload["pos_key_fingerprint"]:
        raise ValueError("pos key")
    terminal = db.get(models.Terminal, request.payload["terminal_id"])
    if terminal is None or not terminal.active or pos_key.terminal_id != terminal.id or terminal.merchant_id != request.payload["merchant_id"]:
        raise ValueError("terminal")
    if not request.verify(pos_key.public_key_b64):
        raise ValueError("request signature")

    wallet = db.get(models.Wallet, receipt.payload["wallet_id"])
    wallet_key = db.get(models.RegisteredKey, receipt.payload["wallet_key_id"])
    if wallet is None or wallet_key is None or wallet_key.revoked or wallet_key.purpose != "wallet":
        raise ValueError("wallet key")
    if wallet_key.wallet_id != wallet.id or wallet_key.fingerprint != receipt.payload["wallet_key_fingerprint"]:
        raise ValueError("wallet key scope")
    if not receipt.verify(wallet_key.public_key_b64):
        raise ValueError("receipt signature")

    authorization = db.get(models.OfflineAuthorization, receipt.payload["offline_authorization_id"])
    if authorization is None or authorization.wallet_id != wallet.id or authorization.wallet_key_id != wallet_key.key_id:
        raise ValueError("authorization")
    issued_at = _parse_timestamp(request.payload["issued_at"])
    expires_at = _parse_timestamp(request.payload["expires_at"])
    auth_issued = _as_utc(authorization.issued_at)
    auth_expires = _as_utc(authorization.expires_at)
    if issued_at < auth_issued or expires_at > auth_expires:
        raise ValueError("authorization window")
    if request.payload["amount_cents"] > authorization.max_payment_cents:
        raise ValueError("authorization amount")

    if ack_wire is not None:
        ack = parse_signed_envelope(ack_wire)
        if ack.payload["type"] != MessageType.PAYMENT_ACK.value:
            raise ValueError("ack type")
        _same_fields(receipt.payload, ack.payload)
        for field in ("wallet_id", "offline_authorization_id"):
            if receipt.payload[field] != ack.payload[field]:
                raise ValueError(field)
        if ack.payload["receipt_digest"] != payload_digest(receipt.payload):
            raise ValueError("receipt digest")
        ack_key = db.get(models.RegisteredKey, ack.payload["pos_key_id"])
        if ack_key is None or ack_key.revoked or ack_key.key_id != pos_key.key_id:
            raise ValueError("ack key")
        if ack_key.fingerprint != ack.payload["pos_key_fingerprint"] or not ack.verify(ack_key.public_key_b64):
            raise ValueError("ack signature")

    merchant_wallet = db.query(models.Wallet).filter(models.Wallet.user_id == terminal.merchant_user_id).one_or_none()
    if merchant_wallet is None:
        raise ValueError("merchant wallet")
    return EvidenceContext(wallet, merchant_wallet, terminal, authorization)


def _apply_payment(
    db: Session,
    payment: models.OfflinePaymentV2,
    context: EvidenceContext,
) -> schemas.OfflinePaymentResultV2:
    amount = payment.amount_cents
    now = utc_now()
    authorization_update = db.execute(
        update(models.OfflineAuthorization)
        .where(
            models.OfflineAuthorization.id == context.authorization.id,
            models.OfflineAuthorization.active.is_(True),
            models.OfflineAuthorization.remaining_amount_cents >= amount,
            models.OfflineAuthorization.remaining_payments > 0,
        )
        .values(
            remaining_amount_cents=models.OfflineAuthorization.remaining_amount_cents - amount,
            remaining_payments=models.OfflineAuthorization.remaining_payments - 1,
        )
        .execution_options(synchronize_session=False)
    )
    debit = db.execute(
        update(models.Wallet)
        .where(models.Wallet.id == context.wallet.id, models.Wallet.confirmed_balance_cents >= amount)
        .values(confirmed_balance_cents=models.Wallet.confirmed_balance_cents - amount)
        .execution_options(synchronize_session=False)
    )
    if authorization_update.rowcount != 1 or debit.rowcount != 1:
        ack_envelope = payment.ack_envelope
        db.rollback()
        persisted = db.get(models.OfflinePaymentV2, payment.operation_id)
        if persisted is None:
            persisted = payment
            db.add(persisted)
        persisted.state = "REJECTED"
        persisted.rejection_code = "INSUFFICIENT_AUTHORIZATION_OR_BALANCE"
        persisted.ack_envelope = ack_envelope
        db.commit()
        return _result(payment.operation_id, "REJECTED", persisted.rejection_code)

    amount_decimal = Decimal(amount) / Decimal("100")
    db.execute(
        update(models.User)
        .where(models.User.id == context.wallet.user_id)
        .values(saldo_real=models.User.saldo_real - amount_decimal)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        update(models.Wallet)
        .where(models.Wallet.id == context.merchant_wallet.id)
        .values(confirmed_balance_cents=models.Wallet.confirmed_balance_cents + amount)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        update(models.User)
        .where(models.User.id == context.merchant_wallet.user_id)
        .values(saldo_real=models.User.saldo_real + amount_decimal)
        .execution_options(synchronize_session=False)
    )
    db.add_all(
        [
            models.LedgerEntry(
                operation_id=payment.operation_id,
                wallet_id=context.wallet.id,
                entry_type="DEBIT",
                delta_cents=-amount,
            ),
            models.LedgerEntry(
                operation_id=payment.operation_id,
                wallet_id=context.merchant_wallet.id,
                entry_type="CREDIT",
                delta_cents=amount,
            ),
        ]
    )
    payment.state = "ACCEPTED"
    payment.applied_at = now
    db.commit()
    return _result(payment.operation_id, "ACCEPTED")


def _authorize_participant(db: Session, user: models.User, wallet_id: str, terminal_id: str) -> None:
    wallet = db.get(models.Wallet, wallet_id)
    terminal = db.get(models.Terminal, terminal_id)
    is_wallet_owner = wallet is not None and wallet.user_id == user.id
    is_terminal_owner = terminal is not None and terminal.merchant_user_id == user.id
    if not (is_wallet_owner or is_terminal_owner):
        raise HTTPException(status_code=403, detail="Operacion no autorizada")


def _same_fields(left: dict, right: dict) -> None:
    for field in (
        "operation_id", "merchant_id", "terminal_id", "amount_cents", "currency", "nonce",
        "issued_at", "expires_at",
    ):
        if left[field] != right[field]:
            raise ValueError(field)


def _decode_wire(value: str | None) -> bytes:
    if value is None or "\n" in value or "\r" in value:
        raise ValueError("base64")
    data = base64.b64decode(value, validate=True)
    if not data or len(data) > 4096:
        raise ValueError("wire length")
    return data


def _safe_decode(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return b""


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _result(operation_id: str, status: str, code: str | None = None) -> schemas.OfflinePaymentResultV2:
    return schemas.OfflinePaymentResultV2(operation_id=operation_id, status=status, code=code)


def process_evidence(db: Session, user: models.User, evidence: schemas.OfflinePaymentEvidence) -> schemas.OfflinePaymentResultV2:
    """Adaptador de compatibilidad para el endpoint v2."""
    return process_evidence_core(db, user, evidence)
