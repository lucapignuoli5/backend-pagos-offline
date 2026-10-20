from __future__ import annotations

import base64
import uuid
from urllib.error import HTTPError
from datetime import datetime, timedelta, timezone
from typing import Protocol

from pos_desktop.database import PosDatabase, PosOperation


class SyncBackend(Protocol):
    def sync_operations(self, access_token: str, operations: list[dict]) -> list[dict]: ...
    def fetch_verified_final_resolution(self, access_token: str, operation_id: str,
                                        evidence: dict, expected_status: str) -> bytes | None: ...


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

    def sync_due(self, access_token: str, limit: int = 100,
                 manual: bool = False) -> dict[str, int]:
        instant = self.now().astimezone(timezone.utc).replace(microsecond=0)
        try:
            if not self.database.try_acquire_sync_lock(
                self.owner, self._timestamp(instant), self._timestamp(instant + timedelta(minutes=5))
            ):
                return {"BUSY": 1}
            if manual:
                self.database.retry_attention_resolutions()
            candidates = self.database.list_sync_candidates(self._timestamp(instant), limit)
            if not candidates:
                return self._recover_final(access_token, instant, limit)
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
                    operation.operation_id, status, code, self._timestamp(instant), next_at,
                    result.get("resolution_envelope"),
                )
                summary[status] = summary.get(status, 0) + 1
            for status, count in self._recover_final(access_token, instant, limit).items():
                summary[status] = summary.get(status, 0) + count
            return summary
        finally:
            self.database.release_sync_lock(self.owner)

    def _recover_final(self, access_token: str, instant: datetime, limit: int) -> dict[str, int]:
        summary: dict[str, int] = {}
        for operation in self.database.list_resolution_recovery_candidates(
            self._timestamp(instant), min(limit, 100)
        ):
            expected = "ACCEPTED" if operation.state == "SYNCED" else "REJECTED"
            try:
                evidence = self._evidence(operation)
                resolution = self.backend.fetch_verified_final_resolution(
                    access_token, operation.operation_id, evidence, expected
                )
            except RuntimeError as exc:
                cause = exc.__cause__
                if isinstance(cause, HTTPError) and cause.code in {401, 403}:
                    raise
                if isinstance(cause, HTTPError) and 400 <= cause.code < 500 and cause.code not in {408, 429}:
                    self.database.flag_resolution_recovery(operation.operation_id)
                    summary["ATTENTION_REQUIRED"] = summary.get("ATTENTION_REQUIRED", 0) + 1
                else:
                    next_at = instant + self._backoff(operation.sync_attempts + 1)
                    self.database.schedule_resolution_recovery(
                        operation.operation_id, self._timestamp(next_at)
                    )
                continue
            except ValueError:
                self.database.flag_resolution_recovery(operation.operation_id)
                summary["ATTENTION_REQUIRED"] = summary.get("ATTENTION_REQUIRED", 0) + 1
                continue
            if resolution is None:
                self.database.flag_resolution_recovery(operation.operation_id)
                summary["ATTENTION_REQUIRED"] = summary.get("ATTENTION_REQUIRED", 0) + 1
            else:
                self.database.attach_final_resolution(operation.operation_id, resolution)
                summary["EVIDENCE_RECOVERED"] = summary.get("EVIDENCE_RECOVERED", 0) + 1
        return summary

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

