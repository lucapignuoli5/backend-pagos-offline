import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

import auth
import main
import models
import schemas
from auth import LoginThrottle
from database import Base


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.directory.name) / 'auth.sqlite'}")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = models.User(
            id=1,
            nombre="cliente",
            saldo_real=Decimal("100.00"),
            password_hash=main.hash_password("password-for-test"),
            role="cliente",
        )
        self.db.add(self.user)
        self.db.commit()
        self.previous_main_secret = main.JWT_SECRET_KEY
        self.previous_auth_secret = auth.JWT_SECRET_KEY
        main.JWT_SECRET_KEY = "test-only-secret-with-sufficient-length"
        auth.JWT_SECRET_KEY = main.JWT_SECRET_KEY
        main.LOGIN_THROTTLE = LoginThrottle(maximum_attempts=5, lock_seconds=300)

    def tearDown(self):
        main.JWT_SECRET_KEY = self.previous_main_secret
        auth.JWT_SECRET_KEY = self.previous_auth_secret
        self.db.close()
        self.engine.dispose()
        self.directory.cleanup()

    def test_login_token_contains_current_role(self):
        response = main.login_usuario(
            schemas.LoginRequest(usuario="cliente", password="password-for-test"),
            self._request("127.0.0.1"),
            self.db,
        )
        claims = jwt.decode(response["access_token"], auth.JWT_SECRET_KEY, algorithms=[auth.JWT_ALGORITHM])
        self.assertEqual(claims["sub"], "1")
        self.assertEqual(claims["role"], "cliente")
        self.assertEqual(response["user_id"], 1)
        self.assertEqual(response["wallet_id"], "wallet-1")

    def test_throttle_is_scoped_and_expires(self):
        throttle = LoginThrottle(maximum_attempts=2, lock_seconds=60)
        now = datetime(2026, 10, 13, tzinfo=timezone.utc)
        throttle.fail("ip:user-a", now)
        throttle.fail("ip:user-a", now)
        with self.assertRaises(HTTPException) as blocked:
            throttle.check("ip:user-a", now)
        self.assertEqual(blocked.exception.status_code, 429)
        throttle.check("ip:user-b", now)
        throttle.check("ip:user-a", now + timedelta(seconds=61))

    def test_validation_response_does_not_echo_password(self):
        secret_value = "password-that-must-not-be-returned"
        error = RequestValidationError(
            [
                {
                    "type": "string_too_short",
                    "loc": ("body", "password"),
                    "msg": "String should have at least 1 character",
                    "input": secret_value,
                    "ctx": {"min_length": 1},
                }
            ]
        )
        response = asyncio.run(main.validation_exception_handler(self._request("127.0.0.1"), error))
        self.assertNotIn(secret_value, response.body.decode("utf-8"))
        body = json.loads(response.body)
        self.assertEqual(body["detail"][0]["loc"], ["body", "password"])

    @staticmethod
    def _request(host: str) -> Request:
        return Request({"type": "http", "method": "POST", "path": "/api/login", "headers": [], "client": (host, 1234)})


if __name__ == "__main__":
    unittest.main()
