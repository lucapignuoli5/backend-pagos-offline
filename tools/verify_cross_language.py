"""Verify complete public envelopes produced by Kotlin or Python, without writes."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import protocol_v3 as p


def verify_fixture(path: Path) -> int:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    messages = fixture["messages"]
    required = {"authorization", "request", "receipt", "ack", "close", "resolution", "key_registration"}
    if set(messages) != required:
        raise p.ProtocolError("Cross-language fixture must contain all seven message types")
    envelopes = {}
    for name, vector in messages.items():
        wire = p.decode_base64(vector["envelope_b64"], "envelope_b64")
        envelope = p.parse_signed_envelope(wire)
        key = fixture["keys"][vector["signer"]]
        if (envelope.payload_bytes != p.decode_base64(vector["payload_b64"])
                or envelope.payload != vector["payload"]
                or p.payload_digest(envelope) != vector["payload_sha256"]
                or envelope.signature_b64 != vector["signature_b64"]
                or not envelope.verify(key["public_key_b64"])):
            raise p.ProtocolError(f"Cross-language evidence failed: {name}")
        if p.encode_signed_envelope(envelope.payload_bytes, envelope.signature_b64) != wire:
            raise p.ProtocolError(f"Original envelope changed: {name}")
        envelopes[name] = envelope
    if not p.verify_authorization(envelopes["authorization"], fixture["keys"]["issuer"]["public_key_b64"],
                                  fixture["keys"]["issuer"]["key_id"]):
        raise p.ProtocolError("Issuer verification failed")
    p.validate_receipt_binding(envelopes["request"], envelopes["receipt"], envelopes["authorization"])
    p.validate_ack_binding(envelopes["request"], envelopes["receipt"], envelopes["ack"])
    manifest = p.decode_base64(fixture["manifest_b64"])
    p.validate_close_manifest(envelopes["close"], envelopes["authorization"], manifest)
    if p.payload_digest(manifest) != fixture["manifest_sha256"]:
        raise p.ProtocolError("Manifest changed")
    return len(messages)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    count = verify_fixture(args.fixture)
    print(f"CROSS_LANGUAGE_VERIFIED={count}; producer={json.loads(args.fixture.read_text(encoding='utf-8'))['producer']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
