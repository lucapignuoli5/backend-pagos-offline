"""Pinned public issuer inventory. Never populated from HTTP responses."""
import json
import os
from pathlib import Path

from issuer_keys import IssuerIdentity
from protocol_v3 import decode_base64, public_key_fingerprint, verify_authorization


def issuer_public_key(payload):
    key_id = payload["issuer_key_id"]
    fingerprint = payload["issuer_key_fingerprint"]
    inventory_path = os.getenv("ISSUER_TRUST_PATH")
    if inventory_path:
        path = Path(inventory_path).expanduser().resolve()
        if path.is_relative_to(Path(__file__).resolve().parent):
            raise ValueError("Issuer trust inventory must be external")
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("Invalid issuer trust inventory")
        for record in records:
            public = record["public_key_b64"]
            if public_key_fingerprint(decode_base64(public)) != record["fingerprint"]:
                raise ValueError("Issuer trust fingerprint mismatch")
            if record["key_id"] == key_id and record["fingerprint"] == fingerprint:
                return public
    active = IssuerIdentity.load_external(os.environ["ISSUER_KEY_PATH"], os.environ["ISSUER_KEY_FINGERPRINT"])
    if active.key_id != key_id or active.fingerprint != fingerprint:
        raise ValueError("Unknown historical issuer")
    return active.public_key_b64


def verify_trusted_authorization(grant):
    return verify_authorization(grant, issuer_public_key(grant.payload), grant.payload["issuer_key_id"])
