import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

import models
from database import Base
from migrations import backfill_wallets, run_schema_migrations


class MigrationTests(unittest.TestCase):
    def test_legacy_user_and_balance_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.sqlite"
            engine = create_engine(f"sqlite:///{database_path}")
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE users ("
                        "id INTEGER PRIMARY KEY, nombre VARCHAR(120) NOT NULL, "
                        "saldo_real NUMERIC(12, 2) NOT NULL, password_hash VARCHAR)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO users (id, nombre, saldo_real, password_hash) "
                        "VALUES (7, 'usuario-heredado', 123.45, NULL)"
                    )
                )

            run_schema_migrations(engine)
            Base.metadata.create_all(engine)
            with Session(engine) as session:
                self.assertEqual(backfill_wallets(session), 1)
                user = session.get(models.User, 7)
                wallet = session.get(models.Wallet, "wallet-7")
                self.assertEqual(user.nombre, "usuario-heredado")
                self.assertEqual(Decimal(user.saldo_real), Decimal("123.45"))
                self.assertEqual(user.role, "cliente")
                self.assertEqual(wallet.confirmed_balance_cents, 12_345)
                self.assertEqual(backfill_wallets(session), 0)

            columns = {column["name"] for column in inspect(engine).get_columns("users")}
            self.assertIn("role", columns)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
