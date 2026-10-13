import tempfile
import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path

from pos_desktop.config import PosConfig
from pos_desktop.database import PosDatabase
from pos_desktop.key_store import PosKeyStore, WindowsDpapiProtector
from pos_desktop.service import PosService
from pos_desktop.simulator import AndroidHceSimulator, SimulatorTransport
from protocol_v2 import encode_signed_envelope, parse_signed_envelope, sign_payload


class ReversibleTestProtector:
    def protect(self, value: bytes) -> bytes:
        return b"test-protected:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"test-protected:"):
            raise ValueError("Proteccion de prueba invalida")
        return value[len(b"test-protected:"):][::-1]


class PosDesktopTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = PosDatabase(Path(self.directory.name) / "pos.sqlite")
        self.simulator = AndroidHceSimulator()
        self.config = PosConfig(
            database_path=Path(self.directory.name) / "pos.sqlite",
            merchant_id="merchant-1",
            terminal_id="terminal-1",
            pos_key_id="pos-key-1",
            backend_url="http://127.0.0.1:8000",
            reader_name=None,
            simulator=True,
        )
        self.service = PosService(
            self.config,
            self.database,
            PosKeyStore(self.database, ReversibleTestProtector()),
            lambda: SimulatorTransport(self.simulator),
            now=lambda: datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc),
        )
        _, public_key, fingerprint = self.service.key_store.get_or_create("pos-key-1")
        self.simulator.trust_pos_key("pos-key-1", fingerprint, public_key)
        self.database.trust_wallet_key(
            self.simulator.wallet_key_id,
            self.simulator.wallet_fingerprint,
            self.simulator.wallet_id,
            self.simulator.wallet_public_key_b64,
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_full_two_approach_flow_is_durable_and_idempotent(self):
        operation = self.service.create_payment(12_345)
        self.assertEqual(self.service.deliver_request(operation.operation_id), "REQUEST_RECEIVED")
        self.simulator.confirm(operation.operation_id)
        self.assertEqual(self.service.collect_receipt(operation.operation_id), "LOCALLY_ACCEPTED")
        self.assertEqual(self.service.collect_receipt(operation.operation_id), "LOCALLY_ACCEPTED")

        stored = self.database.get_operation(operation.operation_id)
        self.assertEqual(stored.state, "LOCALLY_ACCEPTED")
        self.assertIsNotNone(stored.receipt_envelope)
        self.assertIsNotNone(stored.ack_envelope)
        self.assertEqual(self.simulator.acks[operation.operation_id], stored.ack_envelope)

    def test_unconfirmed_request_remains_waiting_without_acceptance(self):
        operation = self.service.create_payment(1_000)
        self.service.deliver_request(operation.operation_id)
        self.assertEqual(self.service.collect_receipt(operation.operation_id), "REQUEST_RECEIVED")
        stored = self.database.get_operation(operation.operation_id)
        self.assertEqual(stored.state, "WAITING_CONFIRMATION")
        self.assertIsNone(stored.receipt_envelope)

    def test_tampered_receipt_is_not_persisted(self):
        operation = self.service.create_payment(5_000)
        self.service.deliver_request(operation.operation_id)
        receipt = bytearray(self.simulator.confirm(operation.operation_id))
        receipt[len(receipt) // 2] ^= 1
        self.simulator.receipts[operation.operation_id] = bytes(receipt)
        with self.assertRaises(ValueError):
            self.service.collect_receipt(operation.operation_id)
        stored = self.database.get_operation(operation.operation_id)
        self.assertIsNone(stored.receipt_envelope)
        self.assertEqual(stored.state, "REQUEST_DELIVERED")

    def test_valid_wallet_signature_cannot_change_amount(self):
        operation = self.service.create_payment(5_000)
        self.service.deliver_request(operation.operation_id)
        original = self.simulator.confirm(operation.operation_id)
        payload = parse_signed_envelope(original).payload
        payload["amount_cents"] = 5_001
        self.simulator.receipts[operation.operation_id] = encode_signed_envelope(
            payload, sign_payload(payload, self.simulator.wallet_private_key)
        )
        with self.assertRaisesRegex(ValueError, "no coincide"):
            self.service.collect_receipt(operation.operation_id)
        self.assertIsNone(self.database.get_operation(operation.operation_id).receipt_envelope)

    def test_private_key_is_not_stored_as_plain_pkcs8(self):
        row = self.database.get_identity("pos-key-1")
        self.assertTrue(bytes(row["protected_private_key"]).startswith(b"test-protected:"))

    @unittest.skipUnless(sys.platform == "win32", "DPAPI requiere Windows")
    def test_windows_dpapi_round_trip(self):
        protector = WindowsDpapiProtector()
        plaintext = b"test-only-private-material"
        protected = protector.protect(plaintext)
        self.assertNotEqual(protected, plaintext)
        self.assertEqual(protector.unprotect(protected), plaintext)


if __name__ == "__main__":
    unittest.main()

