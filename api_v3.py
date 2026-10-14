from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from clock import utc_now
from auth import get_current_user, require_role
from database import get_db
from issuer_keys import IssuerIdentity
from protocol_v3 import parse_signed_envelope, payload_digest, validate_close_manifest, verify_authorization
from sync_v3 import process_evidence_v3
from settings import MAX_OFFLINE_PAYMENTS, MAX_PAYMENT_CENTS, OFFLINE_AUTHORIZATION_SECONDS

router = APIRouter(prefix="/api/v3")
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[models.User, Depends(get_current_user)]


@router.post("/simulated-topups", response_model=schemas.SimulatedTopupResponse)
def simulated_topup_v3(
    request: schemas.SimulatedTopupRequest,
    db: DbSession,
    user: Annotated[models.User, Depends(require_role("cliente"))],
):
    wallet = db.get(models.Wallet, request.wallet_id)
    if wallet is None or wallet.user_id != user.id:
        raise HTTPException(403, "Billetera no autorizada")
    existing = db.get(models.SimulatedTopup, request.request_id)
    if existing is not None:
        if (existing.wallet_id != request.wallet_id
                or existing.user_id != user.id
                or existing.amount_cents != request.amount_cents):
            raise HTTPException(409, "request_id reutilizado con otro contenido")
        db.refresh(wallet)
        return schemas.SimulatedTopupResponse(
            request_id=existing.request_id, wallet_id=existing.wallet_id,
            amount_cents=existing.amount_cents,
            confirmed_balance_cents=wallet.confirmed_balance_cents,
        )
    db.add(models.SimulatedTopup(
        request_id=request.request_id, wallet_id=wallet.id,
        user_id=user.id, amount_cents=request.amount_cents,
    ))
    db.execute(update(models.Wallet).where(models.Wallet.id == wallet.id).values(
        confirmed_balance_cents=models.Wallet.confirmed_balance_cents + request.amount_cents
    ))
    db.execute(update(models.User).where(models.User.id == user.id).values(
        saldo_real=models.User.saldo_real + Decimal(request.amount_cents) / Decimal("100")
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.get(models.SimulatedTopup, request.request_id)
        if (existing is None or existing.wallet_id != request.wallet_id
                or existing.user_id != user.id
                or existing.amount_cents != request.amount_cents):
            raise HTTPException(409, "Recarga simulada conflictiva") from exc
    db.refresh(wallet)
    return schemas.SimulatedTopupResponse(
        request_id=request.request_id, wallet_id=wallet.id,
        amount_cents=request.amount_cents,
        confirmed_balance_cents=wallet.confirmed_balance_cents,
    )


@router.post("/offline-authorizations", response_model=schemas.OfflineAuthorizationV3Response)
def issue_authorization_v3(
    request: schemas.OfflineAuthorizationV3Request,
    db: DbSession,
    user: Annotated[models.User, Depends(require_role("cliente"))],
):
    if request.max_payment_cents > MAX_PAYMENT_CENTS or request.max_payments > MAX_OFFLINE_PAYMENTS:
        raise HTTPException(422, "Limites de autorizacion excedidos")
    wallet = db.get(models.Wallet, request.wallet_id)
    key = db.get(models.RegisteredKey, request.wallet_key_id)
    if wallet is None or wallet.user_id != user.id or key is None or key.revoked or key.wallet_id != wallet.id:
        raise HTTPException(403, "Billetera o clave no autorizada")
    if wallet.offline_review_required:
        raise HTTPException(409, "La billetera requiere revision contable")
    previous = db.query(models.OfflineAuthorization).filter_by(
        issuance_request_id=request.request_id
    ).one_or_none()
    if previous is not None:
        return _repeat_authorization(db, previous, request)
    issuer_path = os.getenv("ISSUER_KEY_PATH")
    issuer_pin = os.getenv("ISSUER_KEY_FINGERPRINT")
    if not issuer_path or not issuer_pin:
        raise HTTPException(503, "Emisor v3 no configurado")
    try:
        issuer = IssuerIdentity.load_external(issuer_path, issuer_pin)
    except Exception as exc:
        raise HTTPException(503, "Emisor v3 no disponible") from exc
    now = utc_now().replace(microsecond=0)
    total = request.max_payment_cents * request.max_payments
    locked = db.execute(
        update(models.Wallet).where(models.Wallet.id == wallet.id).values(
            confirmed_balance_cents=models.Wallet.confirmed_balance_cents
        )
    )
    if locked.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "No se pudo reservar el presupuesto offline")
    committed = int(db.query(func.coalesce(func.sum(models.OfflineCommitment.reserved_cents - models.OfflineCommitment.emitted_cents), 0)).filter(
        models.OfflineCommitment.wallet_id == wallet.id, models.OfflineCommitment.closed.is_(False)
    ).scalar())
    if wallet.confirmed_balance_cents - committed < total:
        raise HTTPException(409, "Saldo insuficiente para compromiso")
    auth_id = str(uuid4())
    expires = now + timedelta(seconds=OFFLINE_AUTHORIZATION_SECONDS)
    payload = {
        "version": 3, "type": "offline_authorization", "authorization_id": auth_id,
        "wallet_id": wallet.id, "wallet_key_id": key.key_id, "wallet_key_fingerprint": key.fingerprint,
        "wallet_public_key_b64": key.public_key_b64, "currency": "ARS",
        "max_payment_cents": request.max_payment_cents, "max_payments": request.max_payments,
        "authorized_total_cents": total, "max_request_lifetime_seconds": 120,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "spend_expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issuer_key_id": issuer.key_id, "issuer_key_fingerprint": issuer.fingerprint,
    }
    signed = issuer.sign_envelope(payload)
    db.add(models.OfflineAuthorization(id=auth_id, issuance_request_id=request.request_id,
        wallet_id=wallet.id, wallet_key_id=key.key_id,
        max_payment_cents=request.max_payment_cents, remaining_amount_cents=total,
        remaining_payments=request.max_payments, issued_at=now, expires_at=expires, active=True))
    db.add(models.OfflineCommitment(authorization_id=auth_id, wallet_id=wallet.id, reserved_cents=total,
        authorization_envelope=signed))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        previous = db.query(models.OfflineAuthorization).filter_by(
            issuance_request_id=request.request_id
        ).one_or_none()
        if previous is None:
            raise HTTPException(409, "No se pudo emitir la autorizacion") from exc
        return _repeat_authorization(db, previous, request)
    return schemas.OfflineAuthorizationV3Response(authorization_id=auth_id, wallet_id=wallet.id,
        authorized_total_cents=total, authorization_envelope_b64=base64.b64encode(signed).decode("ascii"),
        issued_at=now, spend_expires_at=expires)


@router.get("/offline-authorizations/{authorization_id}/commitment", response_model=schemas.OfflineCommitmentResponse)
def commitment_v3(authorization_id: str, db: DbSession, user: CurrentUser):
    commitment = db.get(models.OfflineCommitment, authorization_id)
    if commitment is None:
        raise HTTPException(404, "Autorizacion no encontrada")
    wallet = db.get(models.Wallet, commitment.wallet_id)
    if wallet is None or wallet.user_id != user.id:
        raise HTTPException(403, "Autorizacion no autorizada")
    return commitment


@router.post("/offline-authorizations/{authorization_id}/close", response_model=schemas.OfflineCommitmentResponse)
def close_authorization_v3(authorization_id: str, request: schemas.OfflineAuthorizationCloseRequest,
                           db: DbSession, user: CurrentUser):
    commitment = db.get(models.OfflineCommitment, authorization_id)
    if commitment is None:
        raise HTTPException(404, "Compromiso no encontrado")
    wallet = db.get(models.Wallet, commitment.wallet_id)
    if wallet is None or wallet.user_id != user.id:
        raise HTTPException(403, "Autorizacion no autorizada")
    try:
        close = parse_signed_envelope(base64.b64decode(request.close_envelope_b64, validate=True))
        grant = parse_signed_envelope(commitment.authorization_envelope or b"")
        manifest = base64.b64decode(request.manifest_b64, validate=True)
        issuer = IssuerIdentity.load_external(os.environ["ISSUER_KEY_PATH"], os.environ["ISSUER_KEY_FINGERPRINT"])
        if not verify_authorization(grant, issuer.public_key_b64, issuer.key_id):
            raise ValueError("grant")
        entries = validate_close_manifest(close, grant, manifest)
        if close.payload["authorization_id"] != authorization_id:
            raise ValueError("authorization")
        if commitment.closed:
            if commitment.closure_id == close.payload["closure_id"]:
                return commitment
            raise HTTPException(409, "Autorizacion cerrada con otra evidencia")
        if sum(int(entry["amount_cents"]) for entry in entries) != commitment.emitted_cents:
            raise ValueError("manifest")
        for entry in entries:
            emission = db.query(models.CommitmentEmission).filter_by(
                authorization_id=authorization_id,
                operation_id=entry["operation_id"],
                issuance_index=entry["issuance_index"],
            ).one_or_none()
            payment = db.get(models.OfflinePaymentV2, entry["operation_id"])
            if (emission is None or payment is None or payment.state != "ACCEPTED"
                    or emission.amount_cents != entry["amount_cents"]
                    or payload_digest(parse_signed_envelope(payment.receipt_envelope)) != entry["receipt_digest"]):
                raise ValueError("manifest evidence")
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(422, "Cierre invalido") from exc
    closed = db.execute(update(models.OfflineCommitment).where(
        models.OfflineCommitment.authorization_id == authorization_id,
        models.OfflineCommitment.closed.is_(False),
    ).values(closed=True, closure_id=close.payload["closure_id"]))
    if closed.rowcount != 1:
        db.rollback()
        current = db.get(models.OfflineCommitment, authorization_id)
        if current is not None and current.closed and current.closure_id == close.payload["closure_id"]:
            return current
        raise HTTPException(409, "Autorizacion cerrada concurrentemente con otra evidencia")
    db.execute(update(models.OfflineAuthorization).where(
        models.OfflineAuthorization.id == authorization_id
    ).values(active=False))
    db.commit()
    return db.get(models.OfflineCommitment, authorization_id)


@router.post("/offline-payments/sync", response_model=schemas.OfflinePaymentSyncV3Response)
def sync_v3(request: schemas.OfflinePaymentSyncV3Request, db: DbSession, user: CurrentUser):
    return schemas.OfflinePaymentSyncV3Response(
        results=[process_evidence_v3(db, user, evidence) for evidence in request.operations]
    )


@router.post("/offline-payments/{operation_id}/resolution")
def store_resolution_v3(operation_id: str, request: schemas.PaymentResolutionRequest,
                        db: DbSession, user: CurrentUser):
    payment = db.get(models.OfflinePaymentV2, operation_id)
    if payment is None:
        raise HTTPException(404, "Operacion no encontrada")
    _authorize_payment_participant(db, user, payment)
    try:
        envelope_bytes = base64.b64decode(request.resolution_envelope_b64, validate=True)
        envelope = parse_signed_envelope(envelope_bytes)
        receipt = parse_signed_envelope(payment.receipt_envelope)
        request_envelope = parse_signed_envelope(payment.request_envelope)
        commitment = db.get(models.OfflineCommitment, payment.authorization_id)
        grant = parse_signed_envelope(commitment.authorization_envelope if commitment else b"")
        if (envelope.payload.get("operation_id") != operation_id
                or envelope.payload.get("operation_status") != payment.state
                or envelope.payload.get("wallet_id") != payment.wallet_id
                or envelope.payload.get("terminal_id") != payment.terminal_id
                or envelope.payload.get("amount_cents") != payment.amount_cents
                or envelope.payload.get("request_digest") != payload_digest(request_envelope)
                or envelope.payload.get("receipt_digest") != payload_digest(receipt)
                or envelope.payload.get("authorization_digest") != payload_digest(grant)):
            raise ValueError("resolution")
        issuer = IssuerIdentity.load_external(os.environ["ISSUER_KEY_PATH"], os.environ["ISSUER_KEY_FINGERPRINT"])
        if not envelope.verify(issuer.public_key_b64):
            raise ValueError("signature")
    except Exception as exc:
        raise HTTPException(422, "Resolucion invalida") from exc
    existing = db.get(models.PaymentResolution, operation_id)
    if existing is not None:
        if existing.resolution_envelope != envelope_bytes:
            raise HTTPException(409, "Resolucion conflictiva")
        return {"operation_id": operation_id, "status": existing.status, "final": True, "revision": existing.revision}
    record = models.PaymentResolution(operation_id=operation_id, status=envelope.payload["operation_status"],
                                      resolution_envelope=envelope_bytes, revision=envelope.payload["resolution_revision"])
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(models.PaymentResolution, operation_id)
        if existing is None or existing.resolution_envelope != envelope_bytes:
            raise HTTPException(409, "Resolucion conflictiva")
        return {"operation_id": operation_id, "status": existing.status, "final": True, "revision": existing.revision}
    return {"operation_id": operation_id, "status": record.status, "final": True, "revision": record.revision}


@router.get("/offline-payments/{operation_id}", response_model=schemas.OfflinePaymentResultV3)
def get_payment_v3(operation_id: str, db: DbSession, user: CurrentUser):
    payment = db.get(models.OfflinePaymentV2, operation_id)
    if payment is None:
        raise HTTPException(404, "Operacion no encontrada")
    _authorize_payment_participant(db, user, payment)
    resolution = db.get(models.PaymentResolution, operation_id)
    final = payment.state in {"ACCEPTED", "REJECTED"} and resolution is not None
    operation_status = payment.state if payment.state in {
        "ACCEPTED", "REJECTED", "PENDING_EVIDENCE", "PENDING_REVIEW"
    } else "UNRESOLVED"
    return schemas.OfflinePaymentResultV3(
        operation_id=operation_id, submission_status="VALIDATED",
        operation_status=operation_status, final=final, code=payment.rejection_code,
        resolution_envelope_b64=(
            base64.b64encode(resolution.resolution_envelope).decode("ascii") if resolution else None
        ),
    )


def _authorize_payment_participant(db: Session, user: models.User,
                                   payment: models.OfflinePaymentV2) -> None:
    wallet = db.get(models.Wallet, payment.wallet_id)
    terminal = db.get(models.Terminal, payment.terminal_id)
    if not ((wallet and wallet.user_id == user.id)
            or (terminal and terminal.merchant_user_id == user.id)):
        raise HTTPException(403, "Operacion no autorizada")


def _repeat_authorization(db: Session, previous: models.OfflineAuthorization,
                          request: schemas.OfflineAuthorizationV3Request):
    commitment = db.get(models.OfflineCommitment, previous.id)
    same = (
        previous.wallet_id == request.wallet_id
        and previous.wallet_key_id == request.wallet_key_id
        and previous.max_payment_cents == request.max_payment_cents
        and previous.remaining_payments <= request.max_payments
        and commitment is not None
        and commitment.reserved_cents == request.max_payment_cents * request.max_payments
        and commitment.authorization_envelope is not None
    )
    if not same:
        raise HTTPException(409, "request_id reutilizado con otro contenido")
    return schemas.OfflineAuthorizationV3Response(
        authorization_id=previous.id, wallet_id=previous.wallet_id,
        authorized_total_cents=commitment.reserved_cents,
        authorization_envelope_b64=base64.b64encode(commitment.authorization_envelope).decode("ascii"),
        issued_at=previous.issued_at, spend_expires_at=previous.expires_at,
    )
