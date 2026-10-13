from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from protocol_v2 import canonical_bytes, sign_payload
from pos_desktop.config import PosConfig
from pos_desktop.key_store import PosKeyStore


@dataclass(frozen=True)
class BackendSession:
    access_token: str
    user_id: int


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
        for wallet_key in self._get("/api/keys/trusted/wallet", session.access_token):
            self.key_store.database.trust_wallet_key(
                wallet_key["key_id"], wallet_key["fingerprint"],
                wallet_key["scope_id"], wallet_key["public_key_b64"]
            )
        return session

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

