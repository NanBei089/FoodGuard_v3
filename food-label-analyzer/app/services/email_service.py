from __future__ import annotations

from time import perf_counter

import structlog

from app.core.config import get_settings
from app.core.email import get_email_service

logger = structlog.get_logger(__name__)


async def send_verification_email(email: str, code: str) -> None:
    logger.info("email_dispatch_start", kind="verification", email=email)
    started_at = perf_counter()
    try:
        await get_email_service().send_verification_code(email, code)
    finally:
        logger.info(
            "email_dispatch_done",
            kind="verification",
            email=email,
            elapsed_ms=int((perf_counter() - started_at) * 1000),
        )


async def send_reset_email(email: str, token: str) -> None:
    reset_link = f"{get_settings().FRONTEND_URL}/reset-password?token={token}"
    logger.info("email_dispatch_start", kind="password_reset", email=email)
    started_at = perf_counter()
    try:
        await get_email_service().send_password_reset(email, reset_link)
    finally:
        logger.info(
            "email_dispatch_done",
            kind="password_reset",
            email=email,
            elapsed_ms=int((perf_counter() - started_at) * 1000),
        )


__all__ = ["send_reset_email", "send_verification_email"]
