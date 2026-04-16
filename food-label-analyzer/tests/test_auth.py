from __future__ import annotations

import asyncio
import importlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import IntegrityError

from app.core.error_handlers import register_exception_handlers
from app.core.errors import (
    CooldownError,
    EmailAlreadyExistsError,
    EmailDeliveryError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    PasswordResetTokenInvalidError,
    TokenInvalidError,
)
from app.core.security import hash_password
from app.models.email_verification import EmailVerification, VerificationType
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from tests.conftest import load_required_env


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return SimpleNamespace(all=lambda: self._value)


def _build_auth_app(monkeypatch: pytest.MonkeyPatch):
    load_required_env(monkeypatch)
    api_module = importlib.reload(importlib.import_module("app.api.v1.auth"))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_module.router)
    return app, api_module


def test_auth_schemas_normalize_email_and_validate_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    schema_module = importlib.reload(importlib.import_module("app.schemas.auth"))

    send_code = schema_module.SendCodeRequest(email="  USER@Example.com ")
    register = schema_module.RegisterRequest(
        email=" Another@Example.com ",
        code="123456",
        password="StrongPass123",
    )

    assert send_code.email == "user@example.com"
    assert register.email == "another@example.com"
    assert schema_module.validate_password_strength("StrongPass123") == "StrongPass123"

    with pytest.raises(ValueError):
        schema_module.validate_password_strength("weakpass")


def test_send_register_code_persists_verification_and_sets_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(None),
            _ScalarResult([]),
        ]
    )
    fake_redis = AsyncMock()
    fake_redis.set.return_value = True
    fake_send_email = AsyncMock()
    monkeypatch.setattr(service_module, "send_verification_email", fake_send_email)

    cooldown = asyncio.run(
        service_module.send_register_code("User@Example.com", fake_db, fake_redis)
    )

    assert cooldown == 60
    assert fake_db.add.call_count == 1
    verification = fake_db.add.call_args.args[0]
    assert isinstance(verification, EmailVerification)
    assert verification.email == "user@example.com"
    assert verification.type == VerificationType.REGISTER
    fake_send_email.assert_awaited_once_with("user@example.com", verification.code)
    fake_redis.set.assert_awaited_once_with(
        "cooldown:register:user@example.com", "1", ex=60, nx=True
    )
    fake_redis.delete.assert_not_awaited()


def test_send_register_code_expires_previous_active_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )
    old_code = EmailVerification(
        email="user@example.com",
        code="111111",
        type=VerificationType.REGISTER,
        expired_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(None),
            _ScalarResult([old_code]),
        ]
    )
    fake_redis = AsyncMock()
    fake_redis.set.return_value = True
    monkeypatch.setattr(service_module, "send_verification_email", AsyncMock())

    asyncio.run(
        service_module.send_register_code("User@Example.com", fake_db, fake_redis)
    )

    assert old_code.is_used is True
    new_code = fake_db.add.call_args.args[0]
    assert isinstance(new_code, EmailVerification)
    assert new_code is not old_code


def test_send_register_code_propagates_email_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(None),
            _ScalarResult([]),
        ]
    )
    fake_redis = AsyncMock()
    fake_redis.set.return_value = True
    monkeypatch.setattr(
        service_module,
        "send_verification_email",
        AsyncMock(side_effect=EmailDeliveryError()),
    )

    with pytest.raises(EmailDeliveryError):
        asyncio.run(
            service_module.send_register_code("User@Example.com", fake_db, fake_redis)
        )

    fake_redis.set.assert_awaited_once_with(
        "cooldown:register:user@example.com", "1", ex=60, nx=True
    )
    fake_redis.delete.assert_awaited_once_with("cooldown:register:user@example.com")


def test_send_register_code_tolerates_cooldown_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(None),
            _ScalarResult([]),
        ]
    )
    fake_redis = AsyncMock()
    fake_redis.set.side_effect = RedisConnectionError("redis down")
    fake_send_email = AsyncMock()
    monkeypatch.setattr(service_module, "send_verification_email", fake_send_email)

    cooldown = asyncio.run(
        service_module.send_register_code("User@Example.com", fake_db, fake_redis)
    )

    assert cooldown == 60
    fake_send_email.assert_awaited_once()
    fake_redis.set.assert_awaited_once_with(
        "cooldown:register:user@example.com", "1", ex=60, nx=True
    )
    fake_redis.delete.assert_not_awaited()


def test_send_register_code_enforces_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.execute = AsyncMock(return_value=_ScalarResult(None))
    fake_redis = AsyncMock()
    fake_redis.set.return_value = False
    fake_redis.ttl.return_value = 42
    monkeypatch.setattr(service_module, "send_verification_email", AsyncMock())

    with pytest.raises(CooldownError) as exc_info:
        asyncio.run(
            service_module.send_register_code("user@example.com", fake_db, fake_redis)
        )

    assert exc_info.value.detail == {"retry_after_seconds": 42}
    fake_redis.set.assert_awaited_once_with(
        "cooldown:register:user@example.com", "1", ex=60, nx=True
    )


def test_register_user_marks_verification_used_and_creates_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )
    verification = EmailVerification(
        email="user@example.com",
        code="123456",
        type=VerificationType.REGISTER,
        expired_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(verification),
            _ScalarResult(None),
        ]
    )

    asyncio.run(
        service_module.register_user(
            "user@example.com", "123456", "StrongPass123", fake_db
        )
    )

    created_user = fake_db.add.call_args.args[0]
    assert isinstance(created_user, User)
    assert created_user.email == "user@example.com"
    assert created_user.password_hash != "StrongPass123"
    assert verification.is_used is True


def test_register_user_translates_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )
    verification = EmailVerification(
        email="user@example.com",
        code="123456",
        type=VerificationType.REGISTER,
        expired_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock(
        side_effect=IntegrityError("insert", {}, Exception("dup"))
    )
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(verification),
            _ScalarResult(None),
        ]
    )

    with pytest.raises(EmailAlreadyExistsError):
        asyncio.run(
            service_module.register_user(
                "user@example.com", "123456", "StrongPass123", fake_db
            )
        )

    fake_db.rollback.assert_not_awaited()


def test_login_user_success_and_error_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )
    active_user = User(
        email="user@example.com",
        password_hash=hash_password("StrongPass123"),
        is_verified=True,
        is_active=True,
    )
    active_user.id = uuid.uuid4()

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(return_value=_ScalarResult(active_user))
    tokens = asyncio.run(
        service_module.login_user("user@example.com", "StrongPass123", fake_db)
    )
    assert tokens.token_type == "Bearer"
    assert tokens.access_token
    assert tokens.refresh_token

    fake_db.execute = AsyncMock(return_value=_ScalarResult(None))
    with pytest.raises(InvalidCredentialsError):
        asyncio.run(
            service_module.login_user("missing@example.com", "StrongPass123", fake_db)
        )

    unverified_user = User(
        email="user@example.com",
        password_hash=hash_password("StrongPass123"),
        is_verified=False,
        is_active=True,
    )
    fake_db.execute = AsyncMock(return_value=_ScalarResult(unverified_user))
    with pytest.raises(EmailNotVerifiedError):
        asyncio.run(
            service_module.login_user("user@example.com", "StrongPass123", fake_db)
        )


def test_refresh_tokens_rejects_non_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )
    monkeypatch.setattr(
        service_module,
        "decode_token",
        lambda token: {"sub": str(uuid.uuid4()), "type": "access"},
    )

    with pytest.raises(TokenInvalidError):
        asyncio.run(service_module.refresh_tokens("bad-token", AsyncMock()))


def test_refresh_tokens_rejects_expired_database_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )
    user_id = uuid.uuid4()
    expired_record = SimpleNamespace(
        jti="refresh-jti",
        user_id=user_id,
        revoked_at=None,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=_ScalarResult(expired_record))
    monkeypatch.setattr(
        service_module,
        "decode_token",
        lambda token: {
            "sub": str(user_id),
            "type": "refresh",
            "jti": "refresh-jti",
        },
    )

    with pytest.raises(TokenInvalidError):
        asyncio.run(service_module.refresh_tokens("expired-refresh-token", fake_db))


def test_send_reset_email_does_not_enumerate_unknown_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(return_value=_ScalarResult(None))
    fake_redis = AsyncMock()
    fake_redis.set.return_value = True

    asyncio.run(
        service_module.send_reset_email("missing@example.com", fake_db, fake_redis)
    )

    fake_db.add.assert_not_called()
    fake_redis.set.assert_awaited_once_with(
        "cooldown:reset:missing@example.com", "1", ex=60, nx=True
    )


def test_send_reset_email_swallows_delivery_failures_for_existing_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    user = User(
        email="user@example.com",
        password_hash="hashed",
        is_verified=True,
        is_active=True,
    )
    user.id = uuid.uuid4()

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(user),
            _ScalarResult([]),
        ]
    )
    fake_redis = AsyncMock()
    fake_redis.set.return_value = True
    monkeypatch.setattr(
        service_module,
        "dispatch_reset_email",
        AsyncMock(side_effect=EmailDeliveryError()),
    )

    asyncio.run(
        service_module.send_reset_email("user@example.com", fake_db, fake_redis)
    )

    fake_db.add.assert_called_once()
    fake_redis.set.assert_awaited_once_with(
        "cooldown:reset:user@example.com", "1", ex=60, nx=True
    )
    fake_redis.delete.assert_not_awaited()


def test_send_reset_email_expires_previous_active_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    user = User(
        email="user@example.com",
        password_hash="hashed",
        is_verified=True,
        is_active=True,
    )
    user.id = uuid.uuid4()
    old_token = PasswordResetToken(
        user_id=user.id,
        token="old-token",
        expired_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    another_old_token = PasswordResetToken(
        user_id=user.id,
        token="another-old-token",
        expired_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(user),
            _ScalarResult([old_token, another_old_token]),
        ]
    )
    fake_redis = AsyncMock()
    fake_redis.set.return_value = True
    dispatch_reset_email = AsyncMock()
    monkeypatch.setattr(service_module, "dispatch_reset_email", dispatch_reset_email)

    asyncio.run(
        service_module.send_reset_email("user@example.com", fake_db, fake_redis)
    )

    assert old_token.is_used is True
    assert another_old_token.is_used is True
    new_reset_token = fake_db.add.call_args.args[0]
    assert isinstance(new_reset_token, PasswordResetToken)
    assert new_reset_token.token not in {old_token.token, another_old_token.token}
    dispatch_reset_email.assert_awaited_once_with(
        "user@example.com",
        new_reset_token.token,
    )


def test_reset_password_marks_token_used(monkeypatch: pytest.MonkeyPatch) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    user = User(
        email="user@example.com",
        password_hash=hash_password("OldPass123"),
        is_verified=True,
        is_active=True,
    )
    user.id = uuid.uuid4()
    reset_token = PasswordResetToken(
        user_id=user.id,
        token="reset-token",
        expired_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(reset_token),
            _ScalarResult(user),
            _ScalarResult([]),
            _ScalarResult([]),
        ],
    )

    asyncio.run(service_module.reset_password("reset-token", "StrongPass123", fake_db))

    assert reset_token.is_used is True
    assert user.password_hash != hash_password("OldPass123")


def test_reset_password_expires_other_reset_tokens_and_revokes_refresh_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    user = User(
        email="user@example.com",
        password_hash=hash_password("OldPass123"),
        is_verified=True,
        is_active=True,
    )
    user.id = uuid.uuid4()
    reset_token = PasswordResetToken(
        user_id=user.id,
        token="reset-token",
        expired_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    reset_token.id = uuid.uuid4()
    sibling_token = PasswordResetToken(
        user_id=user.id,
        token="sibling-token",
        expired_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    sibling_token.id = uuid.uuid4()
    refresh_token = SimpleNamespace(revoked_at=None)

    fake_db = AsyncMock()
    fake_db.add = Mock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(reset_token),
            _ScalarResult(user),
            _ScalarResult([reset_token, sibling_token]),
            _ScalarResult([refresh_token]),
        ],
    )

    asyncio.run(service_module.reset_password("reset-token", "StrongPass123", fake_db))

    assert reset_token.is_used is True
    assert sibling_token.is_used is True
    assert refresh_token.revoked_at is not None


def test_logout_user_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    fake_db = AsyncMock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(return_value=_ScalarResult(None))
    monkeypatch.setattr(
        service_module,
        "decode_token",
        lambda token: {
            "sub": str(uuid.uuid4()),
            "type": "refresh",
            "jti": "refresh-jti",
        },
    )

    asyncio.run(service_module.logout_user("refresh-token", fake_db))

    fake_db.flush.assert_not_awaited()


def test_reset_password_raises_dedicated_invalid_token_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    service_module = importlib.reload(
        importlib.import_module("app.services.auth_service")
    )

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=_ScalarResult(None))

    with pytest.raises(PasswordResetTokenInvalidError):
        asyncio.run(
            service_module.reset_password("bad-token", "StrongPass123", fake_db)
        )


def test_email_service_wrapper_propagates_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    email_service_module = importlib.reload(
        importlib.import_module("app.services.email_service")
    )

    class FailingEmailService:
        async def send_verification_code(self, email: str, code: str) -> None:
            raise RuntimeError("smtp down")

        async def send_password_reset(self, email: str, reset_link: str) -> None:
            raise RuntimeError("smtp down")

    monkeypatch.setattr(
        email_service_module, "get_email_service", lambda: FailingEmailService()
    )

    with pytest.raises(RuntimeError):
        asyncio.run(
            email_service_module.send_verification_email("user@example.com", "123456")
        )

    with pytest.raises(RuntimeError):
        asyncio.run(
            email_service_module.send_reset_email("user@example.com", "reset-token")
        )


def test_auth_router_login_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    app, api_module = _build_auth_app(monkeypatch)
    fake_db = AsyncMock()

    async def override_db():
        yield fake_db

    async def fake_login_user(email: str, password: str, db) -> object:
        assert email == "user@example.com"
        return api_module.TokenResponse(
            access_token="access",
            refresh_token="refresh",
            token_type="Bearer",
            expires_in=1800,
        )

    app.dependency_overrides[api_module.get_db] = override_db
    monkeypatch.setattr(api_module, "login_user", fake_login_user)

    with TestClient(app) as client:
        response = client.post(
            "/login",
            json={"email": "USER@example.com", "password": "StrongPass123"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["access_token"] == "access"


def test_auth_router_register_send_code_returns_503_when_email_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, api_module = _build_auth_app(monkeypatch)
    fake_db = AsyncMock()
    fake_redis = AsyncMock()

    async def override_db():
        yield fake_db

    async def override_redis():
        return fake_redis

    async def fake_send_register_code(email: str, db, redis) -> int:
        raise EmailDeliveryError()

    app.dependency_overrides[api_module.get_db] = override_db
    app.dependency_overrides[api_module.get_redis] = override_redis
    monkeypatch.setattr(api_module, "send_register_code", fake_send_register_code)

    with TestClient(app) as client:
        response = client.post(
            "/register/send-code",
            json={"email": "user@example.com"},
        )

    assert response.status_code == 503
    assert response.json()["message"] == "邮件服务暂时不可用"


def test_auth_router_login_returns_403_for_unverified_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, api_module = _build_auth_app(monkeypatch)
    fake_db = AsyncMock()

    async def override_db():
        yield fake_db

    async def fake_login_user(email: str, password: str, db) -> object:
        raise EmailNotVerifiedError()

    app.dependency_overrides[api_module.get_db] = override_db
    monkeypatch.setattr(api_module, "login_user", fake_login_user)

    with TestClient(app) as client:
        response = client.post(
            "/login",
            json={"email": "user@example.com", "password": "StrongPass123"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == 4011


def test_auth_router_register_returns_translated_validation_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, api_module = _build_auth_app(monkeypatch)
    fake_db = AsyncMock()

    async def override_db():
        yield fake_db

    app.dependency_overrides[api_module.get_db] = override_db

    with TestClient(app) as client:
        response = client.post(
            "/register",
            json={
                "email": "user@example.com",
                "code": "123456",
                "password": "weakpass",
            },
        )

    payload = response.json()
    assert response.status_code == 422
    assert payload["code"] == 4220
    assert payload["message"] == "密码必须同时包含大写字母、小写字母和数字"
    assert payload["data"]["errors"] == [
        {
            "field": "password",
            "message": "密码必须同时包含大写字母、小写字母和数字",
            "type": "value_error",
        }
    ]


def test_auth_router_logout_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    app, api_module = _build_auth_app(monkeypatch)
    fake_db = AsyncMock()

    async def override_db():
        yield fake_db

    async def fake_logout_user(refresh_token: str, db) -> None:
        assert refresh_token == "refresh-token"

    app.dependency_overrides[api_module.get_db] = override_db
    monkeypatch.setattr(api_module, "logout_user", fake_logout_user)

    with TestClient(app) as client:
        response = client.post("/logout", json={"refresh_token": "refresh-token"})

    assert response.status_code == 200
    assert response.json() == {"code": 0, "message": "ok", "data": None}
