"""Aprovisionamiento administrativo explícito; modifica la base configurada al ejecutarse."""
from __future__ import annotations

import argparse
import hashlib
from decimal import Decimal

import bcrypt

import models
from database import SessionLocal


def password_hash(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raw = hashlib.sha256(raw).hexdigest().encode("ascii")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crear o restablecer un usuario del prototipo")
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", required=True, choices=("cliente", "comercio"))
    parser.add_argument("--password", required=True)
    parser.add_argument("--initial-cents", required=True, type=int)
    parser.add_argument("--confirm-database-change", action="store_true", required=True)
    args = parser.parse_args()
    if args.initial_cents < 0:
        parser.error("--initial-cents no puede ser negativo")

    with SessionLocal() as db:
        user = db.query(models.User).filter(models.User.nombre == args.name).one_or_none()
        if user is None:
            user = models.User(
                nombre=args.name, role=args.role,
                saldo_real=Decimal(args.initial_cents) / Decimal("100"),
                password_hash=password_hash(args.password),
            )
            db.add(user)
            db.flush()
            db.add(models.Wallet(
                id=f"wallet-{user.id}", user_id=user.id,
                confirmed_balance_cents=args.initial_cents, currency="ARS",
            ))
        else:
            user.role = args.role
            user.password_hash = password_hash(args.password)
        db.commit()
        print(f"Usuario aprovisionado: id={user.id}, role={user.role}")


if __name__ == "__main__":
    main()
