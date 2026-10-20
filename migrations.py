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
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS legacy_evidence_inventory ("
            "operation_id VARCHAR(36) NOT NULL PRIMARY KEY, wallet_id VARCHAR(120) NOT NULL, "
            "authorization_id VARCHAR(120) NOT NULL, receipt_digest VARCHAR(64) NOT NULL, "
            "imported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(wallet_id) REFERENCES wallets(id), "
            "FOREIGN KEY(authorization_id) REFERENCES offline_authorizations(id))"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_legacy_inventory_wallet_id ON legacy_evidence_inventory(wallet_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_legacy_inventory_authorization_id ON legacy_evidence_inventory(authorization_id)"
        ))
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" not in user_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'cliente'")
            )
    inspector = inspect(engine)
    if "registered_keys" in inspector.get_table_names():
        key_columns = {column["name"] for column in inspector.get_columns("registered_keys")}
        if "revoked_at" not in key_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE registered_keys ADD COLUMN revoked_at DATETIME"))
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
    inspector = inspect(engine)
    if "offline_commitments" in inspector.get_table_names():
        commitment_columns = {column["name"] for column in inspector.get_columns("offline_commitments")}
        additions = {
            "held_cents": "INTEGER NOT NULL DEFAULT 0",
            "released_unissued_cents": "INTEGER NOT NULL DEFAULT 0",
            "released_rejected_cents": "INTEGER NOT NULL DEFAULT 0",
            "phase": "VARCHAR(20) NOT NULL DEFAULT 'OPEN'",
            "closure_envelope": "BLOB",
            "closure_manifest": "BLOB",
            "manifest_digest": "VARCHAR(64)",
        }
        with engine.begin() as connection:
            for name, declaration in additions.items():
                if name not in commitment_columns:
                    connection.execute(text(
                        f"ALTER TABLE offline_commitments ADD COLUMN {name} {declaration}"
                    ))
            connection.execute(text(
                "UPDATE offline_commitments SET held_cents = "
                "CASE WHEN held_cents = 0 AND reserved_cents >= emitted_cents "
                "AND released_unissued_cents = 0 AND released_rejected_cents = 0 "
                "THEN reserved_cents - emitted_cents ELSE held_cents END"
            ))
            connection.execute(text(
                "UPDATE offline_commitments SET phase = CASE WHEN closed = 1 "
                "AND phase != 'SETTLED' THEN 'SEALED' "
                "WHEN closed = 0 AND phase != 'SETTLED' THEN 'OPEN' ELSE phase END"
            ))
            # Older closures did not persist signed closure evidence. Keep their
            # unresolved amount held and require explicit accounting review.
            connection.execute(text(
                "UPDATE wallets SET offline_review_required = 1 WHERE id IN ("
                "SELECT wallet_id FROM offline_commitments "
                "WHERE closed = 1 AND held_cents > 0 AND closure_envelope IS NULL)"
            ))

    inspector = inspect(engine)
    if {"offline_authorizations", "offline_commitments", "offline_payments_v2"}.issubset(
        set(inspector.get_table_names())
    ):
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS offline_commitment_claims ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "authorization_id VARCHAR(120) NOT NULL, operation_id VARCHAR(36) NOT NULL, "
                "issuance_index INTEGER NOT NULL CHECK (issuance_index > 0), "
                "amount_cents INTEGER NOT NULL CHECK (amount_cents > 0), "
                "receipt_digest VARCHAR(64) NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "CONSTRAINT uq_commitment_claim_operation UNIQUE (authorization_id, operation_id), "
                "FOREIGN KEY(authorization_id) REFERENCES offline_authorizations(id))"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_offline_commitment_claims_authorization_id "
                "ON offline_commitment_claims(authorization_id)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_offline_commitment_claims_operation_id "
                "ON offline_commitment_claims(operation_id)"
            ))
        _backfill_commitment_claims(engine)


def _backfill_commitment_claims(engine: Engine) -> None:
    """Preserve parseable historical v3 receipts as claims; flag any ambiguity."""
    from protocol_v3 import parse_signed_envelope, payload_digest

    with engine.begin() as connection:
        rows = connection.execute(text(
            "SELECT p.operation_id, p.authorization_id, p.wallet_id, p.amount_cents, "
            "p.receipt_envelope FROM offline_payments_v2 p "
            "JOIN offline_commitments c ON c.authorization_id = p.authorization_id "
            "WHERE NOT EXISTS (SELECT 1 FROM offline_commitment_claims cc "
            "WHERE cc.authorization_id = p.authorization_id AND cc.operation_id = p.operation_id)"
        )).mappings().all()
        for row in rows:
            try:
                receipt = parse_signed_envelope(bytes(row["receipt_envelope"]))
                payload = receipt.payload
                if (payload.get("operation_id") != row["operation_id"]
                        or payload.get("offline_authorization_id") != row["authorization_id"]
                        or payload.get("wallet_id") != row["wallet_id"]
                        or payload.get("amount_cents") != row["amount_cents"]):
                    raise ValueError("receipt does not match persisted payment")
                connection.execute(text(
                    "INSERT OR IGNORE INTO offline_commitment_claims "
                    "(authorization_id, operation_id, issuance_index, amount_cents, receipt_digest) "
                    "VALUES (:authorization_id, :operation_id, :issuance_index, :amount_cents, :receipt_digest)"
                ), {
                    "authorization_id": row["authorization_id"],
                    "operation_id": row["operation_id"],
                    "issuance_index": int(payload["issuance_index"]),
                    "amount_cents": int(payload["amount_cents"]),
                    "receipt_digest": payload_digest(receipt),
                })
            except Exception:
                connection.execute(text(
                    "UPDATE wallets SET offline_review_required = 1 WHERE id = :wallet_id"
                ), {"wallet_id": row["wallet_id"]})


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
