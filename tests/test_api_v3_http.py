import tempfile
import unittest
import base64
import os
from unittest.mock import patch
from types import SimpleNamespace
from decimal import Decimal
from pathlib import Path
import base64
import os
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import ec

import api_v3
import auth
import models
from database import Base, get_db
from protocol_v3 import encode_public_key, encode_signed_envelope, sign_payload, payload_digest, public_key_fingerprint
from protocol_v3 import encode_public_key, encode_signed_envelope, sign_payload


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

    def test_signed_close_uses_wallet_key_over_http(self):
        directory = tempfile.TemporaryDirectory(); engine = create_engine(f"sqlite:///{Path(directory.name) / 'close.sqlite'}", connect_args={"check_same_thread": False}); Base.metadata.create_all(engine)
        issuer = ec.generate_private_key(ec.SECP256R1()); wallet_key = ec.generate_private_key(ec.SECP256R1())
        issuer_pub, wallet_pub = encode_public_key(issuer.public_key()), encode_public_key(wallet_key.public_key())
        grant = {"version":3,"type":"offline_authorization","authorization_id":"auth-1","wallet_id":"wallet-1","wallet_key_id":"wallet-key-1","wallet_key_fingerprint":public_key_fingerprint(base64.b64decode(wallet_pub)),"wallet_public_key_b64":wallet_pub,"currency":"ARS","max_payment_cents":100,"max_payments":10,"authorized_total_cents":1000,"max_request_lifetime_seconds":120,"issued_at":"2026-10-14T00:00:00Z","spend_expires_at":"2026-10-15T00:00:00Z","issuer_key_id":"issuer-test","issuer_key_fingerprint":public_key_fingerprint(base64.b64decode(issuer_pub))}
        grant_wire = encode_signed_envelope(grant, sign_payload(grant, issuer)); close = {"version":3,"type":"offline_authorization_close","closure_id":"11111111-1111-4111-8111-111111111111","authorization_id":"auth-1","wallet_id":"wallet-1","wallet_key_id":"wallet-key-1","wallet_key_fingerprint":grant["wallet_key_fingerprint"],"authorization_digest":payload_digest(grant),"final_issuance_index":0,"emitted_total_cents":0,"manifest_digest":payload_digest(b"[]"),"issued_at":"2026-10-14T00:00:00Z"}; close_wire = encode_signed_envelope(close, sign_payload(close, wallet_key))
        with Session(engine) as db: db.add_all([models.User(id=1,nombre="c",saldo_real=Decimal("10"),role="cliente"),models.Wallet(id="wallet-1",user_id=1,confirmed_balance_cents=1000,currency="ARS"),models.OfflineCommitment(authorization_id="auth-1",wallet_id="wallet-1",reserved_cents=1000,authorization_envelope=grant_wire)]); db.commit()
        app = FastAPI(); app.include_router(api_v3.router)
        def override_db():
            with Session(engine) as session: yield session
        app.dependency_overrides[get_db] = override_db; app.dependency_overrides[auth.get_current_user] = lambda: SimpleNamespace(id=1)
        fake = SimpleNamespace(public_key_b64=issuer_pub,key_id="issuer-test")
        with patch.dict(os.environ,{"ISSUER_KEY_PATH":"external","ISSUER_KEY_FINGERPRINT":grant["issuer_key_fingerprint"]}), patch.object(api_v3.IssuerIdentity,"load_external",return_value=fake), TestClient(app) as client: response = client.post("/api/v3/offline-authorizations/auth-1/close",json={"close_envelope_b64":base64.b64encode(close_wire).decode(),"manifest_b64":base64.b64encode(b"[]").decode()})
        self.assertEqual(response.status_code,200,response.text); engine.dispose(); directory.cleanup()

    def test_signed_resolution_is_idempotent_over_http(self):
        directory = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(directory.name) / 'resolution.sqlite'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        app = FastAPI(); app.include_router(api_v3.router)
        def override_db():
            with Session(engine) as session: yield session
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[auth.get_current_user] = lambda: SimpleNamespace(id=1)
        private = ec.generate_private_key(ec.SECP256R1())
        public = encode_public_key(private.public_key())
        fake = SimpleNamespace(public_key_b64=public, key_id="issuer-test")
        payload = {"version": 3, "type": "payment_resolution", "operation_id": "11111111-1111-4111-8111-111111111111",
                   "wallet_id": "wallet-1", "merchant_id": "merchant-1", "terminal_id": "terminal-1",
                   "amount_cents": 100, "currency": "ARS", "offline_authorization_id": "auth-1",
                   "authorization_digest": "a" * 64, "request_digest": "b" * 64, "receipt_digest": "c" * 64,
                   "operation_status": "ACCEPTED", "code": "OK", "resolution_revision": 1,
                   "resolved_at": "2026-10-14T00:00:00Z", "issuer_key_id": "issuer-test", "issuer_key_fingerprint": "d" * 64}
        wire = encode_signed_envelope(payload, sign_payload(payload, private))
        encoded = base64.b64encode(wire).decode()
        with patch.dict(os.environ, {"ISSUER_KEY_PATH": "external", "ISSUER_KEY_FINGERPRINT": "d" * 64}), patch.object(api_v3.IssuerIdentity, "load_external", return_value=fake), TestClient(app) as client:
            first = client.post("/api/v3/offline-payments/11111111-1111-4111-8111-111111111111/resolution", json={"resolution_envelope_b64": encoded})
            second = client.post("/api/v3/offline-payments/11111111-1111-4111-8111-111111111111/resolution", json={"resolution_envelope_b64": encoded})
        self.assertEqual(first.status_code, 200, first.text); self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()["final"])
        engine.dispose()
        directory.cleanup()


if __name__ == "__main__":
    unittest.main()
