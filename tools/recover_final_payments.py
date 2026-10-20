"""Diagnose, then optionally restore a proven ACCEPTED row downgraded by old sync code.

This tool never adjusts balances, commitments, ledger entries, signatures, or review flags.
Stop the server before using --apply. The default mode opens the database read-only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from protocol_v3 import (
    MessageType, parse_signed_envelope, payload_digest, public_key_fingerprint,
    decode_base64, validate_ack_binding, validate_receipt_binding,
    verify_pos_signer, validate_payload,
)


def _trust(path: Path) -> dict[tuple[str, str], str]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("El inventario publico debe ser una lista")
    trusted = {}
    for item in records:
        key = (item["key_id"], item["fingerprint"])
        public = item["public_key_b64"]
        if public_key_fingerprint(decode_base64(public)) != key[1] or key in trusted:
            raise ValueError("Inventario publico contradictorio")
        trusted[key] = public
    return trusted


def _one(db: sqlite3.Connection, sql: str, params: tuple):
    return db.execute(sql, params).fetchone()


def _signed(wire: bytes, kind: MessageType, trusted: dict) -> object:
    envelope = parse_signed_envelope(bytes(wire))
    if validate_payload(envelope.payload) is not kind:
        raise ValueError("Tipo firmado incompatible")
    payload = envelope.payload
    public = trusted.get((payload["issuer_key_id"], payload["issuer_key_fingerprint"]))
    if public is None or not envelope.verify(public):
        raise ValueError("Emisor historico desconocido o firma invalida")
    return envelope


def _eligible(db: sqlite3.Connection, operation_id: str, trusted: dict) -> bool:
    payment = _one(db, "SELECT * FROM offline_payments_v2 WHERE operation_id=?", (operation_id,))
    if payment is None or payment["state"] != "PENDING_REVIEW" or payment["rejection_code"] not in {
        "CONTENT_MISMATCH", "ACK_MISMATCH"
    } or payment["applied_at"] is None or payment["ack_envelope"] is None:
        return False
    resolution_row = _one(db, "SELECT * FROM offline_payment_resolutions WHERE operation_id=?",
                          (operation_id,))
    if resolution_row is None or resolution_row["status"] != "ACCEPTED" or resolution_row["revision"] != 1:
        return False
    commitment = _one(db, "SELECT * FROM offline_commitments WHERE authorization_id=?",
                      (payment["authorization_id"],))
    if commitment is None or commitment["wallet_id"] != payment["wallet_id"] or commitment["authorization_envelope"] is None:
        return False
    try:
        grant = _signed(commitment["authorization_envelope"], MessageType.OFFLINE_AUTHORIZATION, trusted)
        resolution = _signed(resolution_row["resolution_envelope"], MessageType.PAYMENT_RESOLUTION, trusted)
        request = parse_signed_envelope(bytes(payment["request_envelope"]))
        receipt = parse_signed_envelope(bytes(payment["receipt_envelope"]))
        ack = parse_signed_envelope(bytes(payment["ack_envelope"]))
        validate_receipt_binding(request, receipt, grant)
        validate_ack_binding(request, receipt, ack)
        if (request.payload["operation_id"] != operation_id
                or request.payload["merchant_id"] != payment["merchant_id"]
                or request.payload["terminal_id"] != payment["terminal_id"]
                or request.payload["amount_cents"] != payment["amount_cents"]
                or request.payload["currency"] != payment["currency"]
                or request.payload["nonce"] != payment["nonce"]
                or receipt.payload["wallet_id"] != payment["wallet_id"]
                or receipt.payload["offline_authorization_id"] != payment["authorization_id"]
                or grant.payload["authorization_id"] != payment["authorization_id"]
                or grant.payload["wallet_id"] != payment["wallet_id"]):
            return False
        terminal = _one(db, "SELECT * FROM terminals WHERE id=?", (payment["terminal_id"],))
        pos_key = _one(db, "SELECT * FROM registered_keys WHERE key_id=?",
                       (request.payload["pos_key_id"],))
        wallet_key = _one(db, "SELECT * FROM registered_keys WHERE key_id=?",
                          (grant.payload["wallet_key_id"],))
        if (terminal is None or pos_key is None or wallet_key is None
                or pos_key["purpose"] != "pos" or pos_key["terminal_id"] != terminal["id"]
                or wallet_key["purpose"] != "wallet" or wallet_key["wallet_id"] != payment["wallet_id"]
                or wallet_key["public_key_b64"] != grant.payload["wallet_public_key_b64"]
                or wallet_key["fingerprint"] != grant.payload["wallet_key_fingerprint"]
                or not verify_pos_signer(request, pos_key["public_key_b64"], pos_key["key_id"],
                                         pos_key["fingerprint"], terminal["merchant_id"], terminal["id"])
                or not verify_pos_signer(ack, pos_key["public_key_b64"], pos_key["key_id"],
                                         pos_key["fingerprint"], terminal["merchant_id"], terminal["id"])
                or not receipt.verify(wallet_key["public_key_b64"])):
            return False
        expected = {
            "operation_id": operation_id, "wallet_id": payment["wallet_id"],
            "merchant_id": payment["merchant_id"], "terminal_id": payment["terminal_id"],
            "amount_cents": payment["amount_cents"], "currency": payment["currency"],
            "offline_authorization_id": payment["authorization_id"],
            "authorization_digest": payload_digest(grant),
            "request_digest": payload_digest(request), "receipt_digest": payload_digest(receipt),
            "operation_status": "ACCEPTED", "resolution_revision": 1,
        }
        if any(resolution.payload.get(field) != value for field, value in expected.items()):
            return False
        applied = datetime.fromisoformat(str(payment["applied_at"]))
        if applied.tzinfo is None:
            applied = applied.replace(tzinfo=timezone.utc)
        resolved = datetime.fromisoformat(resolution.payload["resolved_at"].replace("Z", "+00:00"))
        if applied.astimezone(timezone.utc).replace(microsecond=0) != resolved:
            return False
        index = receipt.payload["issuance_index"]
        emission = _one(db, "SELECT * FROM offline_commitment_emissions WHERE operation_id=?",
                        (operation_id,))
        if (emission is None or emission["authorization_id"] != payment["authorization_id"]
                or emission["issuance_index"] != index or emission["amount_cents"] != payment["amount_cents"]):
            return False
        collision = _one(db, "SELECT COUNT(DISTINCT operation_id) AS n FROM offline_commitment_claims WHERE authorization_id=? AND issuance_index=?",
                         (payment["authorization_id"], index))
        if collision is None or collision["n"] != 1:
            return False
        merchant_wallet = _one(db, "SELECT id FROM wallets WHERE user_id=?",
                               (terminal["merchant_user_id"],))
        if merchant_wallet is None:
            return False
        ledger = db.execute("SELECT entry_type, wallet_id, delta_cents FROM ledger_entries WHERE operation_id=?",
                            (operation_id,)).fetchall()
        expected_ledger = {("DEBIT", payment["wallet_id"], -payment["amount_cents"]),
                           ("CREDIT", merchant_wallet["id"], payment["amount_cents"])}
        return len(ledger) == 2 and {(r["entry_type"], r["wallet_id"], r["delta_cents"]) for r in ledger} == expected_ledger
    except (KeyError, ValueError, TypeError, OverflowError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--issuer-trust-json", type=Path, required=True,
                        help="Inventario publico fijado externamente; nunca clave privada")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    source = args.database.resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        parser.error("Seleccione explicitamente un archivo SQLite existente")
    trusted = _trust(args.issuer_trust_json.resolve(strict=True))
    uri = "file:" + quote(source.as_posix(), safe="/:\\") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as read:
        read.row_factory = sqlite3.Row
        candidates = [r[0] for r in read.execute(
            "SELECT operation_id FROM offline_payments_v2 WHERE state='PENDING_REVIEW' "
            "AND rejection_code IN ('CONTENT_MISMATCH','ACK_MISMATCH') ORDER BY operation_id"
        )]
        repairable = [item for item in candidates if _eligible(read, item, trusted)]
        print(f"Candidatas: {len(candidates)}; reparables con evidencia completa: {len(repairable)}; "
              f"requieren revision: {len(candidates) - len(repairable)}")
        if not args.apply:
            return
        if args.backup_dir is None:
            parser.error("--apply exige --backup-dir y servidor detenido")
        backup_dir = args.backup_dir.resolve(strict=True)
        if not backup_dir.is_dir() or backup_dir == source.parent:
            parser.error("La copia debe guardarse en un directorio distinto del origen")
        backup = backup_dir / (source.stem + "-antes-C12-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".db")
        if backup.exists():
            parser.error("La copia de seguridad ya existe")
        with closing(sqlite3.connect(backup)) as target:
            read.backup(target)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("La copia no supero la comprobacion SQLite")
    with closing(sqlite3.connect(source)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        changed = 0
        for operation_id in repairable:
            if not _eligible(db, operation_id, trusted):
                continue
            updated = db.execute(
                "UPDATE offline_payments_v2 SET state='ACCEPTED', rejection_code=NULL "
                "WHERE operation_id=? AND state='PENDING_REVIEW' "
                "AND rejection_code IN ('CONTENT_MISMATCH','ACK_MISMATCH')", (operation_id,)
            )
            changed += updated.rowcount
        db.commit()
    print(f"Filas restauradas: {changed}. La marca de revision de billetera permanece intacta.")


if __name__ == "__main__":
    main()
