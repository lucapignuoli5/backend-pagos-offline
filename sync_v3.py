from __future__ import annotations

import base64
import binascii
import os
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

import models
import schemas
from clock import utc_now
from issuer_keys import IssuerIdentity
from protocol_v3 import (
    MessageType, ProtocolError, parse_signed_envelope, validate_ack_binding,
    validate_receipt_binding, verify_authorization, verify_pos_signer,
)


def process_evidence_v3(db: Session, user: models.User,
                        evidence: schemas.OfflinePaymentEvidenceV3) -> schemas.OfflinePaymentResultV3:
    operation_id = evidence.operation_id
    try:
        request_wire = _wire(evidence.request_envelope_b64)
        grant_wire = _wire(evidence.authorization_envelope_b64)
        receipt_wire = _wire(evidence.receipt_envelope_b64)
        ack_wire = _wire(evidence.ack_envelope_b64) if evidence.ack_envelope_b64 else None
        request = parse_signed_envelope(request_wire)
        grant = parse_signed_envelope(grant_wire)
        receipt = parse_signed_envelope(receipt_wire)
        if request.payload.get("operation_id") != operation_id or receipt.payload.get("operation_id") != operation_id:
            return _result(operation_id, "INVALID_EVIDENCE", "UNRESOLVED", False, "OPERATION_ID_MISMATCH")

        existing = db.get(models.OfflinePaymentV2, operation_id)
        if existing is not None:
            if existing.request_envelope != request_wire or existing.receipt_envelope != receipt_wire:
                return _result(operation_id, "CONFLICT", "PENDING_REVIEW", False, "CONTENT_MISMATCH")
            if existing.ack_envelope is not None and ack_wire is not None and existing.ack_envelope != ack_wire:
                return _result(operation_id, "CONFLICT", "PENDING_REVIEW", False, "ACK_MISMATCH")
            _authorize(db, user, existing.wallet_id, existing.terminal_id)
            if existing.state in {"ACCEPTED", "REJECTED"}:
                return _result(operation_id, "VALIDATED", existing.state, True, existing.rejection_code)

        wallet, merchant_wallet, terminal, authorization, commitment = _validate(
            db, request, grant, grant_wire, receipt, ack_wire
        )
        _authorize(db, user, wallet.id, terminal.id)
        payment = existing
        if payment is None:
            payment = models.OfflinePaymentV2(
                operation_id=operation_id, wallet_id=wallet.id,
                merchant_id=request.payload["merchant_id"], terminal_id=terminal.id,
                authorization_id=authorization.id, amount_cents=request.payload["amount_cents"],
                currency=request.payload["currency"], nonce=request.payload["nonce"],
                request_envelope=request_wire, receipt_envelope=receipt_wire,
                ack_envelope=ack_wire, state="PENDING_EVIDENCE" if ack_wire is None else "VALIDATED",
            )
            db.add(payment)
            db.flush()
        elif ack_wire is not None and payment.ack_envelope is None:
            payment.ack_envelope = ack_wire
            payment.state = "VALIDATED"
        if ack_wire is None:
            db.commit()
            return _result(operation_id, "VALIDATED", "PENDING_EVIDENCE", False, "ACK_REQUIRED")
        return _apply(db, payment, wallet, merchant_wallet, authorization, commitment,
                      receipt.payload["issuance_index"])
    except HTTPException:
        db.rollback()
        raise
    except (ProtocolError, ValueError, TypeError, KeyError, binascii.Error):
        db.rollback()
        return _result(operation_id, "INVALID_EVIDENCE", "UNRESOLVED", False, "INVALID_EVIDENCE")
    except IntegrityError:
        db.rollback()
        return _result(operation_id, "CONFLICT", "PENDING_REVIEW", False, "DATABASE_CONSTRAINT")
    except OperationalError:
        db.rollback()
        return _result(operation_id, "RETRYABLE_ERROR", "UNRESOLVED", False, "DATABASE_BUSY")
    except Exception:
        db.rollback()
        return _result(operation_id, "RETRYABLE_ERROR", "UNRESOLVED", False, "INTERNAL_ERROR")


def _validate(db, request, grant, grant_wire, receipt, ack_wire):
    if request.payload["type"] != MessageType.PAYMENT_REQUEST.value:
        raise ValueError("request")
    issuer = IssuerIdentity.load_external(os.environ["ISSUER_KEY_PATH"], os.environ["ISSUER_KEY_FINGERPRINT"])
    if not verify_authorization(grant, issuer.public_key_b64, issuer.key_id):
        raise ValueError("grant")
    validate_receipt_binding(request, receipt, grant)
    pos_key = db.get(models.RegisteredKey, request.payload["pos_key_id"])
    terminal = db.get(models.Terminal, request.payload["terminal_id"])
    if (pos_key is None or pos_key.revoked or pos_key.purpose != "pos" or terminal is None
            or not terminal.active or pos_key.terminal_id != terminal.id
            or not verify_pos_signer(request, pos_key.public_key_b64, pos_key.key_id,
                                     pos_key.fingerprint, terminal.merchant_id, terminal.id)):
        raise ValueError("pos")
    wallet = db.get(models.Wallet, grant.payload["wallet_id"])
    authorization = db.get(models.OfflineAuthorization, grant.payload["authorization_id"])
    commitment = db.get(models.OfflineCommitment, grant.payload["authorization_id"])
    if (wallet is None or authorization is None or commitment is None
            or authorization.wallet_id != wallet.id or commitment.wallet_id != wallet.id
            or commitment.authorization_envelope != grant_wire):
        raise ValueError("authorization")
    if ack_wire is not None:
        ack = parse_signed_envelope(ack_wire)
        validate_ack_binding(request, receipt, ack)
        if not verify_pos_signer(ack, pos_key.public_key_b64, pos_key.key_id,
                                 pos_key.fingerprint, terminal.merchant_id, terminal.id):
            raise ValueError("ack")
    merchant_wallet = db.query(models.Wallet).filter(models.Wallet.user_id == terminal.merchant_user_id).one_or_none()
    if merchant_wallet is None:
        raise ValueError("merchant wallet")
    return wallet, merchant_wallet, terminal, authorization, commitment


def _apply(db, payment, wallet, merchant_wallet, authorization, commitment, issuance_index):
    amount = payment.amount_cents
    duplicate = db.query(models.CommitmentEmission).filter_by(
        authorization_id=authorization.id, issuance_index=issuance_index,
    ).first()
    if duplicate is not None and duplicate.operation_id != payment.operation_id:
        db.rollback()
        return _result(payment.operation_id, "CONFLICT", "PENDING_REVIEW", False, "ISSUANCE_INDEX_REUSED")
    updates = (
        db.execute(update(models.OfflineAuthorization).where(
            models.OfflineAuthorization.id == authorization.id,
            models.OfflineAuthorization.remaining_amount_cents >= amount,
            models.OfflineAuthorization.remaining_payments > 0,
        ).values(
            remaining_amount_cents=models.OfflineAuthorization.remaining_amount_cents - amount,
            remaining_payments=models.OfflineAuthorization.remaining_payments - 1,
        )),
        db.execute(update(models.Wallet).where(
            models.Wallet.id == wallet.id,
            models.Wallet.confirmed_balance_cents >= amount,
        ).values(confirmed_balance_cents=models.Wallet.confirmed_balance_cents - amount)),
        db.execute(update(models.OfflineCommitment).where(
            models.OfflineCommitment.authorization_id == commitment.authorization_id,
            models.OfflineCommitment.emitted_cents + amount <= models.OfflineCommitment.reserved_cents,
        ).values(
            emitted_cents=models.OfflineCommitment.emitted_cents + amount,
            emitted_count=models.OfflineCommitment.emitted_count + 1,
        )),
    )
    if any(item.rowcount != 1 for item in updates):
        db.rollback()
        return _result(payment.operation_id, "VALIDATED", "PENDING_REVIEW", False,
                       "INSUFFICIENT_COMMITMENT_OR_BALANCE")
    db.add(models.CommitmentEmission(
        authorization_id=authorization.id, operation_id=payment.operation_id,
        issuance_index=issuance_index, amount_cents=amount,
    ))
    amount_decimal = Decimal(amount) / Decimal("100")
    db.execute(update(models.User).where(models.User.id == wallet.user_id).values(
        saldo_real=models.User.saldo_real - amount_decimal))
    db.execute(update(models.Wallet).where(models.Wallet.id == merchant_wallet.id).values(
        confirmed_balance_cents=models.Wallet.confirmed_balance_cents + amount))
    db.execute(update(models.User).where(models.User.id == merchant_wallet.user_id).values(
        saldo_real=models.User.saldo_real + amount_decimal))
    db.add_all([
        models.LedgerEntry(operation_id=payment.operation_id, wallet_id=wallet.id,
                           entry_type="DEBIT", delta_cents=-amount),
        models.LedgerEntry(operation_id=payment.operation_id, wallet_id=merchant_wallet.id,
                           entry_type="CREDIT", delta_cents=amount),
    ])
    payment.state = "ACCEPTED"
    payment.applied_at = utc_now()
    db.commit()
    return _result(payment.operation_id, "VALIDATED", "ACCEPTED", True)


def _authorize(db, user, wallet_id, terminal_id):
    wallet = db.get(models.Wallet, wallet_id)
    terminal = db.get(models.Terminal, terminal_id)
    if not ((wallet and wallet.user_id == user.id) or (terminal and terminal.merchant_user_id == user.id)):
        raise HTTPException(403, "Operacion no autorizada")


def _wire(value: str) -> bytes:
    data = base64.b64decode(value, validate=True)
    if not data or len(data) > 4096:
        raise ValueError("wire")
    return data


def _result(operation_id, submission, operation, final, code=None):
    return schemas.OfflinePaymentResultV3(
        operation_id=operation_id, submission_status=submission,
        operation_status=operation, final=final, code=code,
    )
