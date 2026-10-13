from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

import models
from database import get_db
from settings import JWT_SECRET_KEY


JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME_SECONDS = 3600
security = HTTPBearer(auto_error=False)


def create_access_token(user: models.User) -> tuple[str, int]:
    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY no configurada")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_LIFETIME_SECONDS)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "role": user.role,
            "exp": int(expires_at.timestamp()),
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
    return token, TOKEN_LIFETIME_SECONDS


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[Session, Depends(get_db)],
) -> models.User:
    if not JWT_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Autenticacion no configurada")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Credenciales requeridas")
    try:
        claims = jwt.decode(credentials.credentials, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = int(claims["sub"])
        role = str(claims["role"])
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Token invalido") from exc
    user = db.get(models.User, user_id)
    if user is None or user.role != role:
        raise HTTPException(status_code=401, detail="Token invalido")
    return user


def require_role(*allowed_roles: str):
    def dependency(user: Annotated[models.User, Depends(get_current_user)]) -> models.User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Rol no autorizado")
        return user

    return dependency


class LoginThrottle:
    def __init__(self, maximum_attempts: int = 5, lock_seconds: int = 300):
        self.maximum_attempts = maximum_attempts
        self.lock_seconds = lock_seconds
        self._failures: dict[str, tuple[int, datetime]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        with self._lock:
            attempts, last_failure = self._failures.get(key, (0, current))
            if attempts < self.maximum_attempts:
                return
            if current - last_failure >= timedelta(seconds=self.lock_seconds):
                self._failures.pop(key, None)
                return
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Demasiados intentos fallidos")

    def fail(self, key: str, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        with self._lock:
            attempts, _ = self._failures.get(key, (0, current))
            self._failures[key] = (attempts + 1, current)

    def succeed(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
