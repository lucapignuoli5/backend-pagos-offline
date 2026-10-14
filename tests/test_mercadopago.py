import asyncio
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import main
import models
from database import Base


class FakeRequest:
    query_params: dict[str, str] = {}

    async def json(self) -> dict:
        return {"type": "payment", "data": {"id": "provider-payment-1"}}


class FakeMercadoPagoSdk:
    def __init__(self, amount: str = "25.50"):
        self.amount = amount
        self.calls = 0

    def payment(self):
        return self

    def get(self, payment_id: str) -> dict:
        self.calls += 1
        return {
            "status": 200,
            "response": {
                "id": payment_id,
                "status": "approved",
                "external_reference": "cliente-prueba",
                "transaction_amount": self.amount,
            },
        }


class MercadoPagoWebhookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "external-payments.sqlite"
        self.engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = models.User(
            id=10,
            nombre="cliente-prueba",
            saldo_real=Decimal("100.00"),
            password_hash="unused",
            role="cliente",
        )
        self.wallet = models.Wallet(
            id="wallet-10",
            user_id=10,
            confirmed_balance_cents=10_000,
            currency="ARS",
        )
        self.db.add_all([self.user, self.wallet])
        self.db.commit()
        self.previous_sdk = main.mp_sdk
        self.sdk = FakeMercadoPagoSdk()
        main.mp_sdk = self.sdk

    def tearDown(self):
        main.mp_sdk = self.previous_sdk
        self.db.close()
        self.engine.dispose()
        self.directory.cleanup()

    def test_duplicate_webhook_credits_exactly_once(self):
        first = asyncio.run(main.mp_webhook(FakeRequest(), self.db))
        repeated = asyncio.run(main.mp_webhook(FakeRequest(), self.db))

        self.assertEqual(first, {"status": "ok", "result": "applied"})
        self.assertEqual(repeated, {"status": "ok", "result": "duplicate"})
        self.db.expire_all()
        self.assertEqual(Decimal(self.db.get(models.User, 10).saldo_real), Decimal("125.50"))
        self.assertEqual(self.db.get(models.Wallet, "wallet-10").confirmed_balance_cents, 12_550)
        self.assertEqual(self.db.query(models.ExternalPaymentEvent).count(), 1)
        self.assertEqual(self.sdk.calls, 2)

    def test_same_provider_id_with_other_amount_is_conflict(self):
        asyncio.run(main.mp_webhook(FakeRequest(), self.db))
        self.sdk.amount = "30.00"

        with self.assertRaises(HTTPException) as context:
            asyncio.run(main.mp_webhook(FakeRequest(), self.db))

        self.assertEqual(context.exception.status_code, 409)
        self.db.expire_all()
        self.assertEqual(Decimal(self.db.get(models.User, 10).saldo_real), Decimal("125.50"))
        self.assertEqual(self.db.query(models.ExternalPaymentEvent).count(), 1)


if __name__ == "__main__":
    unittest.main()
