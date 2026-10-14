import tempfile
import unittest
from types import SimpleNamespace
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import api_v3
import auth
import models
from database import Base, get_db


class ApiV3HttpTests(unittest.TestCase):
    def test_commitment_query_requires_authenticated_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'http.sqlite'}")
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                user = models.User(id=1, nombre="cliente", saldo_real=Decimal("10"), role="cliente")
                db.add_all([user, models.Wallet(id="wallet-1", user_id=1, confirmed_balance_cents=1000, currency="ARS"),
                            models.OfflineCommitment(authorization_id="auth-1", wallet_id="wallet-1", reserved_cents=1000)])
                db.commit()
            app = FastAPI()
            app.include_router(api_v3.router)
            def override_db():
                with Session(engine) as session:
                    yield session
            app.dependency_overrides[get_db] = override_db
            app.dependency_overrides[auth.get_current_user] = lambda: SimpleNamespace(id=1)
            with TestClient(app) as client:
                response = client.get("/api/v3/offline-authorizations/auth-1/commitment")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["reserved_cents"], 1000)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
