from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import uuid

from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
import schemas
from database import Base
from protocol_v2 import (
    encode_public_key,
    encode_signed_envelope,
    payload_digest,
    public_key_fingerprint,
    sign_payload,
)
from sync_v2 import process_evidence


class C2ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.directory.name) / 'c2_reconciliation.sqlite'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        self.client = models.User(id=1, nombre="cliente-c2-rec", saldo_real=Decimal("100.00"), role="cliente")
        self.merchant = models.User(id=2, nombre="comercio-c2-rec", saldo_real=Decimal("0.00"), role="comercio")
        self.client_wallet = models.Wallet(id="wallet-1", user_id=1, confirmed_balance_cents=10_000, currency="ARS")
        self.merchant_wallet = models.Wallet(id="wallet-2", user_id=2, confirmed_balance_cents=0, currency="ARS")
        self.terminal = models.Terminal(
            id="terminal-1", merchant_user_id=2, merchant_id="merchant-2", active=True
        )

        self.pos_private = ec.generate_private_key(ec.SECP256R1())
        self.wallet_private = ec.generate_private_key(ec.SECP256R1())
        self.pos_key = self._registered_key("pos-key-1", self.pos_private, 2, "pos", terminal_id="terminal-1")
        self.wallet_key = self._registered_key(
            "wallet-key-1", self.wallet_private, 1, "wallet", wallet_id="wallet-1"
        )

        # Historical authorization: issued 2026-10-10, expired 2026-10-11
        # Now (2026-10-14) is well after expiration!
        self.authorization = models.OfflineAuthorization(
            id="authorization-hist-1",
            wallet_id="wallet-1",
            wallet_key_id="wallet-key-1",
            max_payment_cents=5_000,
            remaining_amount_cents=10_000,
            remaining_payments=2,
            issued_at=datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
            active=True,
        )

        self.db.add_all([
            self.client, self.merchant,
            self.client_wallet, self.merchant_wallet,
            self.terminal, self.pos_key, self.wallet_key,
            self.authorization,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.directory.cleanup()

    def _registered_key(self, key_id, private_key, owner_user_id, purpose, wallet_id=None, terminal_id=None):
        b64 = encode_public_key(private_key.public_key())
        der = base64.b64decode(b64)
        return models.RegisteredKey(
            key_id=key_id,
            owner_user_id=owner_user_id,
            purpose=purpose,
            wallet_id=wallet_id,
            terminal_id=terminal_id,
            public_key_b64=b64,
            fingerprint=public_key_fingerprint(der),
            proof_nonce=f"nonce-{key_id}",
            revoked=False,
        )

    def _create_evidence(self, op_id, amount_cents=1500, issued_str="2026-10-10T12:00:00Z", expires_str="2026-10-10T12:01:00Z", with_ack=True):
        nonce = base64.urlsafe_b64encode(uuid.UUID(op_id).bytes).decode().rstrip("=")
        request_payload = {
            "version": 2,
            "type": "payment_request",
            "operation_id": op_id,
            "merchant_id": "merchant-2",
            "terminal_id": "terminal-1",
            "pos_key_id": "pos-key-1",
            "pos_key_fingerprint": self.pos_key.fingerprint,
            "amount_cents": amount_cents,
            "currency": "ARS",
            "nonce": nonce,
            "issued_at": issued_str,
            "expires_at": expires_str,
        }
        request_sig = sign_payload(request_payload, self.pos_private)
        request_wire = encode_signed_envelope(request_payload, request_sig)

        receipt_payload = {
            "version": 2,
            "type": "payment_receipt",
            "operation_id": op_id,
            "wallet_id": "wallet-1",
            "wallet_key_id": "wallet-key-1",
            "wallet_key_fingerprint": self.wallet_key.fingerprint,
            "offline_authorization_id": self.authorization.id,
            "merchant_id": "merchant-2",
            "terminal_id": "terminal-1",
            "amount_cents": amount_cents,
            "currency": "ARS",
            "nonce": nonce,
            "issued_at": issued_str,
            "expires_at": expires_str,
            "request_digest": payload_digest(request_payload),
        }
        receipt_sig = sign_payload(receipt_payload, self.wallet_private)
        receipt_wire = encode_signed_envelope(receipt_payload, receipt_sig)

        ack_wire = None
        if with_ack:
            ack_payload = {
                "version": 2,
                "type": "payment_ack",
                "operation_id": op_id,
                "merchant_id": "merchant-2",
                "terminal_id": "terminal-1",
                "pos_key_id": "pos-key-1",
                "pos_key_fingerprint": self.pos_key.fingerprint,
                "wallet_id": "wallet-1",
                "offline_authorization_id": self.authorization.id,
                "amount_cents": amount_cents,
                "currency": "ARS",
                "nonce": nonce,
                "issued_at": issued_str,
                "expires_at": expires_str,
                "receipt_digest": payload_digest(receipt_payload),
                "accepted_at": "2026-10-10T12:00:30Z",
                "status": "LOCALLY_ACCEPTED",
            }
            ack_sig = sign_payload(ack_payload, self.pos_private)
            ack_wire = encode_signed_envelope(ack_payload, ack_sig)

        return schemas.OfflinePaymentEvidence(
            operation_id=op_id,
            request_envelope_b64=base64.b64encode(request_wire).decode("ascii"),
            receipt_envelope_b64=base64.b64encode(receipt_wire).decode("ascii"),
            ack_envelope_b64=base64.b64encode(ack_wire).decode("ascii") if ack_wire else None,
        )

    def test_late_reconciliation_applies_when_sync_occurs_after_authorization_expires(self):
        # The authorization expired 2026-10-11. Payment was issued 2026-10-10 within authorization.
        # Now is 2026-10-14+. Reconciliation must succeed (R04).
        evidence = self._create_evidence("00000000-0000-4000-8000-000000000001", amount_cents=2_500)
        res = process_evidence(self.db, self.client, evidence)
        self.assertEqual(res.status, "ACCEPTED")

        self.db.expire_all()
        # Verify balances were debited/credited
        wallet = self.db.get(models.Wallet, "wallet-1")
        m_wallet = self.db.get(models.Wallet, "wallet-2")
        self.assertEqual(wallet.confirmed_balance_cents, 7_500)
        self.assertEqual(m_wallet.confirmed_balance_cents, 2_500)

        # Verify authorization remaining amounts
        auth_row = self.db.get(models.OfflineAuthorization, self.authorization.id)
        self.assertEqual(auth_row.remaining_amount_cents, 7_500)
        self.assertEqual(auth_row.remaining_payments, 1)

    def test_resubmission_of_accepted_payment_is_idempotent_and_stable_even_after_revocation(self):
        evidence = self._create_evidence("00000000-0000-4000-8000-000000000002", amount_cents=1_000)
        res1 = process_evidence(self.db, self.client, evidence)
        self.assertEqual(res1.status, "ACCEPTED")

        # Now revoke the wallet key!
        self.wallet_key.revoked = True
        self.db.commit()

        # Resubmission by client must return ACCEPTED stably without error or duplicate debit
        res2 = process_evidence(self.db, self.client, evidence)
        self.assertEqual(res2.status, "ACCEPTED")

        # Resubmission by merchant must also return ACCEPTED stably
        res3 = process_evidence(self.db, self.merchant, evidence)
        self.assertEqual(res3.status, "ACCEPTED")

        self.db.expire_all()
        wallet = self.db.get(models.Wallet, "wallet-1")
        # 10,000 - 1,000 = 9,000 (only debited once!)
        self.assertEqual(wallet.confirmed_balance_cents, 9_000)

        # Ledger entries count for this operation is exactly 2 (1 DEBIT, 1 CREDIT)
        ledger_count = self.db.query(models.LedgerEntry).filter_by(
            operation_id="00000000-0000-4000-8000-000000000002"
        ).count()
        self.assertEqual(ledger_count, 2)

    def test_progressive_submission_pending_then_accepted_is_stable(self):
        op_id = "00000000-0000-4000-8000-000000000003"
        evidence_with_ack = self._create_evidence(op_id, amount_cents=1_200, with_ack=True)
        evidence_no_ack = evidence_with_ack.model_copy(update={"ack_envelope_b64": None})

        # First submission without ack
        r1 = process_evidence(self.db, self.client, evidence_no_ack)
        self.assertEqual(r1.status, "PENDING_EVIDENCE")

        # Repeat submission without ack: stable PENDING_EVIDENCE
        r2 = process_evidence(self.db, self.merchant, evidence_no_ack)
        self.assertEqual(r2.status, "PENDING_EVIDENCE")

        # Now submit with ack
        r3 = process_evidence(self.db, self.merchant, evidence_with_ack)
        self.assertEqual(r3.status, "ACCEPTED")

        # Repeat submission with ack: stable ACCEPTED
        r4 = process_evidence(self.db, self.client, evidence_with_ack)
        self.assertEqual(r4.status, "ACCEPTED")
