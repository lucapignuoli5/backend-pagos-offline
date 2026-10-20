from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from protocol_v2 import canonical_bytes, sign_payload
from protocol_v3 import MessageType, decode_base64, parse_signed_envelope, payload_digest, public_key_fingerprint, validate_payload
from pos_desktop.config import PosConfig
from pos_desktop.key_store import PosKeyStore
from pos_desktop.issuer_trust import public_key as issuer_public_key


@dataclass(frozen=True)
class BackendSession:
    access_token: str
    user_id: int
    merchant_id: str | None = None
    terminal_id: str | None = None
    key_id: str | None = None


class PosBackendClient:
    def __init__(self, config: PosConfig, key_store: PosKeyStore, timeout_seconds: float = 10):
        self.config = config
        self.key_store = key_store
        self.timeout_seconds = timeout_seconds

    def login_and_register_key(self, username: str, password: str) -> BackendSession:
        login = self._request("/api/login", {"usuario": username, "password": password})
        session = BackendSession(login["access_token"], int(login["user_id"]))
        private_key, public_key_b64, fingerprint = self.key_store.get_or_create(
            self.config.pos_key_id
        )
        proof = {
            "version": 2,
            "type": "key_registration",
            "key_id": self.config.pos_key_id,
            "purpose": "pos",
            "owner_user_id": session.user_id,
            "scope_id": self.config.terminal_id,
            "fingerprint": fingerprint,
            "nonce": base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("="),
            "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        proof_bytes = canonical_bytes(proof)
        registered = self._request(
            "/api/keys/register",
            {
                "public_key_b64": public_key_b64,
                "proof_payload_b64": base64.b64encode(proof_bytes).decode("ascii"),
                "proof_signature_b64": sign_payload(proof, private_key),
            },
            session.access_token,
        )
        if (
            registered.get("key_id") != self.config.pos_key_id
            or registered.get("fingerprint") != fingerprint
            or registered.get("scope_id") != self.config.terminal_id
            or registered.get("purpose") != "pos"
        ):
            raise RuntimeError("El backend devolvio una identidad POS incompatible")
        merchant_id = registered.get("merchant_id")
        if not isinstance(merchant_id, str) or not merchant_id:
            raise RuntimeError("El backend no devolvio el perfil comercial del terminal")
        self.key_store.database.save_profile(
            session.user_id,
            merchant_id,
            registered["scope_id"],
            registered["key_id"],
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for wallet_key in self._get("/api/keys/trusted/wallet", session.access_token):
            self.key_store.database.trust_wallet_key(
                wallet_key["key_id"], wallet_key["fingerprint"],
                wallet_key["scope_id"], wallet_key["public_key_b64"]
            )
        return BackendSession(
            session.access_token, session.user_id, merchant_id,
            registered["scope_id"], registered["key_id"],
        )

    def sync_operations(self, access_token: str, operations: list[dict]) -> list[dict]:
        response = self._request(
            "/api/v3/offline-payments/sync", {"operations": operations}, access_token
        )
        results = response.get("results")
        if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
            raise RuntimeError("Respuesta de conciliacion invalida")
        normalized = []
        submitted = {item.get("operation_id"): item for item in operations}
        for result in results:
            submission = result.get("submission_status")
            operation = result.get("operation_status")
            if submission == "CONFLICT":
                status = "CONFLICT"
            elif submission == "RETRYABLE_ERROR":
                status = "RETRYABLE_ERROR"
            elif submission == "INVALID_EVIDENCE":
                status = "CONFLICT"
            elif operation in {"ACCEPTED", "REJECTED"}:
                evidence = submitted.get(result.get("operation_id"))
                status = operation if result.get("final") is True and self._valid_resolution(result, evidence) else "RETRYABLE_ERROR"
            elif operation == "PENDING_EVIDENCE":
                status = operation
            elif operation == "PENDING_REVIEW":
                status = "CONFLICT"
            else:
                status = "PENDING_EVIDENCE"
            resolution = None
            if status in {"ACCEPTED", "REJECTED"}:
                resolution = base64.b64decode(result["resolution_envelope_b64"], validate=True)
            normalized.append({"operation_id": result.get("operation_id"), "status": status,
                               "code": result.get("code"), "resolution_envelope": resolution})
        return normalized

    def _valid_resolution(self, result: dict, evidence: dict | None) -> bool:
        try:
            if evidence is None:
                return False
            wire = base64.b64decode(result["resolution_envelope_b64"], validate=True)
            resolution = parse_signed_envelope(wire)
            if validate_payload(resolution.payload) is not MessageType.PAYMENT_RESOLUTION:
                return False
            request = parse_signed_envelope(base64.b64decode(evidence["request_envelope_b64"], validate=True))
            grant = parse_signed_envelope(base64.b64decode(evidence["authorization_envelope_b64"], validate=True))
            receipt = parse_signed_envelope(base64.b64decode(evidence["receipt_envelope_b64"], validate=True))
            payload = resolution.payload
            public = issuer_public_key(self.key_store.database, self.config, payload)
            return (
                resolution.verify(public)
                and payload["issuer_key_fingerprint"] == public_key_fingerprint(
                    decode_base64(public)
                )
                and payload["operation_id"] == evidence["operation_id"]
                and payload["operation_status"] == result["operation_status"]
                and payload["wallet_id"] == receipt.payload["wallet_id"]
                and payload["merchant_id"] == request.payload["merchant_id"]
                and payload["terminal_id"] == request.payload["terminal_id"]
                and payload["amount_cents"] == request.payload["amount_cents"]
                and payload["offline_authorization_id"] == receipt.payload["offline_authorization_id"]
                and payload["request_digest"] == payload_digest(request)
                and payload["authorization_digest"] == payload_digest(grant)
                and payload["receipt_digest"] == payload_digest(receipt)
            )
        except (KeyError, TypeError, ValueError):
            return False

    def get_operation_status(self, access_token: str, operation_id: str) -> dict:
        value = self._get_object(f"/api/v3/offline-payments/{operation_id}", access_token)
        if value.get("operation_id") != operation_id or not isinstance(value.get("operation_status"), str):
            raise RuntimeError("Estado de operacion invalido")
        return value

    def _get(self, path: str, token: str) -> list[dict]:
        request = Request(
            self.config.backend_url.rstrip("/") + path,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Backend rechazo la solicitud ({exc.code})") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("No se pudo completar la comunicacion con el backend") from exc
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise RuntimeError("Respuesta de claves del backend invalida")
        return value

    def _get_object(self, path: str, token: str) -> dict:
        request = Request(
            self.config.backend_url.rstrip("/") + path,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Backend rechazo la solicitud ({exc.code})") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("No se pudo completar la comunicacion con el backend") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Respuesta del backend invalida")
        return value

    def _request(self, path: str, payload: dict, token: str | None = None) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            self.config.backend_url.rstrip("/") + path,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Backend rechazo la solicitud ({exc.code})") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("No se pudo completar la comunicacion con el backend") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Respuesta del backend invalida")
        return value

