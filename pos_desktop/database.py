from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PosOperation:
    operation_id: str
    merchant_id: str
    terminal_id: str
    amount_cents: int
    nonce: str
    request_envelope: bytes
    authorization_envelope: bytes | None
    receipt_envelope: bytes | None
    ack_envelope: bytes | None
    resolution_envelope: bytes | None
    resolution_recovery_status: str
    state: str
    created_at: str
    updated_at: str
    sync_attempts: int
    next_sync_at: str | None
    last_sync_error: str | None


class PosDatabase:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def migrate(self) -> None:
        with closing(self.connect()) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 7:
                raise RuntimeError("La base POS fue creada por una version mas nueva")
            if version == 0:
                db.executescript(
                    """
                    BEGIN IMMEDIATE;
                    CREATE TABLE pos_identity (
                        key_id TEXT PRIMARY KEY,
                        public_key_b64 TEXT NOT NULL,
                        fingerprint TEXT NOT NULL UNIQUE,
                        protected_private_key BLOB NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE trusted_wallet_keys (
                        key_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL UNIQUE,
                        wallet_id TEXT NOT NULL,
                        public_key_b64 TEXT NOT NULL,
                        revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
                    );
                    CREATE TABLE operations (
                        operation_id TEXT PRIMARY KEY,
                        merchant_id TEXT NOT NULL,
                        terminal_id TEXT NOT NULL,
                        amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                        nonce TEXT NOT NULL UNIQUE,
                        request_envelope BLOB NOT NULL,
                        receipt_envelope BLOB,
                        ack_envelope BLOB,
                        state TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                        ,sync_attempts INTEGER NOT NULL DEFAULT 0
                        ,next_sync_at TEXT
                        ,last_sync_error TEXT
                    );
                    CREATE INDEX index_operations_state_updated_at ON operations(state, updated_at);
                    PRAGMA user_version=2;
                    COMMIT;
                    """
                )
                version = 2
            if version == 1:
                db.executescript(
                    """
                    BEGIN IMMEDIATE;
                    ALTER TABLE operations ADD COLUMN sync_attempts INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE operations ADD COLUMN next_sync_at TEXT;
                    ALTER TABLE operations ADD COLUMN last_sync_error TEXT;
                    PRAGMA user_version=2;
                    COMMIT;
                    """
                )
                version = 2
            if version == 2:
                db.executescript(
                    """
                    BEGIN IMMEDIATE;
                    CREATE TABLE pos_profile (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        user_id INTEGER NOT NULL,
                        merchant_id TEXT NOT NULL,
                        terminal_id TEXT NOT NULL,
                        key_id TEXT NOT NULL,
                        provisioned_at TEXT NOT NULL
                    );
                    CREATE TABLE sync_lock (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        owner TEXT NOT NULL,
                        expires_at TEXT NOT NULL
                    );
                    PRAGMA user_version=3;
                    COMMIT;
                    """
                )
                version = 3
            if version == 3:
                db.executescript(
                    """
                    BEGIN IMMEDIATE;
                    ALTER TABLE operations ADD COLUMN authorization_envelope BLOB;
                    PRAGMA user_version=4;
                    COMMIT;
                    """
                )
                version = 4
            if version == 4:
                db.executescript(
                    """
                    BEGIN IMMEDIATE;
                    CREATE TABLE trusted_issuer_keys (
                        key_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                        public_key_b64 TEXT NOT NULL,
                        PRIMARY KEY(key_id, fingerprint)
                    );
                    PRAGMA user_version=5;
                    COMMIT;
                    """
                )
                version = 5
            if version == 5:
                db.executescript(
                    """
                    BEGIN IMMEDIATE;
                    ALTER TABLE operations ADD COLUMN resolution_envelope BLOB;
                    PRAGMA user_version=6;
                    COMMIT;
                    """
                )
                version = 6
            if version == 6:
                db.executescript(
                    """
                    BEGIN IMMEDIATE;
                    ALTER TABLE operations ADD COLUMN resolution_recovery_status TEXT NOT NULL DEFAULT 'PENDING';
                    UPDATE operations SET resolution_recovery_status='COMPLETE' WHERE resolution_envelope IS NOT NULL;
                    PRAGMA user_version=7;
                    COMMIT;
                    """
                )

    def trust_issuer_key(self, key_id, fingerprint, public_key_b64):
        from protocol_v3 import decode_base64, public_key_fingerprint
        if public_key_fingerprint(decode_base64(public_key_b64)) != fingerprint:
            raise ValueError("Issuer fingerprint mismatch")
        with closing(self.connect()) as db:
            db.execute(
                "INSERT OR IGNORE INTO trusted_issuer_keys VALUES (?, ?, ?)",
                (key_id, fingerprint, public_key_b64),
            )

    def get_issuer_key(self, key_id, fingerprint):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT public_key_b64 FROM trusted_issuer_keys WHERE key_id=? AND fingerprint=?",
                (key_id, fingerprint),
            ).fetchone()
            return row[0] if row else None

    def save_profile(
        self, user_id: int, merchant_id: str, terminal_id: str, key_id: str, provisioned_at: str,
    ) -> None:
        if not merchant_id or not terminal_id or not key_id:
            raise ValueError("Perfil POS incompleto")
        with closing(self.connect()) as db:
            db.execute(
                """INSERT INTO pos_profile VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET
                     user_id=excluded.user_id, merchant_id=excluded.merchant_id,
                     terminal_id=excluded.terminal_id, key_id=excluded.key_id,
                     provisioned_at=excluded.provisioned_at""",
                (user_id, merchant_id, terminal_id, key_id, provisioned_at),
            )

    def get_profile(self) -> sqlite3.Row | None:
        with closing(self.connect()) as db:
            return db.execute("SELECT * FROM pos_profile WHERE singleton=1").fetchone()

    def try_acquire_sync_lock(self, owner: str, now: str, expires_at: str) -> bool:
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner, expires_at FROM sync_lock WHERE singleton=1").fetchone()
            if row is not None and row["owner"] != owner and row["expires_at"] > now:
                db.rollback()
                return False
            db.execute(
                """INSERT INTO sync_lock VALUES (1, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET owner=excluded.owner, expires_at=excluded.expires_at""",
                (owner, expires_at),
            )
            db.commit()
            return True

    def release_sync_lock(self, owner: str) -> None:
        with closing(self.connect()) as db:
            db.execute("DELETE FROM sync_lock WHERE singleton=1 AND owner=?", (owner,))

    def save_identity(
        self, key_id: str, public_key_b64: str, fingerprint: str,
        protected_private_key: bytes, created_at: str,
    ) -> None:
        with closing(self.connect()) as db:
            db.execute(
                "INSERT INTO pos_identity VALUES (?, ?, ?, ?, ?)",
                (key_id, public_key_b64, fingerprint, protected_private_key, created_at),
            )

    def get_identity(self, key_id: str) -> sqlite3.Row | None:
        with closing(self.connect()) as db:
            return db.execute("SELECT * FROM pos_identity WHERE key_id=?", (key_id,)).fetchone()

    def trust_wallet_key(
        self, key_id: str, fingerprint: str, wallet_id: str, public_key_b64: str,
    ) -> None:
        with closing(self.connect()) as db:
            db.execute(
                """INSERT INTO trusted_wallet_keys(
                     key_id, fingerprint, wallet_id, public_key_b64, revoked
                   ) VALUES (?, ?, ?, ?, 0)
                   ON CONFLICT(key_id) DO UPDATE SET
                     fingerprint=excluded.fingerprint,
                     wallet_id=excluded.wallet_id,
                     public_key_b64=excluded.public_key_b64,
                     revoked=0""",
                (key_id, fingerprint, wallet_id, public_key_b64),
            )

    def resolve_wallet_key(self, key_id: str, fingerprint: str, wallet_id: str) -> str | None:
        with closing(self.connect()) as db:
            row = db.execute(
                """SELECT public_key_b64 FROM trusted_wallet_keys
                   WHERE key_id=? AND fingerprint=? AND wallet_id=? AND revoked=0""",
                (key_id, fingerprint, wallet_id),
            ).fetchone()
            return row[0] if row else None

    def insert_request(self, payload: dict, envelope: bytes, now: str) -> bool:
        with closing(self.connect()) as db:
            existing = db.execute(
                "SELECT request_envelope FROM operations WHERE operation_id=?",
                (payload["operation_id"],),
            ).fetchone()
            if existing:
                if bytes(existing[0]) != envelope:
                    raise ValueError("operation_id ya existe con otra solicitud")
                return False
            db.execute(
                """INSERT INTO operations(
                     operation_id, merchant_id, terminal_id, amount_cents, nonce,
                     request_envelope, state, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 'REQUEST_CREATED', ?, ?)""",
                (
                    payload["operation_id"], payload["merchant_id"], payload["terminal_id"],
                    payload["amount_cents"], payload["nonce"], envelope, now, now,
                ),
            )
            return True

    def mark_request_delivered(self, operation_id: str, now: str) -> None:
        self._transition(operation_id, {"REQUEST_CREATED", "REQUEST_DELIVERED"}, "REQUEST_DELIVERED", now)

    def set_authorization(self, operation_id: str, envelope: bytes, now: str) -> None:
        with closing(self.connect()) as db:
            result = db.execute(
                """UPDATE operations SET authorization_envelope=?, updated_at=?
                   WHERE operation_id=? AND state IN ('REQUEST_DELIVERED','WAITING_CONFIRMATION')
                     AND (authorization_envelope IS NULL OR authorization_envelope=?)""",
                (envelope, now, operation_id, envelope),
            )
            if result.rowcount != 1:
                raise ValueError("Autorizacion conflictiva para la operacion")

    def accept_receipt_and_ack(
        self, operation_id: str, receipt: bytes, ack: bytes, now: str,
    ) -> None:
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT receipt_envelope, ack_envelope, state FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Operacion POS inexistente")
            if row[0] is not None:
                if bytes(row[0]) != receipt or bytes(row[1]) != ack:
                    raise ValueError("Evidencia conflictiva para la operacion")
                db.commit()
                return
            if row["state"] not in {"REQUEST_DELIVERED", "WAITING_CONFIRMATION"}:
                raise ValueError("Estado POS incompatible con la aceptacion")
            db.execute(
                """UPDATE operations SET receipt_envelope=?, ack_envelope=?,
                   state='LOCALLY_ACCEPTED', updated_at=? WHERE operation_id=?""",
                (receipt, ack, now, operation_id),
            )
            db.commit()

    def mark_waiting(self, operation_id: str, now: str) -> None:
        self._transition(
            operation_id, {"REQUEST_DELIVERED", "WAITING_CONFIRMATION"},
            "WAITING_CONFIRMATION", now,
        )

    def get_operation(self, operation_id: str) -> PosOperation | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            return PosOperation(**dict(row)) if row else None

    def list_operations(self, limit: int = 100) -> list[PosOperation]:
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT * FROM operations ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [PosOperation(**dict(row)) for row in rows]

    def list_sync_candidates(self, now: str, limit: int = 100) -> list[PosOperation]:
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT * FROM operations
                   WHERE state='LOCALLY_ACCEPTED' AND authorization_envelope IS NOT NULL
                     AND (NOT EXISTS (SELECT 1 FROM pos_profile)
                          OR terminal_id=(SELECT terminal_id FROM pos_profile WHERE singleton=1))
                     AND (next_sync_at IS NULL OR next_sync_at <= ?)
                   ORDER BY updated_at ASC LIMIT ?""",
                (now, limit),
            ).fetchall()
            return [PosOperation(**dict(row)) for row in rows]

    def apply_sync_result(
        self, operation_id: str, status: str, code: str | None,
        now: str, next_sync_at: str | None = None,
        resolution_envelope: bytes | None = None,
    ) -> None:
        if status in {"ACCEPTED", "REJECTED"} and not resolution_envelope:
            raise ValueError("Resultado final sin resolucion firmada")
        state = {
            "ACCEPTED": "SYNCED",
            "REJECTED": "REJECTED",
            "CONFLICT": "CONFLICT",
        }.get(status, "LOCALLY_ACCEPTED")
        with closing(self.connect()) as db:
            result = db.execute(
                """UPDATE operations SET state=?, updated_at=?,
                   sync_attempts=CASE WHEN ? IN ('PENDING_EVIDENCE','RETRYABLE_ERROR')
                                      THEN sync_attempts + 1 ELSE sync_attempts END,
                   next_sync_at=?, last_sync_error=?,
                   resolution_envelope=CASE WHEN ? IN ('ACCEPTED','REJECTED')
                                            THEN COALESCE(resolution_envelope, ?) ELSE resolution_envelope END,
                   resolution_recovery_status=CASE WHEN ? IN ('ACCEPTED','REJECTED')
                                            THEN 'COMPLETE' ELSE resolution_recovery_status END
                   WHERE operation_id=? AND state='LOCALLY_ACCEPTED'""",
                (state, now, status, next_sync_at, code, status, resolution_envelope, status, operation_id),
            )
            if result.rowcount != 1:
                raise ValueError("Operacion POS no disponible para conciliacion")

    def list_resolution_recovery_candidates(self, now: str, limit: int = 100) -> list[PosOperation]:
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT * FROM operations WHERE state IN ('SYNCED','REJECTED')
                   AND resolution_envelope IS NULL AND authorization_envelope IS NOT NULL
                   AND resolution_recovery_status='PENDING'
                   AND (NOT EXISTS (SELECT 1 FROM pos_profile)
                        OR terminal_id=(SELECT terminal_id FROM pos_profile WHERE singleton=1))
                   AND (next_sync_at IS NULL OR next_sync_at <= ?)
                   ORDER BY updated_at ASC LIMIT ?""", (now, min(limit, 100))
            ).fetchall()
            return [PosOperation(**dict(row)) for row in rows]

    def attach_final_resolution(self, operation_id: str, resolution: bytes) -> None:
        with closing(self.connect()) as db:
            result = db.execute(
                """UPDATE operations SET resolution_envelope=?, resolution_recovery_status='COMPLETE',
                   next_sync_at=NULL WHERE operation_id=? AND state IN ('SYNCED','REJECTED')
                   AND resolution_envelope IS NULL AND resolution_recovery_status='PENDING'""",
                (resolution, operation_id),
            )
            if result.rowcount != 1:
                raise ValueError("La operacion POS cambio durante la recuperacion")

    def schedule_resolution_recovery(self, operation_id: str, next_at: str) -> None:
        with closing(self.connect()) as db:
            db.execute(
                """UPDATE operations SET sync_attempts=sync_attempts+1, next_sync_at=?
                   WHERE operation_id=? AND state IN ('SYNCED','REJECTED')
                   AND resolution_envelope IS NULL AND resolution_recovery_status='PENDING'""",
                (next_at, operation_id),
            )

    def flag_resolution_recovery(self, operation_id: str) -> None:
        with closing(self.connect()) as db:
            db.execute(
                """UPDATE operations SET resolution_recovery_status='ATTENTION_REQUIRED', next_sync_at=NULL
                   WHERE operation_id=? AND state IN ('SYNCED','REJECTED') AND resolution_envelope IS NULL""",
                (operation_id,),
            )

    def retry_attention_resolutions(self) -> None:
        with closing(self.connect()) as db:
            db.execute(
                """UPDATE operations SET resolution_recovery_status='PENDING'
                   WHERE resolution_recovery_status='ATTENTION_REQUIRED'
                   AND state IN ('SYNCED','REJECTED') AND resolution_envelope IS NULL"""
            )

    def _transition(self, operation_id: str, allowed: set[str], state: str, now: str) -> None:
        placeholders = ",".join("?" for _ in allowed)
        with closing(self.connect()) as db:
            result = db.execute(
                f"UPDATE operations SET state=?, updated_at=? WHERE operation_id=? AND state IN ({placeholders})",
                (state, now, operation_id, *sorted(allowed)),
            )
            if result.rowcount != 1:
                raise ValueError("Transicion de estado POS invalida")

