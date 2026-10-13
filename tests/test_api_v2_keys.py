import base64
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
import schemas
from api_v2 import create_offline_authorization, get_wallet_balance, register_key
from database import Base
from protocol_v2 import canonical_bytes, encode_public_key, public_key_fingerprint


class KeyAndAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "api.sqlite"
        self.engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.client_user = models.User(
            id=1,
            nombre="cliente",
            saldo_real=Decimal("10000.00"),
            password_hash="unused",
            role="cliente",
        )
        self.other_user = models.User(
            id=2,
            nombre="otro",
            saldo_real=Decimal("10000.00"),
            password_hash="unused",
            role="cliente",
        )
        self.wallet = models.Wallet(
            id="wallet-1", user_id=1, confirmed_balance_cents=1_000_000, currency="ARS"
        )
        self.db.add_all([self.client_user, self.other_user, self.wallet])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.directory.cleanup()

    def test_registers_p256_key_with_proof_and_is_idempotent(self):
        request = self._key_request("wallet-key-1", "wallet", "wallet-1")
        created = register_key(request, self.db, self.client_user)
        repeated = register_key(request, self.db, self.client_user)
        self.assertTrue(created.created)
        self.assertFalse(repeated.created)
        stored = self.db.get(models.RegisteredKey, "wallet-key-1")
        self.assertEqual(stored.wallet_id, "wallet-1")

    def test_authorization_respects_limits_and_ownership(self):
        register_key(self._key_request("wallet-key-1", "wallet", "wallet-1"), self.db, self.client_user)
        authorization = create_offline_authorization(
            schemas.OfflineAuthorizationRequest(
                wallet_id="wallet-1",
                wallet_key_id="wallet-key-1",
                max_payment_cents=100_000,
                max_payments=10,
            ),
            self.db,
            self.client_user,
        )
        self.assertEqual(authorization.authorized_total_cents, 1_000_000)
        with self.assertRaises(HTTPException) as context:
            create_offline_authorization(
                schemas.OfflineAuthorizationRequest(
                    wallet_id="wallet-1",
                    wallet_key_id="wallet-key-1",
                    max_payment_cents=100_000,
                    max_payments=1,
                ),
                self.db,
                self.client_user,
            )
        self.assertEqual(context.exception.status_code, 409)
        with self.assertRaises(HTTPException) as forbidden:
            get_wallet_balance("wallet-1", self.db, self.other_user)
        self.assertEqual(forbidden.exception.status_code, 403)

    def _key_request(self, key_id: str, purpose: str, scope_id: str) -> schemas.KeyRegistrationRequest:
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key_b64 = encode_public_key(private_key.public_key())
        fingerprint = public_key_fingerprint(base64.b64decode(public_key_b64))
        payload = {
            "version": 2,
            "type": "key_registration",
            "key_id": key_id,
            "purpose": purpose,
            "owner_user_id": self.client_user.id,
            "scope_id": scope_id,
            "fingerprint": fingerprint,
            "nonce": "registration-nonce-unique",
            "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        payload_bytes = canonical_bytes(payload)
        signature = private_key.sign(payload_bytes, ec.ECDSA(hashes.SHA256()))
        return schemas.KeyRegistrationRequest(
            public_key_b64=public_key_b64,
            proof_payload_b64=base64.b64encode(payload_bytes).decode("ascii"),
            proof_signature_b64=base64.b64encode(signature).decode("ascii"),
        )


if __name__ == "__main__":
    unittest.main()
