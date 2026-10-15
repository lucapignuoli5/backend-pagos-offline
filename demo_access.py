"""One-touch simulated accounts, explicitly enabled only in a demonstration server."""
import os
from decimal import Decimal
from typing import Literal
from uuid import UUID

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import models
from auth import LoginThrottle, create_access_token
from database import get_db
from demo_events import event
from settings import INITIAL_BALANCE_CENTS

router = APIRouter()
throttle = LoginThrottle(maximum_attempts=10, lock_seconds=300)


class DeviceLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installation_id: UUID
    role: Literal["cliente", "comercio"]
    device_secret: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/api/demo/device-login")
def device_login(payload: DeviceLogin, request: Request, db: Session = Depends(get_db)):
    if os.getenv("DEMO_DEVICE_LOGIN_ENABLED", "false").lower() != "true":
        raise HTTPException(404, "Acceso de demostracion deshabilitado")
    bucket = "demo:" + (request.client.host if request.client else "unknown")
    throttle.check(bucket)
    name = f"demo-device-{payload.installation_id}-{payload.role}"
    try:
        # Serialize account creation as well as its wallet; retries never reset funds.
        db.execute(text("BEGIN IMMEDIATE"))
        user = db.scalar(select(models.User).where(models.User.nombre == name))
        if user is None:
            count = db.scalar(select(func.count()).select_from(models.User).where(
                models.User.nombre.like("demo-device-%")))
            if count >= int(os.getenv("DEMO_MAX_DEVICE_ACCOUNTS", "100")):
                raise HTTPException(429, "Limite de cuentas de demostracion alcanzado")
            cents = INITIAL_BALANCE_CENTS if payload.role == "cliente" else 0
            user = models.User(nombre=name, role=payload.role,
                saldo_real=Decimal(cents) / 100,
                password_hash=bcrypt.hashpw(payload.device_secret.encode("ascii"), bcrypt.gensalt()).decode("ascii"))
            db.add(user)
            db.flush()
            db.add(models.Wallet(id=f"wallet-{user.id}", user_id=user.id,
                confirmed_balance_cents=cents, currency="ARS"))
        elif user.role != payload.role or not user.password_hash or not bcrypt.checkpw(
                payload.device_secret.encode("ascii"), user.password_hash.encode("ascii")):
            throttle.fail(bucket)
            raise HTTPException(401, "Identidad de dispositivo invalida")
        db.commit()
    except OperationalError as exc:
        db.rollback()
        raise HTTPException(503, "Acceso temporalmente ocupado; reintentar") from exc
    except Exception:
        db.rollback()
        raise
    throttle.succeed(bucket)
    token, expires_in = create_access_token(user)
    event("LOGIN_OK", usuario_id=user.id, rol=user.role, billetera=f"wallet-{user.id}")
    return dict(access_token=token, token_type="bearer", expires_in=expires_in,
                user_id=user.id, wallet_id=f"wallet-{user.id}", role=user.role)
