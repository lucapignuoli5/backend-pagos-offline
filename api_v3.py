from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from clock import utc_now
from auth import get_current_user, require_role
from database import get_db
from issuer_keys import IssuerIdentity
from protocol_v3 import (
    parse_signed_envelope, parse_timestamp, payload_digest, validate_ack_binding, validate_close_manifest,
    validate_receipt_binding, verify_authorization, verify_pos_signer,
)
from sync_v3 import process_evidence_v3
from demo_events import event
from issuer_trust import issuer_public_key, verify_trusted_authorization
from revocation import requires_review
from settings import LEGACY_INVENTORY_OPEN, MAX_OFFLINE_PAYMENTS, MAX_PAYMENT_CENTS, OFFLINE_AUTHORIZATION_SECONDS

router = APIRouter(prefix="/api/v3")
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[models.User, Depends(get_current_user)]


@router.post("/legacy-inventory")
def register_legacy_inventory(
    request: schemas.LegacyInventoryRequest,
    db: DbSession,
    user: Annotated[models.User, Depends(require_role("cliente"))],
):
    if not LEGACY_INVENTORY_OPEN:
        raise HTTPException(403, "Ventana de inventario historico cerrada")
    wallet = db.get(models.Wallet, request.wallet_id)
    if wallet is None or wallet.user_id != user.id:
        raise HTTPException(403, "Billetera no autorizada")
    imported = 0
    for entry in request.operations:
        try:
            parsed_operation_id = UUID(entry.operation_id)
            if parsed_operation_id.version != 4 or str(parsed_operation_id) != entry.operation_id:
                raise ValueError("uuid")
        except ValueError as exc:
            raise HTTPException(422, "operation_id historico invalido") from exc
        authorization = db.get(models.OfflineAuthorization, entry.authorization_id)
        if (authorization is None or authorization.wallet_id != wallet.id
                or db.get(models.OfflineCommitment, authorization.id) is not None):
            raise HTTPException(409, "Autorizacion historica incompatible")
        existing = db.get(models.LegacyEvidenceInventory, entry.operation_id)
        if existing is not None:
            if (existing.wallet_id != wallet.id
                    or existing.authorization_id != entry.authorization_id
                    or existing.receipt_digest != entry.receipt_digest):
                raise HTTPException(409, "Inventario historico conflictivo")
            continue
        db.add(models.LegacyEvidenceInventory(
            operation_id=entry.operation_id, wallet_id=wallet.id,
            authorization_id=entry.authorization_id,
            receipt_digest=entry.receipt_digest,
        ))
        imported += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Inventario historico concurrente") from exc
    return {"wallet_id": wallet.id, "imported": imported, "total": len(request.operations)}


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
        event("RECARGA_REPETIDA_SIN_NUEVO_CREDITO", usuario_id=user.id,
              billetera=wallet.id, centavos=existing.amount_cents)
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
    event("RECARGA_SIMULADA_CONFIRMADA", usuario_id=user.id,
          billetera=wallet.id, centavos=request.amount_cents)
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
    wallet = db.get(models.Wallet, request.wallet_id)
    key = db.get(models.RegisteredKey, request.wallet_key_id)
    if wallet is None or wallet.user_id != user.id:
        raise HTTPException(403, "Billetera o clave no autorizada")
    previous = db.query(models.OfflineAuthorization).filter_by(
        issuance_request_id=request.request_id
    ).one_or_none()
    if previous is not None:
        return _repeat_authorization(db, previous, request)
    if request.max_payment_cents > MAX_PAYMENT_CENTS or request.max_payments > MAX_OFFLINE_PAYMENTS:
        raise HTTPException(422, "Limites de autorizacion excedidos")
    if key is None or key.revoked or key.wallet_id != wallet.id:
        raise HTTPException(403, "Billetera o clave no autorizada")
    if wallet.offline_review_required:
        raise HTTPException(409, detail={
            "code": "WALLET_REVIEW_REQUIRED",
            "message": "La billetera requiere revision contable",
        })
    issuer_path = os.getenv("ISSUER_KEY_PATH")
    issuer_pin = os.getenv("ISSUER_KEY_FINGERPRINT")
    if not issuer_path or not issuer_pin:
        raise HTTPException(503, "Emisor v3 no configurado")
    try:
        issuer = IssuerIdentity.load_external(issuer_path, issuer_pin)
    except Exception as exc:
        raise HTTPException(503, "Emisor v3 no disponible") from exc
    now = utc_now().replace(microsecond=0)
    requested_total = request.max_payment_cents * request.max_payments
    if requested_total > 2**63 - 1:
        raise HTTPException(422, detail={"code": "AUTHORIZATION_LIMIT_EXCEEDED"})
    locked = db.execute(
        update(models.Wallet).where(models.Wallet.id == wallet.id).values(
            confirmed_balance_cents=models.Wallet.confirmed_balance_cents
        )
    )
    if locked.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "No se pudo reservar el presupuesto offline")
    db.refresh(wallet)
    if wallet.offline_review_required:
        db.rollback()
        raise HTTPException(409, detail={
            "code": "WALLET_REVIEW_REQUIRED",
            "message": "La billetera requiere revision contable",
        })
    if wallet.offline_review_required:
        db.rollback()
        raise HTTPException(409, detail={
            "code": "WALLET_REVIEW_REQUIRED",
            "message": "La billetera requiere revision contable",
        })
    committed = int(db.query(func.coalesce(func.sum(models.OfflineCommitment.held_cents), 0)).filter(
        models.OfflineCommitment.wallet_id == wallet.id
    ).scalar())
    committed += int(db.query(func.coalesce(func.sum(models.OfflineAuthorization.remaining_amount_cents), 0)).filter(
        models.OfflineAuthorization.wallet_id == wallet.id,
        models.OfflineAuthorization.active.is_(True),
        ~models.OfflineAuthorization.id.in_(select(models.OfflineCommitment.authorization_id)),
    ).scalar())
    available = max(wallet.confirmed_balance_cents - committed, 0)
    total = min(available, requested_total)
    if total <= 0:
        db.rollback()
        raise HTTPException(409, detail={
            "code": "AUTHORIZATION_BUDGET_UNAVAILABLE",
            "message": "No hay saldo libre para una nueva autorizacion offline",
        })
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
        held_cents=total, authorization_envelope=signed))
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
    event("AUTORIZACION_OFFLINE_EMITIDA", usuario_id=user.id,
          billetera=wallet.id, autorizacion=auth_id, centavos=total, cantidad=request.max_payments)
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
    db.execute(update(models.Wallet).where(models.Wallet.id == wallet.id).values(
        confirmed_balance_cents=models.Wallet.confirmed_balance_cents))
    db.refresh(commitment)
    try:
        close = parse_signed_envelope(base64.b64decode(request.close_envelope_b64, validate=True))
        grant = parse_signed_envelope(commitment.authorization_envelope or b"")
        manifest = base64.b64decode(request.manifest_b64, validate=True)
        if not verify_trusted_authorization(grant):
            raise ValueError("grant")
        entries = validate_close_manifest(close, grant, manifest)
        if close.payload["authorization_id"] != authorization_id:
            raise ValueError("authorization")
        if commitment.closed:
            if (commitment.closure_id == close.payload["closure_id"]
                    and commitment.closure_envelope == base64.b64decode(request.close_envelope_b64, validate=True)
                    and commitment.closure_manifest == manifest):
                return commitment
            raise HTTPException(409, "Autorizacion cerrada con otra evidencia")
        claims = db.query(models.CommitmentClaim).filter_by(
            authorization_id=authorization_id
        ).order_by(models.CommitmentClaim.issuance_index, models.CommitmentClaim.operation_id).all()
        payments = db.query(models.OfflinePaymentV2).filter_by(
            authorization_id=authorization_id
        ).all()
        claim_by_operation = {claim.operation_id: claim for claim in claims}
        entry_by_operation = {entry["operation_id"]: entry for entry in entries}
        if (len(claims) != len(entries) or len(payments) != len(entries)
                or set(claim_by_operation) != set(entry_by_operation)
                or {payment.operation_id for payment in payments} != set(entry_by_operation)):
            raise ValueError("manifest incompleto o con evidencia omitida")
        if len({claim.issuance_index for claim in claims}) != len(claims):
            wallet.offline_review_required = True
            db.commit()
            raise HTTPException(409, detail={"code": "ISSUANCE_INDEX_CONFLICT"})
        payment_by_operation = {payment.operation_id: payment for payment in payments}
        accepted_total = 0
        rejected_total = 0
        for entry in entries:
            claim = claim_by_operation.get(entry["operation_id"])
            payment = payment_by_operation.get(entry["operation_id"])
            if claim is None or payment is None:
                raise ValueError("manifest evidence")
            request_wire = bytes(payment.request_envelope)
            receipt_wire = bytes(payment.receipt_envelope)
            request_envelope = parse_signed_envelope(request_wire)
            receipt_envelope = parse_signed_envelope(receipt_wire)
            pos_key = db.get(models.RegisteredKey, request_envelope.payload["pos_key_id"])
            terminal = db.get(models.Terminal, payment.terminal_id)
            wallet_key = db.get(models.RegisteredKey, grant.payload["wallet_key_id"])
            if (claim.issuance_index != entry["issuance_index"]
                    or claim.amount_cents != entry["amount_cents"]
                    or claim.receipt_digest != entry["receipt_digest"]
                    or payment.amount_cents != entry["amount_cents"]
                    or payment.wallet_id != wallet.id
                    or payment.authorization_id != authorization_id
                    or payment.merchant_id != request_envelope.payload["merchant_id"]
                    or payment.terminal_id != request_envelope.payload["terminal_id"]
                    or payment.currency != request_envelope.payload["currency"]
                    or payload_digest(receipt_envelope) != entry["receipt_digest"]):
                raise ValueError("manifest distinto de evidencia registrada")
            validate_receipt_binding(request_envelope, receipt_envelope, grant)
            if (pos_key is None or terminal is None
                    or pos_key.terminal_id != terminal.id
                    or not verify_pos_signer(request_envelope, pos_key.public_key_b64, pos_key.key_id,
                                             pos_key.fingerprint, terminal.merchant_id, terminal.id)):
                raise ValueError("firma o alcance POS invalido")
            if (wallet_key is None or wallet_key.wallet_id != wallet.id or wallet_key.purpose != "wallet"
                    or wallet_key.fingerprint != grant.payload["wallet_key_fingerprint"]
                    or wallet_key.public_key_b64 != grant.payload["wallet_public_key_b64"]):
                raise ValueError("clave de billetera desconocida")
            issued_at = parse_timestamp(request_envelope.payload["issued_at"])
            confirmed_at = parse_timestamp(receipt_envelope.payload["confirmed_at"])
            if requires_review(pos_key, issued_at) or requires_review(wallet_key, confirmed_at):
                wallet.offline_review_required = True
                db.commit()
                raise HTTPException(409, detail={"code": "EVIDENCE_REVOCATION_REVIEW"})
            if payment.ack_envelope is not None:
                ack = parse_signed_envelope(bytes(payment.ack_envelope))
                validate_ack_binding(request_envelope, receipt_envelope, ack)
                if not verify_pos_signer(ack, pos_key.public_key_b64, pos_key.key_id,
                                         pos_key.fingerprint, terminal.merchant_id, terminal.id):
                    raise ValueError("firma de acuse invalida")
                if requires_review(pos_key, parse_timestamp(ack.payload["accepted_at"])):
                    wallet.offline_review_required = True
                    db.commit()
                    raise HTTPException(409, detail={"code": "ACK_REVOCATION_REVIEW"})
            if payment.state == "ACCEPTED":
                accepted_total += payment.amount_cents
            elif payment.state == "REJECTED":
                resolution = db.get(models.PaymentResolution, payment.operation_id)
                if resolution is None or resolution.status != "REJECTED":
                    raise ValueError("rechazo sin resolucion definitiva")
                result = parse_signed_envelope(bytes(resolution.resolution_envelope))
                expected = {
                    "type": "payment_resolution", "operation_status": "REJECTED",
                    "operation_id": payment.operation_id, "wallet_id": payment.wallet_id,
                    "merchant_id": payment.merchant_id, "terminal_id": payment.terminal_id,
                    "amount_cents": payment.amount_cents, "currency": payment.currency,
                    "offline_authorization_id": authorization_id,
                    "authorization_digest": payload_digest(grant),
                    "request_digest": payload_digest(request_envelope),
                    "receipt_digest": payload_digest(receipt_envelope),
                    "resolution_revision": resolution.revision, "code": payment.rejection_code,
                }
                if (any(result.payload.get(field) != value for field, value in expected.items())
                        or not result.verify(issuer_public_key(result.payload))
                        or payment.applied_at is not None
                        or db.query(models.LedgerEntry).filter_by(operation_id=payment.operation_id).first() is not None
                        or db.query(models.CommitmentEmission).filter_by(operation_id=payment.operation_id).first() is not None):
                    raise ValueError("rechazo contradictorio con evidencia o contabilidad")
                rejected_total += payment.amount_cents
            elif payment.state not in {"PENDING_EVIDENCE", "VALIDATED"}:
                raise ValueError("operacion en revision; no se libera presupuesto")
        total_issued = sum(int(entry["amount_cents"]) for entry in entries)
        expected_held_before_close = (
            commitment.reserved_cents - commitment.emitted_cents
            - commitment.released_rejected_cents - commitment.released_unissued_cents
        )
        if (accepted_total != commitment.emitted_cents
                or rejected_total != commitment.released_rejected_cents
                or total_issued > commitment.reserved_cents
                or total_issued < commitment.emitted_cents + commitment.released_rejected_cents
                or commitment.held_cents != expected_held_before_close
                or commitment.released_unissued_cents != 0):
            raise ValueError("invariante contable del manifiesto")
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(422, "Cierre invalido") from exc
    unissued = commitment.reserved_cents - total_issued
    remaining_held = commitment.held_cents - unissued
    closed = db.execute(update(models.OfflineCommitment).where(
        models.OfflineCommitment.authorization_id == authorization_id,
        models.OfflineCommitment.closed.is_(False),
    ).values(
        closed=True,
        phase="SETTLED" if remaining_held == 0 else "SEALED",
        released_unissued_cents=unissued,
        held_cents=remaining_held,
        closure_id=close.payload["closure_id"],
        closure_envelope=base64.b64decode(request.close_envelope_b64, validate=True),
        closure_manifest=manifest,
        manifest_digest=payload_digest(manifest),
    ))
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
    event("AUTORIZACION_CERRADA", usuario_id=user.id, autorizacion=authorization_id)
    return db.get(models.OfflineCommitment, authorization_id)


@router.post("/offline-payments/sync", response_model=schemas.OfflinePaymentSyncV3Response)
def sync_v3(request: schemas.OfflinePaymentSyncV3Request, db: DbSession, user: CurrentUser):
    results = []
    for evidence in request.operations:
        result = process_evidence_v3(db, user, evidence)
        event("CONCILIACION", usuario_id=user.id, operacion=result.operation_id,
              envio=result.submission_status, estado=result.operation_status,
              definitivo=result.final, codigo=result.code)
        results.append(result)
    return schemas.OfflinePaymentSyncV3Response(results=results)


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
                or envelope.payload.get("merchant_id") != payment.merchant_id
                or envelope.payload.get("currency") != payment.currency
                or envelope.payload.get("offline_authorization_id") != payment.authorization_id
                or envelope.payload.get("terminal_id") != payment.terminal_id
                or envelope.payload.get("amount_cents") != payment.amount_cents
                or envelope.payload.get("request_digest") != payload_digest(request_envelope)
                or envelope.payload.get("receipt_digest") != payload_digest(receipt)
                or envelope.payload.get("authorization_digest") != payload_digest(grant)):
            raise ValueError("resolution")
        if not envelope.verify(issuer_public_key(envelope.payload)):
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
    try:
        grant = parse_signed_envelope(commitment.authorization_envelope if commitment else b"")
    except Exception:
        grant = None
    same = (
        previous.wallet_id == request.wallet_id
        and previous.wallet_key_id == request.wallet_key_id
        and previous.max_payment_cents == request.max_payment_cents
        and grant is not None
        and grant.payload.get("max_payments") == request.max_payments
        and grant.payload.get("max_payment_cents") == request.max_payment_cents
        and grant.payload.get("wallet_id") == request.wallet_id
        and grant.payload.get("wallet_key_id") == request.wallet_key_id
        and commitment is not None
        and commitment.authorization_envelope is not None
    )
    if not same:
        raise HTTPException(409, "request_id reutilizado con otro contenido")
    event("AUTORIZACION_REUTILIZADA", billetera=previous.wallet_id, autorizacion=previous.id)
    return schemas.OfflineAuthorizationV3Response(
        authorization_id=previous.id, wallet_id=previous.wallet_id,
        authorized_total_cents=commitment.reserved_cents,
        authorization_envelope_b64=base64.b64encode(commitment.authorization_envelope).decode("ascii"),
        issued_at=previous.issued_at.replace(tzinfo=timezone.utc) if previous.issued_at.tzinfo is None else previous.issued_at,
        spend_expires_at=previous.expires_at.replace(tzinfo=timezone.utc) if previous.expires_at.tzinfo is None else previous.expires_at,
    )
