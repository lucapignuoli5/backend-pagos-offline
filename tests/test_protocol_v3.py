"""Pure contract tests: original wire bytes, signatures and cross-message scope."""
import base64
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
import unittest

from cryptography.hazmat.primitives.asymmetric import ec

import protocol_v3 as p
from protocol_v2 import parse_signed_envelope as parse_legacy


FIXTURE = Path(__file__).parent / "fixtures" / "protocol_v3_vectors.json"


class ProtocolV3Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.envelopes = {
            name: p.parse_signed_envelope(base64.b64decode(vector["envelope_b64"]))
            for name, vector in self.fixture["messages"].items()
        }

    def test_complete_original_kotlin_envelopes_verify_in_python(self):
        from tools.verify_cross_language import verify_fixture
        self.assertEqual(verify_fixture(FIXTURE.parent / "protocol_v3_kotlin_vectors.json"), 7)

    def test_all_seven_public_vectors_verify_original_bytes(self):
        self.assertEqual(len(self.envelopes), 7)
        for name, envelope in self.envelopes.items():
            with self.subTest(name=name):
                vector = self.fixture["messages"][name]
                self.assertEqual(envelope.payload_bytes, base64.b64decode(vector["payload_b64"]))
                self.assertEqual(envelope.payload, vector["payload"])
                self.assertEqual(p.payload_digest(envelope), vector["payload_sha256"])
                self.assertTrue(envelope.verify(self.fixture["keys"][vector["signer"]]["public_key_b64"]))
                self.assertEqual(p.encode_signed_envelope(envelope.payload_bytes, envelope.signature_b64),
                                 base64.b64decode(vector["envelope_b64"]))

    def test_altering_every_signed_field_invalidates_each_signature(self):
        for name, envelope in self.envelopes.items():
            key = self.fixture["keys"][self.fixture["messages"][name]["signer"]]["public_key_b64"]
            for field, value in envelope.payload.items():
                with self.subTest(name=name, field=field):
                    changed = dict(envelope.payload)
                    changed[field] = value + 1 if type(value) is int else value + "x"
                    self.assertFalse(p.verify_exact_signature(p.canonical_bytes(changed), envelope.signature_b64, key))

    def test_wrong_signer_is_rejected_for_every_message(self):
        foreign = p.encode_public_key(ec.generate_private_key(ec.SECP256R1()).public_key())
        for envelope in self.envelopes.values():
            self.assertFalse(envelope.verify(foreign))
        grant = self.envelopes["authorization"]
        self.assertFalse(p.verify_authorization(grant, foreign))
        self.assertFalse(p.verify_authorization(grant, self.fixture["keys"]["issuer"]["public_key_b64"], "other-issuer"))

    def test_pos_trusted_scope_must_match_signed_identity(self):
        key = self.fixture["keys"]["pos"]
        args = [key["public_key_b64"], key["key_id"], key["fingerprint"], "merchant-2", "terminal-1"]
        for name in ("request", "ack"):
            self.assertTrue(p.verify_pos_signer(self.envelopes[name], *args))
            for offset in (1, 2, 3, 4):
                changed = list(args)
                changed[offset] = "0"*64 if offset == 2 else "other"
                self.assertFalse(p.verify_pos_signer(self.envelopes[name], *changed))

    def test_select_capabilities_validate_version_limits_and_grant_support(self):
        self.assertEqual(p.parse_select_capabilities(p.encode_select_capabilities()), p.SelectCapabilities(4096, 160))
        self.assertEqual(p.parse_select_capabilities(p.encode_select_capabilities(4096, 120)), p.SelectCapabilities(4096, 120))
        original = json.loads(p.encode_select_capabilities())
        for field, value in (("protocol_version", 2), ("protocol_version", 3.0), ("chunk_bytes", 161),
                             ("max_message_bytes", 4097), ("max_message_bytes", 0), ("authorization_instruction", 64)):
            with self.subTest(field=field, value=value), self.assertRaises(p.ProtocolError):
                p.parse_select_capabilities(json.dumps(dict(original, **{field: value}), sort_keys=True, separators=(",", ":")).encode())
        with self.assertRaises(p.ProtocolError):
            p.parse_select_capabilities(b"v2|4096|160")

    def test_coherent_receipt_ack_authorization_and_closure(self):
        e = self.envelopes
        self.assertTrue(p.verify_authorization(e["authorization"], self.fixture["keys"]["issuer"]["public_key_b64"],
                                              self.fixture["keys"]["issuer"]["key_id"]))
        p.validate_receipt_binding(e["request"], e["receipt"], e["authorization"])
        p.validate_ack_binding(e["request"], e["receipt"], e["ack"])
        manifest_bytes = base64.b64decode(self.fixture["manifest_b64"])
        self.assertEqual(p.validate_close_manifest(e["close"], e["authorization"], manifest_bytes), self.fixture["manifest"])
        # A final resolution may be dated after spend expiry; no wall clock is read.
        self.assertGreater(e["resolution"].payload["resolved_at"], e["authorization"].payload["spend_expires_at"])

    def _changed(self, name, **updates):
        value = copy.deepcopy(self.envelopes[name].payload)
        value.update(updates)
        return p.SignedEnvelope(p.canonical_bytes(value), value, self.envelopes[name].signature_b64)

    def test_binding_rejects_foreign_scope_and_digest(self):
        e = self.envelopes
        for field, value in {"wallet_id": "wallet-other", "offline_authorization_id": "grant-other",
                             "wallet_key_id": "wallet-other-key", "wallet_key_fingerprint": "0"*64,
                             "request_digest": "0"*64, "authorization_digest": "0"*64,
                             "issuance_index": 11}.items():
            with self.subTest(field=field), self.assertRaises(p.ProtocolError):
                p.validate_receipt_binding(e["request"], self._changed("receipt", **{field: value}), e["authorization"])
        for field, value in {"pos_key_id": "foreign-pos", "pos_key_fingerprint": "0"*64,
                             "receipt_digest": "0"*64, "accepted_at": "2026-10-14T15:00:10Z"}.items():
            with self.subTest(field=field), self.assertRaises(p.ProtocolError):
                p.validate_ack_binding(e["request"], e["receipt"], self._changed("ack", **{field: value}))

    def test_binding_rejects_signed_window_and_amount_limits(self):
        e = self.envelopes
        wallet_private = ec.generate_private_key(ec.SECP256R1())
        issuer_private = ec.generate_private_key(ec.SECP256R1())
        wallet_public = p.encode_public_key(wallet_private.public_key())
        issuer_public = p.encode_public_key(issuer_private.public_key())
        for updates in ({"max_payment_cents": 99999, "authorized_total_cents": 999990},
                        {"authorized_total_cents": 50000},
                        {"spend_expires_at": "2026-10-14T15:01:00Z"},
                        {"issued_at": "2026-10-14T15:00:01Z"}, {"max_request_lifetime_seconds": 119}):
            gp = dict(e["authorization"].payload, wallet_public_key_b64=wallet_public,
                      wallet_key_fingerprint=p.public_key_fingerprint(base64.b64decode(wallet_public)),
                      issuer_key_fingerprint=p.public_key_fingerprint(base64.b64decode(issuer_public)))
            gp.update(updates)
            grant = p.parse_signed_envelope(p.encode_signed_envelope(gp, p.sign_payload(gp, issuer_private)))
            rp = dict(e["receipt"].payload, authorization_digest=p.payload_digest(grant),
                      wallet_key_fingerprint=gp["wallet_key_fingerprint"])
            receipt = p.parse_signed_envelope(p.encode_signed_envelope(rp, p.sign_payload(rp, wallet_private)))
            self.assertTrue(p.verify_authorization(grant, issuer_public))
            self.assertTrue(receipt.verify(wallet_public))
            with self.subTest(updates=updates), self.assertRaises(p.ProtocolError):
                p.validate_receipt_binding(e["request"], receipt, grant)

    def test_manifest_rejects_gaps_duplicates_wrong_totals_and_tampering(self):
        e = self.envelopes
        original = self.fixture["manifest"]
        malformed = [dict(original[0], issuance_index=2)]
        with self.assertRaises(p.ProtocolError):
            p.parse_close_manifest(p.canonical_bytes(malformed))
        repeated = [original[0], dict(original[0], issuance_index=2)]
        with self.assertRaises(p.ProtocolError):
            p.parse_close_manifest(p.canonical_bytes(repeated))
        raw = base64.b64decode(self.fixture["manifest_b64"])
        for updates in ({"emitted_total_cents": 99999}, {"final_issuance_index": 0},
                        {"manifest_digest": "0"*64}, {"wallet_id": "wallet-other"}):
            with self.subTest(updates=updates), self.assertRaises(p.ProtocolError):
                p.validate_close_manifest(self._changed("close", **updates), e["authorization"], raw)
        self.assertEqual(p.parse_close_manifest(b"[]"), [])

    def test_strict_types_unknown_fields_amounts_and_overflow(self):
        original = self.envelopes["request"].payload
        for field, values in {"version": [3.0, "3", True, 2], "amount_cents": [0, -1, 2**63, 3.0, "1", True],
                              "nonce": ["AAECAwQFBgcICQoLDA0ODx", "AAECAwQFBgcICQoLDA0ODw=="],
                              "operation_id": ["123e4567-e89b-42d3-a456-426614174001".upper()],
                              "currency": ["USD", "ars"], "merchant_id": ["comercio-á", "a=b"]}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(p.ProtocolError):
                    p.validate_payload(dict(original, **{field: value}))
        with self.assertRaises(p.ProtocolError):
            p.validate_payload(dict(original, unexpected="field"))
        missing = dict(original)
        del missing["nonce"]
        with self.assertRaises(p.ProtocolError):
            p.validate_payload(missing)
        grant = dict(self.envelopes["authorization"].payload, max_payment_cents=p.MAX_INT64, max_payments=2)
        with self.assertRaises(p.ProtocolError):
            p.validate_payload(grant)
        for name, field in (("key_registration", "purpose"), ("resolution", "operation_status")):
            for value in ([], {}):
                with self.assertRaises(p.ProtocolError):
                    p.validate_payload(dict(self.envelopes[name].payload, **{field: value}))

    def test_rejects_duplicate_noncanonical_and_malformed_json(self):
        vector = self.fixture["messages"]["request"]
        payload = base64.b64decode(vector["payload_b64"])
        duplicate = payload.replace(b'"version":3', b'"version":3,"version":3')
        for raw in (duplicate, payload.replace(b'"version":3', b'"version":3.0'), b'{', b'\xff',
                    b' ' + payload, b'[]', b'{"a":null}', b'{"a":true}', b'['*1500+b']'*1500):
            with self.subTest(raw=raw[:30]), self.assertRaises(p.ProtocolError):
                p.parse_canonical_payload(raw)
        wire = base64.b64decode(vector["envelope_b64"])
        for raw in (wire + b"\n", wire.replace(b"=", b"\\u003d"),
                    wire.replace(b'"payload_b64":', b'"unknown":'), b"{}"):
            with self.assertRaises(p.ProtocolError):
                p.parse_signed_envelope(raw)

    def test_padding_zero_one_two_and_utf8_no_html_escaping(self):
        for value in (b"abc", b"ab", b"a"):
            encoded = base64.b64encode(value).decode("ascii")
            self.assertEqual(p.decode_base64(encoded), value)
        for value in ("AB==", "AA=", "AA===", "AA==\n", "AA", ""):
            with self.assertRaises(p.ProtocolError):
                p.decode_base64(value)
        self.assertEqual(p.canonical_bytes({"z": "<>&='", "á": "\u2028😀"}),
                         '{"z":"<>&=\'","á":"\u2028😀"}'.encode())
        private = ec.generate_private_key(ec.SECP256R1())
        paddings = set()
        for length in range(1, 4):
            payload = dict(self.envelopes["request"].payload, merchant_id="m"*length)
            data = p.canonical_bytes(payload)
            paddings.add(len(data) % 3)
            signature = p.sign_payload(payload, private)
            wire = p.encode_signed_envelope(payload, signature)
            self.assertNotIn(b"\\u003d", wire)
            self.assertTrue(p.parse_signed_envelope(wire).verify(p.encode_public_key(private.public_key())))
        self.assertEqual(paddings, {0, 1, 2})

    def test_der_signature_key_shape_and_message_limits(self):
        for signature in ("AA==", "AAAA", "MAA="):
            with self.assertRaises(p.ProtocolError):
                p.encode_signed_envelope(self.envelopes["request"].payload, signature)
        other_curve = ec.generate_private_key(ec.SECP384R1())
        with self.assertRaises(p.ProtocolError):
            p.sign_payload(self.envelopes["request"].payload, other_curve)
        public_der = base64.b64decode(self.fixture["keys"]["wallet"]["public_key_b64"])
        unknown_curve_der = public_der.replace(bytes.fromhex("06082a8648ce3d030107"),
                                              bytes.fromhex("06082a8648ce3d030100"))
        unknown_curve = base64.b64encode(unknown_curve_der).decode("ascii")
        with self.assertRaises(p.ProtocolError):
            p.decode_public_key(unknown_curve)
        self.assertFalse(self.envelopes["receipt"].verify(unknown_curve))
        self.assertFalse(p.verify_authorization(self.envelopes["authorization"], unknown_curve))
        with self.assertRaises(p.ProtocolError):
            p.validate_payload(dict(self.envelopes["authorization"].payload,
                                    wallet_public_key_b64=unknown_curve))
        with self.assertRaises(p.ProtocolError):
            p.canonical_bytes({"a": "a"*4096})
        with self.assertRaises(p.ProtocolError):
            p.parse_signed_envelope(b"a"*4097)
        with self.assertRaises(p.ProtocolError):
            p.encode_signed_envelope(dict(self.envelopes["request"].payload,
                                          merchant_id="m"*120,terminal_id="t"*120,
                                          pos_key_id="p"*120,amount_cents=p.MAX_INT64),
                                     "AA==")

    def test_seconds_precision_rejects_fractional_and_rounds_producer(self):
        original = self.envelopes["request"].payload
        self.assertEqual(p.timestamp(datetime(2026, 10, 14, 15, 0, 0, 1000, tzinfo=timezone.utc)),
                         "2026-10-14T15:00:00Z")
        for value in ("2026-10-14T15:00:00.001Z", "2026-10-14T15:00:00+00:00", "2026-02-30T15:00:00Z"):
            with self.assertRaises(p.ProtocolError):
                p.validate_payload(dict(original, issued_at=value))
        with self.assertRaises(p.ProtocolError):
            p.timestamp(datetime(2026, 10, 14))

    def test_legacy_outer_forms_are_preserved_and_float_version_rejected(self):
        legacy = json.loads((FIXTURE.parent / "protocol_v2_vectors.json").read_text(encoding="utf-8"))
        # Build the envelope from the original public payload/signature, never resign.
        from protocol_v2 import encode_signed_envelope
        payload = legacy["request"]
        signature = legacy["signature_der_b64"]
        wire = encode_signed_envelope(payload, signature)
        gson_wire = wire.replace(b"=", b"\\u003d")
        parsed = parse_legacy(gson_wire)
        self.assertEqual(parsed.payload_bytes, parse_legacy(wire).payload_bytes)
        self.assertTrue(parsed.verify(legacy["public_key_der_b64"]))
        with self.assertRaises(ValueError):
            parse_legacy(wire + b"\n")
        changed = dict(payload, version=2.0)
        from protocol_v2 import validate_payload
        with self.assertRaises(ValueError):
            validate_payload(changed)


if __name__ == "__main__":
    unittest.main()
