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
from demo_events import event
from issuer_keys import IssuerIdentity
from issuer_trust import verify_trusted_authorization
from revocation import requires_review
from protocol_v3 import parse_timestamp
from protocol_v3 import (
    MessageType, ProtocolError, parse_signed_envelope, validate_ack_binding,
    payload_digest, validate_receipt_binding, verify_authorization, verify_pos_signer,
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

        # Serialize with authorization issuance/closure before observing durable state.
        db.execute(update(models.Wallet).where(
            models.Wallet.id == grant.payload["wallet_id"]
        ).values(confirmed_balance_cents=models.Wallet.confirmed_balance_cents))
        db.expire_all()

        existing = db.get(models.OfflinePaymentV2, operation_id)
        if existing is not None:
            if existing.request_envelope != request_wire or existing.receipt_envelope != receipt_wire:
                db.rollback()
                return _result(operation_id, "CONFLICT", "PENDING_REVIEW", False, "CONTENT_MISMATCH")
            if existing.ack_envelope is not None and ack_wire is not None and existing.ack_envelope != ack_wire:
                db.rollback()
                return _result(operation_id, "CONFLICT", "PENDING_REVIEW", False, "ACK_MISMATCH")
            _authorize(db, user, existing.wallet_id, existing.terminal_id)
            if existing.state in {"ACCEPTED", "REJECTED"}:
                known_grant = db.get(models.OfflineCommitment, existing.authorization_id)
                if known_grant is None or known_grant.authorization_envelope != grant_wire:
                    db.rollback()
                    return _result(operation_id, "CONFLICT", "PENDING_REVIEW", False, "AUTHORIZATION_MISMATCH")
                resolution = db.get(models.PaymentResolution, operation_id)
                if resolution is None:
                    db.rollback()
                    return _result(operation_id, "VALIDATED", "PENDING_REVIEW", False,
                                   "SIGNED_RESOLUTION_MISSING")
                if existing.ack_envelope is None and ack_wire is not None:
                    ack = parse_signed_envelope(ack_wire)
                    validate_ack_binding(request, receipt, ack)
                    key = db.get(models.RegisteredKey, request.payload["pos_key_id"])
                    if key is None or not ack.verify(key.public_key_b64):
                        raise ValueError("late ack signature")
                    existing.ack_envelope = ack_wire
                    db.flush()
                result = _result(operation_id, "VALIDATED", existing.state, True,
                               existing.rejection_code, resolution.resolution_envelope)
                db.commit()
                return result

        wallet, merchant_wallet, terminal, authorization, commitment, review = _validate(
            db, request, grant, grant_wire, receipt, ack_wire
        )
        _authorize(db, user, wallet.id, terminal.id)
        if review or (existing is not None and existing.state == "PENDING_REVIEW"):
            if existing is None:
                db.add(models.OfflinePaymentV2(
                    operation_id=operation_id, wallet_id=wallet.id,
                    merchant_id=request.payload["merchant_id"], terminal_id=terminal.id,
                    authorization_id=authorization.id, amount_cents=request.payload["amount_cents"],
                    currency=request.payload["currency"], nonce=request.payload["nonce"],
                    request_envelope=request_wire, receipt_envelope=receipt_wire,
                    ack_envelope=ack_wire, state="PENDING_REVIEW",
                    rejection_code="REVOCATION_REVIEW",
                ))
            else:
                existing.state = "PENDING_REVIEW"
            db.commit()
            return _result(operation_id, "VALIDATED", "PENDING_REVIEW", False, "REVOCATION_REVIEW")
        if commitment.closed and existing is None:
            wallet.offline_review_required = True
            db.add(models.OfflinePaymentV2(
                operation_id=operation_id, wallet_id=wallet.id,
                merchant_id=request.payload["merchant_id"], terminal_id=terminal.id,
                authorization_id=authorization.id, amount_cents=request.payload["amount_cents"],
                currency=request.payload["currency"], nonce=request.payload["nonce"],
                request_envelope=request_wire, receipt_envelope=receipt_wire,
                ack_envelope=ack_wire, state="PENDING_REVIEW",
                rejection_code="EVIDENCE_OMITTED_FROM_CLOSURE",
            ))
            db.commit()
            return _result(operation_id, "VALIDATED", "PENDING_REVIEW", False,
                           "EVIDENCE_OMITTED_FROM_CLOSURE")
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
    if not verify_trusted_authorization(grant):
        raise ValueError("grant")
    validate_receipt_binding(request, receipt, grant)
    pos_key = db.get(models.RegisteredKey, request.payload["pos_key_id"])
    terminal = db.get(models.Terminal, request.payload["terminal_id"])
    if (pos_key is None or pos_key.purpose != "pos" or terminal is None
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
    wallet_key = db.get(models.RegisteredKey, grant.payload["wallet_key_id"])
    if (wallet_key is None or wallet_key.wallet_id != wallet.id or wallet_key.purpose != "wallet"
            or wallet_key.fingerprint != grant.payload["wallet_key_fingerprint"]
            or wallet_key.public_key_b64 != grant.payload["wallet_public_key_b64"]):
        raise ValueError("wallet key")
    review = requires_review(pos_key, parse_timestamp(request.payload["issued_at"]))
    review = review or requires_review(wallet_key, parse_timestamp(receipt.payload["confirmed_at"]))
    if ack_wire is not None:
        ack = parse_signed_envelope(ack_wire)
        validate_ack_binding(request, receipt, ack)
        if not verify_pos_signer(ack, pos_key.public_key_b64, pos_key.key_id,
                                 pos_key.fingerprint, terminal.merchant_id, terminal.id):
            raise ValueError("ack")
        review = review or requires_review(pos_key, parse_timestamp(ack.payload["accepted_at"]))
    merchant_wallet = db.query(models.Wallet).filter(models.Wallet.user_id == terminal.merchant_user_id).one_or_none()
    if merchant_wallet is None:
        raise ValueError("merchant wallet")
    return wallet, merchant_wallet, terminal, authorization, commitment, review


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
    issuer = IssuerIdentity.load_external(
        os.environ["ISSUER_KEY_PATH"], os.environ["ISSUER_KEY_FINGERPRINT"]
    )
    grant = parse_signed_envelope(commitment.authorization_envelope)
    request = parse_signed_envelope(payment.request_envelope)
    receipt = parse_signed_envelope(payment.receipt_envelope)
    resolution_wire = issuer.sign_envelope({
        "version": 3, "type": "payment_resolution",
        "operation_id": payment.operation_id, "wallet_id": payment.wallet_id,
        "merchant_id": payment.merchant_id, "terminal_id": payment.terminal_id,
        "amount_cents": amount, "currency": payment.currency,
        "offline_authorization_id": payment.authorization_id,
        "authorization_digest": payload_digest(grant),
        "request_digest": payload_digest(request), "receipt_digest": payload_digest(receipt),
        "operation_status": "ACCEPTED", "code": "ACCEPTED", "resolution_revision": 1,
        "resolved_at": payment.applied_at.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issuer_key_id": issuer.key_id, "issuer_key_fingerprint": issuer.fingerprint,
    })
    db.add(models.PaymentResolution(
        operation_id=payment.operation_id, status="ACCEPTED",
        resolution_envelope=resolution_wire, revision=1,
    ))
    db.commit()
    event("PAGO_APLICADO_UNA_VEZ", operacion=payment.operation_id,
          billetera=payment.wallet_id, comercio=payment.merchant_id,
          terminal=payment.terminal_id, centavos=amount, estado="ACCEPTED")
    return _result(payment.operation_id, "VALIDATED", "ACCEPTED", True,
                   resolution=resolution_wire)


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


def _result(operation_id, submission, operation, final, code=None, resolution=None):
    return schemas.OfflinePaymentResultV3(
        operation_id=operation_id, submission_status=submission,
        operation_status=operation, final=final, code=code,
        resolution_envelope_b64=(
            base64.b64encode(resolution).decode("ascii") if resolution is not None else None
        ),
    )
