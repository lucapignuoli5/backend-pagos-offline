from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user, require_role
from database import get_db
from issuer_keys import IssuerIdentity
from protocol_v3 import parse_signed_envelope, validate_close_manifest, verify_authorization
from sync_v2 import process_evidence
from settings import MAX_OFFLINE_PAYMENTS, MAX_PAYMENT_CENTS, OFFLINE_AUTHORIZATION_SECONDS

router = APIRouter(prefix="/api/v3")
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[models.User, Depends(get_current_user)]


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
    issuer_path = os.getenv("ISSUER_KEY_PATH")
    issuer_pin = os.getenv("ISSUER_KEY_FINGERPRINT")
    if not issuer_path or not issuer_pin:
        raise HTTPException(503, "Emisor v3 no configurado")
    try:
        issuer = IssuerIdentity.load_external(issuer_path, issuer_pin)
    except Exception as exc:
        raise HTTPException(503, "Emisor v3 no disponible") from exc
    now = datetime.now(timezone.utc).replace(microsecond=0)
    total = request.max_payment_cents * request.max_payments
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
    db.add(models.OfflineAuthorization(id=auth_id, wallet_id=wallet.id, wallet_key_id=key.key_id,
        max_payment_cents=request.max_payment_cents, remaining_amount_cents=total,
        remaining_payments=request.max_payments, issued_at=now, expires_at=expires, active=True))
    db.add(models.OfflineCommitment(authorization_id=auth_id, wallet_id=wallet.id, reserved_cents=total,
        authorization_envelope=signed))
    db.commit()
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
    if commitment is None or commitment.closed:
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
        if sum(int(entry["amount_cents"]) for entry in entries) != commitment.emitted_cents:
            raise ValueError("manifest")
    except Exception as exc:
        db.rollback()
        raise HTTPException(422, "Cierre invalido") from exc
    commitment.closed = True
    commitment.closure_id = close.payload["closure_id"]
    db.commit()
    return commitment


@router.post("/offline-payments/sync", response_model=schemas.OfflinePaymentSyncV2Response)
def sync_v3(request: schemas.OfflinePaymentSyncV2Request, db: DbSession, user: CurrentUser):
    results = []
    for evidence in request.operations:
        result = process_evidence(db, user, evidence)
        results.append(result)
        if result.status == "ACCEPTED":
            payment = db.get(models.OfflinePaymentV2, evidence.operation_id)
            if payment is not None:
                commitment = db.get(models.OfflineCommitment, payment.authorization_id)
                already = db.query(models.CommitmentEmission).filter_by(
                    authorization_id=payment.authorization_id, operation_id=payment.operation_id
                ).first()
                if commitment is not None and already is None and commitment.emitted_cents + payment.amount_cents <= commitment.reserved_cents:
                    db.add(models.CommitmentEmission(
                        authorization_id=payment.authorization_id,
                        operation_id=payment.operation_id,
                        amount_cents=payment.amount_cents,
                    ))
                    commitment.emitted_cents = min(commitment.reserved_cents, commitment.emitted_cents + payment.amount_cents)
                    commitment.emitted_count += 1
                    db.commit()
    return schemas.OfflinePaymentSyncV2Response(results=results)


@router.post("/offline-payments/{operation_id}/resolution")
def store_resolution_v3(operation_id: str, request: schemas.PaymentResolutionRequest,
                        db: DbSession, user: CurrentUser):
    try:
        envelope_bytes = base64.b64decode(request.resolution_envelope_b64, validate=True)
        envelope = parse_signed_envelope(envelope_bytes)
        if envelope.payload.get("operation_id") != operation_id or envelope.payload.get("operation_status") not in {"ACCEPTED", "REJECTED"}:
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
    db.commit()
    return {"operation_id": operation_id, "status": record.status, "final": True, "revision": record.revision}
