from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from pos_desktop.database import PosDatabase, PosOperation


class SyncBackend(Protocol):
    def sync_operations(self, access_token: str, operations: list[dict]) -> list[dict]: ...


class PosSyncService:
    VALID_RESULTS = {"ACCEPTED", "REJECTED", "CONFLICT", "PENDING_EVIDENCE", "RETRYABLE_ERROR"}

    def __init__(
        self, database: PosDatabase, backend: SyncBackend,
        now=lambda: datetime.now(timezone.utc),
    ):
        self.database = database
        self.backend = backend
        self.now = now
        self.owner = str(uuid.uuid4())

    def sync_due(self, access_token: str, limit: int = 100) -> dict[str, int]:
        instant = self.now().astimezone(timezone.utc).replace(microsecond=0)
        try:
            if not self.database.try_acquire_sync_lock(
                self.owner, self._timestamp(instant), self._timestamp(instant + timedelta(minutes=5))
            ):
                return {"BUSY": 1}
            candidates = self.database.list_sync_candidates(self._timestamp(instant), limit)
            if not candidates:
                return {}
            evidence = [self._evidence(operation) for operation in candidates]
            try:
                raw_results = self.backend.sync_operations(access_token, evidence)
            except Exception:
                for operation in candidates:
                    self._retry(operation, "NETWORK_ERROR", instant)
                raise

            by_id: dict[str, dict] = {}
            candidate_ids = {item.operation_id for item in candidates}
            for result in raw_results:
                operation_id = result.get("operation_id")
                status = result.get("status")
                if operation_id not in candidate_ids or operation_id in by_id or status not in self.VALID_RESULTS:
                    continue
                by_id[operation_id] = result

            summary: dict[str, int] = {}
            for operation in candidates:
                result = by_id.get(operation.operation_id)
                if result is None:
                    self._retry(operation, "MISSING_RESULT", instant)
                    summary["RETRYABLE_ERROR"] = summary.get("RETRYABLE_ERROR", 0) + 1
                    continue
                status = result["status"]
                code = result.get("code")
                next_at = None
                if status in {"PENDING_EVIDENCE", "RETRYABLE_ERROR"}:
                    next_at = self._timestamp(instant + self._backoff(operation.sync_attempts + 1))
                self.database.apply_sync_result(
                    operation.operation_id, status, code, self._timestamp(instant), next_at
                )
                summary[status] = summary.get(status, 0) + 1
            return summary
        finally:
            self.database.release_sync_lock(self.owner)

    @staticmethod
    def _evidence(operation: PosOperation) -> dict:
        if (operation.authorization_envelope is None or operation.receipt_envelope is None
                or operation.ack_envelope is None):
            raise ValueError("El POS no puede conciliar evidencia incompleta como aceptada")
        return {
            "operation_id": operation.operation_id,
            "request_envelope_b64": base64.b64encode(operation.request_envelope).decode("ascii"),
            "authorization_envelope_b64": base64.b64encode(operation.authorization_envelope).decode("ascii"),
            "receipt_envelope_b64": base64.b64encode(operation.receipt_envelope).decode("ascii"),
            "ack_envelope_b64": base64.b64encode(operation.ack_envelope).decode("ascii"),
        }

    def _retry(self, operation: PosOperation, code: str, instant: datetime) -> None:
        next_at = instant + self._backoff(operation.sync_attempts + 1)
        self.database.apply_sync_result(
            operation.operation_id, "RETRYABLE_ERROR", code,
            self._timestamp(instant), self._timestamp(next_at),
        )

    @staticmethod
    def _backoff(attempt: int) -> timedelta:
        return timedelta(seconds=min(15 * (2 ** max(attempt - 1, 0)), 3600))

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

