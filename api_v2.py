from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user, require_role
from database import get_db
from protocol_v2 import ID_PATTERN, canonical_json, public_key_fingerprint, verify_exact_signature
from settings import MAX_OFFLINE_PAYMENTS, MAX_PAYMENT_CENTS, OFFLINE_AUTHORIZATION_SECONDS


router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[models.User, Depends(get_current_user)]


@router.post("/keys/register", response_model=schemas.KeyRegistrationResponse)
def register_key(
    request: schemas.KeyRegistrationRequest,
    db: DbSession,
    user: CurrentUser,
) -> schemas.KeyRegistrationResponse:
    payload_bytes = _decode_base64(request.proof_payload_b64, "proof_payload_b64")
    try:
        payload_text = payload_bytes.decode("utf-8")
        payload = json.loads(payload_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Prueba de posesion invalida") from exc
    if not isinstance(payload, dict) or canonical_json(payload) != payload_text:
        raise HTTPException(status_code=422, detail="Prueba de posesion no canonica")
    expected_fields = {
        "version", "type", "key_id", "purpose", "owner_user_id", "scope_id",
        "fingerprint", "nonce", "issued_at",
    }
    if set(payload) != expected_fields or payload.get("version") != 2 or payload.get("type") != "key_registration":
        raise HTTPException(status_code=422, detail="Campos de prueba de posesion incompatibles")
    if type(payload.get("owner_user_id")) is not int or payload.get("owner_user_id") != user.id:
        raise HTTPException(status_code=403, detail="La clave pertenece a otro usuario")
    if payload.get("purpose") not in {"wallet", "pos"}:
        raise HTTPException(status_code=422, detail="Proposito de clave invalido")
    issued_at = _parse_utc(payload.get("issued_at"), "issued_at")
    if abs((datetime.now(timezone.utc) - issued_at).total_seconds()) > 300:
        raise HTTPException(status_code=422, detail="Prueba de posesion vencida")
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not 16 <= len(nonce) <= 120:
        raise HTTPException(status_code=422, detail="Nonce de registro invalido")

    public_der = _decode_base64(request.public_key_b64, "public_key_b64")
    try:
        public_key = serialization.load_der_public_key(public_der)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Clave publica invalida") from exc
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(public_key.curve, ec.SECP256R1):
        raise HTTPException(status_code=422, detail="La clave debe usar P-256")
    fingerprint = public_key_fingerprint(public_der)
    if payload.get("fingerprint") != fingerprint:
        raise HTTPException(status_code=422, detail="Huella de clave inconsistente")
    if not verify_exact_signature(payload_bytes, request.proof_signature_b64, request.public_key_b64):
        raise HTTPException(status_code=422, detail="Prueba de posesion invalida")

    key_id = _identifier(payload.get("key_id"), "key_id")
    scope_id = _identifier(payload.get("scope_id"), "scope_id")
    purpose = payload["purpose"]
    wallet_id: str | None = None
    terminal_id: str | None = None
    if purpose == "wallet":
        if user.role != "cliente":
            raise HTTPException(status_code=403, detail="Solo clientes registran claves de billetera")
        wallet = db.get(models.Wallet, scope_id)
        if wallet is None or wallet.user_id != user.id:
            raise HTTPException(status_code=403, detail="Billetera no autorizada")
        wallet_id = scope_id
    else:
        if user.role != "comercio":
            raise HTTPException(status_code=403, detail="Solo comercios registran claves POS")
        terminal = db.get(models.Terminal, scope_id)
        if terminal is None:
            terminal = models.Terminal(
                id=scope_id,
                merchant_user_id=user.id,
                merchant_id=f"merchant-{user.id}",
                active=True,
            )
            db.add(terminal)
        elif terminal.merchant_user_id != user.id or not terminal.active:
            raise HTTPException(status_code=403, detail="Terminal no autorizada")
        terminal_id = scope_id

    existing = db.get(models.RegisteredKey, key_id)
    if existing is not None:
        same = (
            existing.owner_user_id == user.id
            and existing.purpose == purpose
            and existing.wallet_id == wallet_id
            and existing.terminal_id == terminal_id
            and existing.public_key_b64 == request.public_key_b64
            and existing.fingerprint == fingerprint
            and not existing.revoked
        )
        if not same:
            raise HTTPException(status_code=409, detail="key_id ya existe con otro contenido")
        return schemas.KeyRegistrationResponse(
            key_id=key_id, fingerprint=fingerprint, purpose=purpose, scope_id=scope_id, created=False
        )

    db.add(
        models.RegisteredKey(
            key_id=key_id,
            owner_user_id=user.id,
            purpose=purpose,
            wallet_id=wallet_id,
            terminal_id=terminal_id,
            public_key_b64=request.public_key_b64,
            fingerprint=fingerprint,
            proof_nonce=nonce,
            revoked=False,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Clave, huella o nonce ya registrado") from exc
    return schemas.KeyRegistrationResponse(
        key_id=key_id, fingerprint=fingerprint, purpose=purpose, scope_id=scope_id, created=True
    )


@router.post("/offline-authorizations", response_model=schemas.OfflineAuthorizationResponse)
def create_offline_authorization(
    request: schemas.OfflineAuthorizationRequest,
    db: DbSession,
    user: Annotated[models.User, Depends(require_role("cliente"))],
) -> schemas.OfflineAuthorizationResponse:
    if request.max_payment_cents > MAX_PAYMENT_CENTS or request.max_payments > MAX_OFFLINE_PAYMENTS:
        raise HTTPException(status_code=422, detail="Limites de autorizacion excedidos")
    wallet = db.get(models.Wallet, request.wallet_id)
    if wallet is None or wallet.user_id != user.id:
        raise HTTPException(status_code=403, detail="Billetera no autorizada")
    key = db.get(models.RegisteredKey, request.wallet_key_id)
    if key is None or key.revoked or key.owner_user_id != user.id or key.wallet_id != wallet.id or key.purpose != "wallet":
        raise HTTPException(status_code=422, detail="Clave de billetera no valida")

    now = datetime.now(timezone.utc)
    committed = db.query(func.coalesce(func.sum(models.OfflineAuthorization.remaining_amount_cents), 0)).filter(
        models.OfflineAuthorization.wallet_id == wallet.id,
        models.OfflineAuthorization.active.is_(True),
        models.OfflineAuthorization.expires_at > now,
    ).scalar()
    available = wallet.confirmed_balance_cents - int(committed)
    requested_total = request.max_payment_cents * request.max_payments
    authorized_total = min(available, requested_total)
    if authorized_total < request.max_payment_cents:
        raise HTTPException(status_code=409, detail="Saldo insuficiente para la autorizacion")
    effective_payments = min(request.max_payments, authorized_total // request.max_payment_cents)
    authorization = models.OfflineAuthorization(
        id=str(uuid4()),
        wallet_id=wallet.id,
        wallet_key_id=key.key_id,
        max_payment_cents=request.max_payment_cents,
        remaining_amount_cents=authorized_total,
        remaining_payments=effective_payments,
        issued_at=now,
        expires_at=now + timedelta(seconds=OFFLINE_AUTHORIZATION_SECONDS),
        active=True,
    )
    db.add(authorization)
    db.commit()
    return schemas.OfflineAuthorizationResponse(
        authorization_id=authorization.id,
        wallet_id=wallet.id,
        wallet_key_id=key.key_id,
        max_payment_cents=authorization.max_payment_cents,
        max_payments=authorization.remaining_payments,
        authorized_total_cents=authorization.remaining_amount_cents,
        issued_at=authorization.issued_at,
        expires_at=authorization.expires_at,
    )


@router.get("/wallets/{wallet_id}/balance", response_model=schemas.WalletBalanceResponse)
def get_wallet_balance(wallet_id: str, db: DbSession, user: CurrentUser) -> schemas.WalletBalanceResponse:
    wallet = db.get(models.Wallet, wallet_id)
    if wallet is None:
        raise HTTPException(status_code=404, detail="Billetera no encontrada")
    if wallet.user_id != user.id:
        raise HTTPException(status_code=403, detail="Billetera no autorizada")
    now = datetime.now(timezone.utc)
    authorized = int(
        db.query(func.coalesce(func.sum(models.OfflineAuthorization.remaining_amount_cents), 0)).filter(
            models.OfflineAuthorization.wallet_id == wallet.id,
            models.OfflineAuthorization.active.is_(True),
            models.OfflineAuthorization.expires_at > now,
        ).scalar()
    )
    return schemas.WalletBalanceResponse(
        wallet_id=wallet.id,
        confirmed_balance_cents=wallet.confirmed_balance_cents,
        authorized_offline_cents=authorized,
        available_for_authorization_cents=max(wallet.confirmed_balance_cents - authorized, 0),
    )


def _decode_base64(value: str, field: str) -> bytes:
    if "\n" in value or "\r" in value:
        raise HTTPException(status_code=422, detail=f"{field} no admite saltos")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} debe ser Base64 valido") from exc


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HTTPException(status_code=422, detail=f"{field} debe estar en UTC")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field} invalido") from exc
    return parsed


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise HTTPException(status_code=422, detail=f"{field} invalido")
    return value
