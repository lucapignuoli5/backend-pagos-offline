import json
from pathlib import Path
from protocol_v3 import decode_base64, public_key_fingerprint


def provision_pinned_keys(database, config):
    """Only explicit local configuration can add issuer trust."""
    records = []
    if config.issuer_public_key_b64 and config.issuer_key_id:
        records.append(dict(
            key_id=config.issuer_key_id, public_key_b64=config.issuer_public_key_b64,
            fingerprint=public_key_fingerprint(decode_base64(config.issuer_public_key_b64)),
        ))
    if config.issuer_trust_path:
        records.extend(json.loads(Path(config.issuer_trust_path).read_text(encoding="utf-8")))
    for record in records:
        database.trust_issuer_key(record["key_id"], record["fingerprint"], record["public_key_b64"])


def public_key(database, config, payload):
    key = database.get_issuer_key(payload["issuer_key_id"], payload["issuer_key_fingerprint"])
    if key is None:
        provision_pinned_keys(database, config)
        key = database.get_issuer_key(payload["issuer_key_id"], payload["issuer_key_fingerprint"])
    if key is None:
        raise ValueError("Unknown issuer; configure pinned public inventory")
    return key
