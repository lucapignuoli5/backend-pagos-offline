import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from database import Base


class ApiV3PersistenceTests(unittest.TestCase):
    def test_commitment_emission_is_unique_per_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'v3.sqlite'}")
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                db.add(models.User(id=1, nombre="c", saldo_real=0, role="cliente"))
                db.add(models.Wallet(id="wallet-1", user_id=1, confirmed_balance_cents=1000, currency="ARS"))
                db.add(models.OfflineAuthorization(id="auth-1", wallet_id="wallet-1", wallet_key_id="key-1",
                    max_payment_cents=100, remaining_amount_cents=1000, remaining_payments=10,
                    issued_at=datetime(2026, 10, 14, tzinfo=timezone.utc), expires_at=datetime(2026, 10, 15, tzinfo=timezone.utc), active=True))
                db.add(models.OfflineCommitment(authorization_id="auth-1", wallet_id="wallet-1", reserved_cents=1000))
                db.commit()
                db.add(models.CommitmentEmission(authorization_id="auth-1", operation_id="op-1", amount_cents=100))
                db.commit()
                db.add(models.CommitmentEmission(authorization_id="auth-1", operation_id="op-1", amount_cents=100))
                with self.assertRaises(IntegrityError):
                    db.commit()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
