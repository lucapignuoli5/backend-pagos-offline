import base64
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import models
import schemas
from database import Base
from protocol_v2 import (
    encode_public_key,
    encode_signed_envelope,
    parse_signed_envelope,
    payload_digest,
    public_key_fingerprint,
    sign_payload,
)
from sync_v2 import process_evidence, sync_offline_payments_v2


class SyncV2Tests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "sync.sqlite"
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.client = models.User(id=1, nombre="cliente", saldo_real=Decimal("100.00"), role="cliente")
        self.merchant = models.User(id=2, nombre="comercio", saldo_real=Decimal("0.00"), role="comercio")
        self.outsider = models.User(id=3, nombre="otro", saldo_real=Decimal("0.00"), role="cliente")
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
        self.authorization = models.OfflineAuthorization(
            id="authorization-1",
            wallet_id="wallet-1",
            wallet_key_id="wallet-key-1",
            max_payment_cents=10_000,
            remaining_amount_cents=10_000,
            remaining_payments=10,
            issued_at=datetime(2026, 10, 13, 14, 59, tzinfo=timezone.utc),
            expires_at=datetime(2026, 10, 14, 14, 59, tzinfo=timezone.utc),
            active=True,
        )
        self.db.add_all(
            [
                self.client,
                self.merchant,
                self.outsider,
                self.client_wallet,
                self.merchant_wallet,
                self.terminal,
                self.pos_key,
                self.wallet_key,
                self.authorization,
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.directory.cleanup()

    def test_pending_evidence_then_ack_applies_once(self):
        pending, completed = self._evidence("123e4567-e89b-42d3-a456-426614174001", 4_000)
        result = process_evidence(self.db, self.client, pending)
        self.assertEqual(result.status, "PENDING_EVIDENCE")
        self.db.refresh(self.client_wallet)
        self.assertEqual(self.client_wallet.confirmed_balance_cents, 10_000)

        accepted = process_evidence(self.db, self.merchant, completed)
        repeated = process_evidence(self.db, self.client, completed)
        self.assertEqual(accepted.status, "ACCEPTED")
        self.assertEqual(repeated.status, "ACCEPTED")
        self.db.refresh(self.client_wallet)
        self.db.refresh(self.merchant_wallet)
        self.db.refresh(self.authorization)
        self.assertEqual(self.client_wallet.confirmed_balance_cents, 6_000)
        self.assertEqual(self.merchant_wallet.confirmed_balance_cents, 4_000)
        self.assertEqual(self.authorization.remaining_amount_cents, 6_000)
        self.assertEqual(self.authorization.remaining_payments, 9)
        self.assertEqual(self.db.query(models.LedgerEntry).count(), 2)

    def test_pos_first_then_phone_without_ack_returns_same_result(self):
        pending, completed = self._evidence("123e4567-e89b-42d3-a456-426614174021", 2_500)

        pos_result = process_evidence(self.db, self.merchant, completed)
        phone_result = process_evidence(self.db, self.client, pending)
        repeated_pos_result = process_evidence(self.db, self.merchant, completed)

        self.assertEqual(pos_result.status, "ACCEPTED")
        self.assertEqual(phone_result.status, "ACCEPTED")
        self.assertEqual(repeated_pos_result.status, "ACCEPTED")
        self.db.expire_all()
        self.assertEqual(self.db.get(models.Wallet, "wallet-1").confirmed_balance_cents, 7_500)
        self.assertEqual(self.db.get(models.Wallet, "wallet-2").confirmed_balance_cents, 2_500)
        self.assertEqual(self.db.query(models.LedgerEntry).count(), 2)

    def test_same_id_with_other_content_is_conflict(self):
        _, completed = self._evidence("123e4567-e89b-42d3-a456-426614174002", 2_000)
        self.assertEqual(process_evidence(self.db, self.client, completed).status, "ACCEPTED")
        _, changed = self._evidence("123e4567-e89b-42d3-a456-426614174002", 3_000)
        conflict = process_evidence(self.db, self.client, changed)
        self.assertEqual(conflict.status, "CONFLICT")
        self.db.refresh(self.client_wallet)
        self.assertEqual(self.client_wallet.confirmed_balance_cents, 8_000)

    def test_valid_operation_rejects_unrelated_user(self):
        _, completed = self._evidence("123e4567-e89b-42d3-a456-426614174003", 1_000)
        with self.assertRaises(HTTPException) as context:
            process_evidence(self.db, self.outsider, completed)
        self.assertEqual(context.exception.status_code, 403)

    def test_revoked_wallet_key_rejects_evidence_without_moving_balance(self):
        _, completed = self._evidence("123e4567-e89b-42d3-a456-426614174004", 1_000)
        self.wallet_key.revoked = True
        self.db.commit()
        result = process_evidence(self.db, self.client, completed)
        self.assertEqual(result.status, "REJECTED")
        self.db.expire_all()
        self.assertEqual(self.db.get(models.Wallet, "wallet-1").confirmed_balance_cents, 10_000)
        self.assertEqual(self.db.query(models.LedgerEntry).count(), 0)

    def test_unregistered_and_foreign_wallet_signers_are_rejected(self):
        _, completed = self._evidence("123e4567-e89b-42d3-a456-426614174030", 1_000)
        unknown = self._resign_evidence(
            completed,
            receipt_updates={"wallet_key_id": "wallet-key-unknown", "wallet_key_fingerprint": "0" * 64},
        )
        self.assertEqual(process_evidence(self.db, self.client, unknown).status, "REJECTED")

        other_private = ec.generate_private_key(ec.SECP256R1())
        foreign = self._resign_evidence(completed, receipt_signer=other_private)
        self.assertEqual(process_evidence(self.db, self.client, foreign).status, "REJECTED")
        self.db.expire_all()
        self.assertEqual(self.db.get(models.Wallet, "wallet-1").confirmed_balance_cents, 10_000)
        self.assertEqual(self.db.query(models.LedgerEntry).count(), 0)

    def test_expired_window_and_unknown_terminal_are_rejected(self):
        _, completed = self._evidence("123e4567-e89b-42d3-a456-426614174031", 1_000)
        expired = self._resign_evidence(
            completed,
            common_updates={
                "issued_at": "2026-10-14T15:00:00Z",
                "expires_at": "2026-10-14T15:02:00Z",
                "accepted_at": "2026-10-14T15:01:00Z",
            },
        )
        wrong_terminal = self._resign_evidence(
            completed,
            common_updates={"terminal_id": "terminal-unknown"},
        )
        self.assertEqual(process_evidence(self.db, self.client, expired).status, "REJECTED")
        self.assertEqual(process_evidence(self.db, self.client, wrong_terminal).status, "REJECTED")

    def test_reused_nonce_with_another_operation_is_conflict(self):
        _, first = self._evidence("123e4567-e89b-42d3-a456-426614174032", 1_000)
        self.assertEqual(process_evidence(self.db, self.client, first).status, "ACCEPTED")
        first_request = parse_signed_envelope(base64.b64decode(first.request_envelope_b64)).payload
        _, second = self._evidence("123e4567-e89b-42d3-a456-426614174033", 1_000)
        reused = self._resign_evidence(
            second,
            common_updates={"nonce": first_request["nonce"]},
        )
        result = process_evidence(self.db, self.client, reused)
        self.assertEqual((result.status, result.code), ("CONFLICT", "NONCE_REUSED"))

    def test_mixed_batch_keeps_individual_results(self):
        pending, _ = self._evidence("123e4567-e89b-42d3-a456-426614174005", 1_000)
        invalid = schemas.OfflinePaymentEvidence(
            operation_id="123e4567-e89b-42d3-a456-426614174006",
            request_envelope_b64="invalid",
            receipt_envelope_b64="invalid",
        )
        response = sync_offline_payments_v2(
            schemas.OfflinePaymentSyncV2Request(operations=[pending, invalid]),
            self.db,
            self.client,
        )
        self.assertEqual([result.status for result in response.results], ["PENDING_EVIDENCE", "REJECTED"])

    def test_concurrent_payments_cannot_overdraw_balance(self):
        self.client_wallet.confirmed_balance_cents = 5_000
        self.authorization.remaining_amount_cents = 10_000
        self.db.commit()
        _, first = self._evidence("123e4567-e89b-42d3-a456-426614174010", 4_000)
        _, second = self._evidence("123e4567-e89b-42d3-a456-426614174011", 4_000)
        barrier = threading.Barrier(2)
        results = []

        def run(evidence):
            with Session(self.engine) as session:
                user = session.get(models.User, 1)
                barrier.wait()
                results.append((evidence, process_evidence(session, user, evidence).status))

        threads = [threading.Thread(target=run, args=(evidence,)) for evidence in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for evidence, result in list(results):
            if result == "RETRYABLE_ERROR":
                with Session(self.engine) as session:
                    result = process_evidence(session, session.get(models.User, 1), evidence).status
                    results.append((evidence, result))

        with Session(self.engine) as session:
            wallet = session.get(models.Wallet, "wallet-1")
            merchant = session.get(models.Wallet, "wallet-2")
            self.assertEqual(wallet.confirmed_balance_cents, 1_000)
            self.assertEqual(merchant.confirmed_balance_cents, 4_000)
            self.assertEqual(session.query(models.LedgerEntry).count(), 2)
        final_statuses = [status for _, status in results if status != "RETRYABLE_ERROR"]
        self.assertIn("ACCEPTED", final_statuses)
        self.assertIn("REJECTED", final_statuses)

    def test_failure_between_updates_rolls_back_every_movement(self):
        _, completed = self._evidence("123e4567-e89b-42d3-a456-426614174020", 2_000)
        self.db.execute(
            text(
                "CREATE TRIGGER fail_merchant_credit BEFORE UPDATE OF confirmed_balance_cents ON wallets "
                "WHEN NEW.id = 'wallet-2' BEGIN SELECT RAISE(ABORT, 'simulated failure'); END"
            )
        )
        self.db.commit()
        result = process_evidence(self.db, self.client, completed)
        self.assertEqual(result.status, "RETRYABLE_ERROR")
        self.db.expire_all()
        self.assertEqual(self.db.get(models.Wallet, "wallet-1").confirmed_balance_cents, 10_000)
        self.assertEqual(self.db.get(models.Wallet, "wallet-2").confirmed_balance_cents, 0)
        self.assertEqual(self.db.get(models.OfflineAuthorization, "authorization-1").remaining_amount_cents, 10_000)
        self.assertEqual(self.db.query(models.LedgerEntry).count(), 0)
        self.assertIsNone(self.db.get(models.OfflinePaymentV2, completed.operation_id))

    def test_failure_after_balance_updates_rolls_back_every_movement(self):
        _, completed = self._evidence("123e4567-e89b-42d3-a456-426614174034", 2_000)
        self.db.execute(
            text(
                "CREATE TRIGGER fail_ledger BEFORE INSERT ON ledger_entries "
                "BEGIN SELECT RAISE(ABORT, 'simulated ledger failure'); END"
            )
        )
        self.db.commit()
        result = process_evidence(self.db, self.client, completed)
        self.assertEqual(result.status, "RETRYABLE_ERROR")
        self.db.expire_all()
        self.assertEqual(self.db.get(models.Wallet, "wallet-1").confirmed_balance_cents, 10_000)
        self.assertEqual(self.db.get(models.Wallet, "wallet-2").confirmed_balance_cents, 0)
        self.assertEqual(self.db.get(models.OfflineAuthorization, "authorization-1").remaining_amount_cents, 10_000)
        self.assertEqual(self.db.query(models.LedgerEntry).count(), 0)
        self.assertIsNone(self.db.get(models.OfflinePaymentV2, completed.operation_id))

    def _registered_key(self, key_id, private_key, owner_id, purpose, wallet_id=None, terminal_id=None):
        public_b64 = encode_public_key(private_key.public_key())
        return models.RegisteredKey(
            key_id=key_id,
            owner_user_id=owner_id,
            purpose=purpose,
            wallet_id=wallet_id,
            terminal_id=terminal_id,
            public_key_b64=public_b64,
            fingerprint=public_key_fingerprint(base64.b64decode(public_b64)),
            proof_nonce=f"proof-{key_id}",
            revoked=False,
        )

    def _evidence(self, operation_id: str, amount: int):
        common = {
            "version": 2,
            "operation_id": operation_id,
            "merchant_id": "merchant-2",
            "terminal_id": "terminal-1",
            "amount_cents": amount,
            "currency": "ARS",
            "nonce": base64.urlsafe_b64encode(UUID(operation_id).bytes).decode().rstrip("="),
            "issued_at": "2026-10-13T15:00:00Z",
            "expires_at": "2026-10-13T15:02:00Z",
        }
        request = {
            **common,
            "type": "payment_request",
            "pos_key_id": self.pos_key.key_id,
            "pos_key_fingerprint": self.pos_key.fingerprint,
        }
        receipt = {
            **common,
            "type": "payment_receipt",
            "wallet_id": "wallet-1",
            "offline_authorization_id": "authorization-1",
            "wallet_key_id": self.wallet_key.key_id,
            "wallet_key_fingerprint": self.wallet_key.fingerprint,
            "request_digest": payload_digest(request),
        }
        ack = {
            **common,
            "type": "payment_ack",
            "wallet_id": "wallet-1",
            "offline_authorization_id": "authorization-1",
            "pos_key_id": self.pos_key.key_id,
            "pos_key_fingerprint": self.pos_key.fingerprint,
            "receipt_digest": payload_digest(receipt),
            "accepted_at": "2026-10-13T15:01:00Z",
            "status": "LOCALLY_ACCEPTED",
        }
        request_wire = encode_signed_envelope(request, sign_payload(request, self.pos_private))
        receipt_wire = encode_signed_envelope(receipt, sign_payload(receipt, self.wallet_private))
        ack_wire = encode_signed_envelope(ack, sign_payload(ack, self.pos_private))
        pending = schemas.OfflinePaymentEvidence(
            operation_id=operation_id,
            request_envelope_b64=base64.b64encode(request_wire).decode(),
            receipt_envelope_b64=base64.b64encode(receipt_wire).decode(),
        )
        complete = pending.model_copy(
            update={"ack_envelope_b64": base64.b64encode(ack_wire).decode()}
        )
        return pending, complete

    def _resign_evidence(
        self,
        evidence: schemas.OfflinePaymentEvidence,
        common_updates: dict | None = None,
        receipt_updates: dict | None = None,
        receipt_signer=None,
    ) -> schemas.OfflinePaymentEvidence:
        request = dict(parse_signed_envelope(base64.b64decode(evidence.request_envelope_b64)).payload)
        receipt = dict(parse_signed_envelope(base64.b64decode(evidence.receipt_envelope_b64)).payload)
        ack = dict(parse_signed_envelope(base64.b64decode(evidence.ack_envelope_b64)).payload)
        updates = dict(common_updates or {})
        accepted_at = updates.pop("accepted_at", None)
        for payload in (request, receipt, ack):
            payload.update(updates)
        if accepted_at is not None:
            ack["accepted_at"] = accepted_at
        receipt.update(receipt_updates or {})
        receipt["request_digest"] = payload_digest(request)
        ack["receipt_digest"] = payload_digest(receipt)
        request_wire = encode_signed_envelope(request, sign_payload(request, self.pos_private))
        receipt_wire = encode_signed_envelope(
            receipt,
            sign_payload(receipt, receipt_signer or self.wallet_private),
        )
        ack_wire = encode_signed_envelope(ack, sign_payload(ack, self.pos_private))
        return schemas.OfflinePaymentEvidence(
            operation_id=evidence.operation_id,
            request_envelope_b64=base64.b64encode(request_wire).decode(),
            receipt_envelope_b64=base64.b64encode(receipt_wire).decode(),
            ack_envelope_b64=base64.b64encode(ack_wire).decode(),
        )


if __name__ == "__main__":
    unittest.main()
