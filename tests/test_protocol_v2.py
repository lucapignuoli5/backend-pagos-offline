import copy
import json
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec

from protocol_v2 import (
    INS_PUT_REQUEST,
    MAX_MESSAGE_BYTES,
    ProtocolError,
    assemble_chunks,
    build_apdu,
    canonical_json,
    chunk_message,
    encode_signed_envelope,
    parse_apdu,
    parse_canonical_payload,
    parse_signed_envelope,
    sign_payload,
    validate_payload,
    verify_payload_signature,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "protocol_v2_vectors.json"


class ProtocolV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vector = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.request = cls.vector["request"]

    def test_canonical_vector(self):
        self.assertEqual(canonical_json(self.request), self.vector["canonical_request"])
        self.assertEqual(validate_payload(self.request).value, "payment_request")
        self.assertEqual(parse_canonical_payload(self.vector["canonical_request"].encode()), self.request)
        self.assertTrue(
            verify_payload_signature(
                self.request,
                self.vector["signature_der_b64"],
                self.vector["public_key_der_b64"],
            )
        )

    def test_python_signature_and_every_field_tamper(self):
        private_key = ec.generate_private_key(ec.SECP256R1())
        from protocol_v2 import encode_public_key

        public_key = encode_public_key(private_key.public_key())
        signature = sign_payload(self.request, private_key)
        self.assertTrue(verify_payload_signature(self.request, signature, public_key))

        for field in self.request:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.request)
                value = changed[field]
                changed[field] = value + "x" if isinstance(value, str) else value + 1
                self.assertFalse(verify_payload_signature(changed, signature, public_key))

    def test_signed_envelope_preserves_exact_payload_bytes(self):
        wire = encode_signed_envelope(self.request, self.vector["signature_der_b64"])
        envelope = parse_signed_envelope(wire)
        self.assertEqual(envelope.payload_bytes, self.vector["canonical_request"].encode())
        self.assertEqual(envelope.payload, self.request)
        self.assertTrue(envelope.verify(self.vector["public_key_der_b64"]))

        changed_wire = wire.replace(b"payload_b64", b"payload_data")
        with self.assertRaises(ProtocolError):
            parse_signed_envelope(changed_wire)

    def test_rejects_non_integer_and_unknown_fields(self):
        for amount in (0, -1, 100_001, 1.5, True):
            changed = {**self.request, "amount_cents": amount}
            with self.subTest(amount=amount), self.assertRaises(ProtocolError):
                validate_payload(changed)
        with self.assertRaises(ProtocolError):
            validate_payload({**self.request, "unexpected": "field"})

    def test_rejects_noncanonical_json(self):
        pretty = json.dumps(self.request, ensure_ascii=False).encode()
        with self.assertRaises(ProtocolError):
            parse_canonical_payload(pretty)

    def test_apdu_fragmentation_round_trip(self):
        data = self.vector["canonical_request"].encode()
        chunks = chunk_message(data)
        decoded = []
        for sequence, chunk in enumerate(chunks):
            apdu = build_apdu(INS_PUT_REQUEST, sequence, sequence == len(chunks) - 1, chunk)
            parsed = parse_apdu(apdu)
            self.assertEqual(parsed.sequence, sequence)
            self.assertEqual(parsed.is_last, sequence == len(chunks) - 1)
            decoded.append(parsed.data)
        self.assertEqual(assemble_chunks(decoded), data)

    def test_rejects_oversized_message(self):
        with self.assertRaises(ProtocolError):
            chunk_message(b"x" * (MAX_MESSAGE_BYTES + 1))

    def test_ack_must_be_accepted_before_request_expiry(self):
        ack = {
            "version": 2,
            "type": "payment_ack",
            "operation_id": self.request["operation_id"],
            "merchant_id": self.request["merchant_id"],
            "terminal_id": self.request["terminal_id"],
            "amount_cents": self.request["amount_cents"],
            "currency": "ARS",
            "nonce": self.request["nonce"],
            "issued_at": self.request["issued_at"],
            "expires_at": self.request["expires_at"],
            "wallet_id": "wallet-1",
            "offline_authorization_id": "authorization-1",
            "pos_key_id": self.request["pos_key_id"],
            "pos_key_fingerprint": self.request["pos_key_fingerprint"],
            "receipt_digest": "0" * 64,
            "accepted_at": "2026-10-13T15:02:01Z",
            "status": "LOCALLY_ACCEPTED",
        }
        with self.assertRaises(ProtocolError):
            validate_payload(ack)


if __name__ == "__main__":
    unittest.main()
