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
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS simulated_topups ("
            "request_id VARCHAR(120) NOT NULL PRIMARY KEY, "
            "wallet_id VARCHAR(120) NOT NULL, user_id INTEGER NOT NULL, "
            "amount_cents INTEGER NOT NULL CHECK (amount_cents > 0), "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(wallet_id) REFERENCES wallets(id), "
            "FOREIGN KEY(user_id) REFERENCES users(id))"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_simulated_topups_wallet_id ON simulated_topups(wallet_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_simulated_topups_user_id ON simulated_topups(user_id)"
        ))
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS external_topup_orders ("
            "id VARCHAR(36) NOT NULL PRIMARY KEY, wallet_id VARCHAR(120) NOT NULL, "
            "user_id INTEGER NOT NULL, amount_cents INTEGER NOT NULL CHECK (amount_cents > 0), "
            "currency VARCHAR(3) NOT NULL DEFAULT 'ARS', status VARCHAR(30) NOT NULL DEFAULT 'PENDING', "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(wallet_id) REFERENCES wallets(id), FOREIGN KEY(user_id) REFERENCES users(id))"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_external_topup_orders_wallet_id ON external_topup_orders(wallet_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_external_topup_orders_user_id ON external_topup_orders(user_id)"
        ))
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" not in user_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'cliente'")
            )
    inspector = inspect(engine)
    if "wallets" in inspector.get_table_names():
        wallet_columns = {column["name"] for column in inspector.get_columns("wallets")}
        if "offline_review_required" not in wallet_columns:
            with engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE wallets ADD COLUMN offline_review_required BOOLEAN NOT NULL DEFAULT 0"
                ))
    inspector = inspect(engine)
    if "terminals" in inspector.get_table_names():
        terminal_columns = {column["name"] for column in inspector.get_columns("terminals")}
        if "merchant_id" not in terminal_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE terminals ADD COLUMN merchant_id VARCHAR(120)"))
                connection.execute(
                    text("UPDATE terminals SET merchant_id = 'merchant-' || merchant_user_id WHERE merchant_id IS NULL")
                )
    inspector = inspect(engine)
    if "offline_commitment_emissions" in inspector.get_table_names():
        emission_columns = {column["name"] for column in inspector.get_columns("offline_commitment_emissions")}
        if "issuance_index" not in emission_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE offline_commitment_emissions ADD COLUMN issuance_index INTEGER"))
                connection.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commitment_issuance_index "
                    "ON offline_commitment_emissions(authorization_id, issuance_index) "
                    "WHERE issuance_index IS NOT NULL"
                ))
    inspector = inspect(engine)
    if "offline_authorizations" in inspector.get_table_names():
        authorization_columns = {column["name"] for column in inspector.get_columns("offline_authorizations")}
        if "issuance_request_id" not in authorization_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE offline_authorizations ADD COLUMN issuance_request_id VARCHAR(120)"))
                connection.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_offline_authorization_issuance_request "
                    "ON offline_authorizations(issuance_request_id) WHERE issuance_request_id IS NOT NULL"
                ))


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
