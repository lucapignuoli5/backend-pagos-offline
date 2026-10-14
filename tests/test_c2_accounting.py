from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import threading
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

import auth
import crypto_utils
import main
import models
import schemas
from api_v2 import create_offline_authorization, get_wallet_balance
from database import Base
from protocol_v2 import encode_signed_envelope, sign_payload
from sync_v2 import process_evidence


class C2AccountingAndRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.directory.name) / 'c2_test.sqlite'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        self.client_user = models.User(
            id=1,
            nombre="cliente-c2",
            saldo_real=Decimal("100.00"),
            password_hash=main.hash_password("password-c2"),
            role="cliente",
        )
        self.client_wallet = models.Wallet(
            id="wallet-1",
            user_id=1,
            confirmed_balance_cents=10_000,
            currency="ARS",
        )
        self.merchant_user = models.User(
            id=2,
            nombre="comercio-c2",
            saldo_real=Decimal("0.00"),
            password_hash=main.hash_password("password-comercio"),
            role="comercio",
        )
        self.merchant_wallet = models.Wallet(
            id="wallet-2",
            user_id=2,
            confirmed_balance_cents=0,
            currency="ARS",
        )
        self.terminal = models.Terminal(
            id="terminal-c2",
            merchant_user_id=2,
            merchant_id="merchant-2",
            active=True,
        )
        self.db.add_all([
            self.client_user, self.client_wallet,
            self.merchant_user, self.merchant_wallet,
            self.terminal,
        ])
        self.db.commit()

        self.prev_jwt = main.JWT_SECRET_KEY
        main.JWT_SECRET_KEY = "test-secret-with-sufficient-length-for-jwt"
        auth.JWT_SECRET_KEY = main.JWT_SECRET_KEY
        main.LOGIN_THROTTLE = auth.LoginThrottle(maximum_attempts=20, lock_seconds=300)

    def tearDown(self):
        main.JWT_SECRET_KEY = self.prev_jwt
        auth.JWT_SECRET_KEY = self.prev_jwt
        self.db.close()
        self.engine.dispose()
        self.directory.cleanup()

    def test_verify_payment_contract_signature_supports_pem_and_der_and_kwarg_names(self):
        key = ec.generate_private_key(ec.SECP256R1())
        pem_public = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        der_b64_public = base64.b64encode(
            key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).decode("ascii")

        payload = '{"test":"payload"}'
        sig_bytes = key.sign(payload.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
        sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

        # Call with schemas.SignatureVerificationRequest kwarg names
        self.assertTrue(crypto_utils.verify_payment_contract_signature(
            contract_json=payload,
            signature=sig_b64,
            public_key_pem=pem_public,
        ))
        # Call with DER base64
        self.assertTrue(crypto_utils.verify_payment_contract_signature(
            payload_str=payload,
            signature_b64=sig_b64,
            public_key_b64=der_b64_public,
        ))
        # Tampered signature or payload fails cleanly
        self.assertFalse(crypto_utils.verify_payment_contract_signature(
            contract_json='{"tampered":true}',
            signature=sig_b64,
            public_key_pem=pem_public,
        ))
        # Integration with main.verify_signature endpoint
        res = main.verify_signature(schemas.SignatureVerificationRequest(
            contract_json=payload,
            firma=sig_b64,
            llave_publica_pem=pem_public,
        ))
        self.assertTrue(res.valid)

    def test_passwords_longer_than_72_bytes_do_not_silently_collide(self):
        long_pwd_a = "A" * 72 + "extra1"
        long_pwd_b = "A" * 72 + "extra2"

        hash_a = main.hash_password(long_pwd_a)
        self.assertTrue(main.verify_password(long_pwd_a, hash_a))
        # In raw bcrypt without pre-hash, long_pwd_b would match hash_a due to 72-byte truncation!
        self.assertFalse(main.verify_password(long_pwd_b, hash_a))

    def test_login_supports_wallet_and_merchant_aliases(self):
        req = Request({"type": "http", "client": ("127.0.0.1", 1234)})

        # Login with wallet alias
        res_wallet = main.login_usuario(
            schemas.LoginRequest(usuario="wallet-1", password="password-c2"),
            req,
            self.db,
        )
        self.assertEqual(res_wallet["user_id"], 1)

        # Login with merchant alias
        res_merch = main.login_usuario(
            schemas.LoginRequest(usuario="merchant-2", password="password-comercio"),
            req,
            self.db,
        )
        self.assertEqual(res_merch["user_id"], 2)

        # Login with terminal alias
        res_term = main.login_usuario(
            schemas.LoginRequest(usuario="terminal-c2", password="password-comercio"),
            req,
            self.db,
        )
        self.assertEqual(res_term["user_id"], 2)

    def test_concurrent_recargas_update_both_wallet_and_user_without_loss(self):
        rounds = 10
        increment_pesos = 10
        total_increment = rounds * increment_pesos

        def do_recarga():
            with Session(self.engine) as session:
                main.recargar_saldo(
                    schemas.RecargaRequest(
                        token_id="wallet-1",
                        monto_recarga=increment_pesos,
                    ),
                    session,
                )

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(do_recarga) for _ in range(rounds)]
            for f in futures:
                f.result()

        self.db.expire_all()
        user = self.db.get(models.User, 1)
        wallet = self.db.get(models.Wallet, "wallet-1")

        expected_saldo = Decimal("100.00") + Decimal(str(total_increment))
        expected_cents = 10_000 + (total_increment * 100)

        self.assertEqual(user.saldo_real, expected_saldo)
        self.assertEqual(wallet.confirmed_balance_cents, expected_cents)
        self.assertEqual(int(user.saldo_real * Decimal("100")), wallet.confirmed_balance_cents)

    def test_concurrent_authorization_emissions_never_overallocate(self):
        # Register a wallet key first
        w_priv = ec.generate_private_key(ec.SECP256R1())
        der = w_priv.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        b64 = base64.b64encode(der).decode("ascii")
        key = models.RegisteredKey(
            key_id="wallet-key-c2",
            owner_user_id=1,
            purpose="wallet",
            wallet_id="wallet-1",
            public_key_b64=b64,
            fingerprint=crypto_utils.verify_payment_contract_signature.__module__,  # dummy string
            proof_nonce="nonce-1234567890123456",
            revoked=False,
        )
        self.db.add(key)
        self.db.commit()

        # Balance is 10,000 cents (or 20,000 after previous test, let's reset to 10,000)
        self.client_wallet.confirmed_balance_cents = 10_000
        self.db.commit()

        # We request 6,000 cents (1 payment of 6,000 cents). Only 1 should succeed, the 2nd must get 409!
        results = []
        errors = []

        def request_auth():
            with Session(self.engine) as session:
                try:
                    res = create_offline_authorization(
                        schemas.OfflineAuthorizationRequest(
                            wallet_id="wallet-1",
                            wallet_key_id="wallet-key-c2",
                            max_payment_cents=6_000,
                            max_payments=1,
                        ),
                        session,
                        self.client_user,
                    )
                    results.append(res)
                except HTTPException as e:
                    errors.append(e.status_code)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(request_auth) for _ in range(4)]
            for f in futures:
                f.result()

        # Exactly 1 can succeed because balance is 10,000 and each requests 6,000
        # The remaining 3 must receive HTTP 409 or return existing if idempotent
        # If identical request, it returns existing authorization
        # Let's verify total committed does not exceed 10,000 cents
        unique_auths = {r.authorization_id: r.authorized_total_cents for r in results}
        total_auth = sum(unique_auths.values())
        self.assertLessEqual(total_auth, 10_000)
