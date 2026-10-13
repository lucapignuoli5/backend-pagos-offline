"""Migraciones incrementales seguras para las bases SQLite heredadas."""

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

import models


def run_schema_migrations(engine: Engine) -> None:
    """Agrega columnas compatibles antes de que SQLAlchemy use los modelos nuevos."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" not in user_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'cliente'")
            )


def backfill_wallets(db: Session) -> int:
    """Crea una billetera v2 por usuario sin modificar el saldo heredado."""
    created = 0
    for user in db.query(models.User).order_by(models.User.id).all():
        existing = db.query(models.Wallet).filter(models.Wallet.user_id == user.id).first()
        if existing is not None:
            continue
        cents = int(
            (Decimal(user.saldo_real) * Decimal("100")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        db.add(
            models.Wallet(
                id=f"wallet-{user.id}",
                user_id=user.id,
                confirmed_balance_cents=max(cents, 0),
                currency="ARS",
            )
        )
        created += 1
    db.commit()
    return created
