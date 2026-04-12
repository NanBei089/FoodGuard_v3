from __future__ import annotations

from app.core.config import get_settings
from app.core.email import get_email_service


async def send_verification_email(email: str, code: str) -> None:
    await get_email_service().send_verification_code(email, code)


async def send_reset_email(email: str, token: str) -> None:
    reset_link = f"{get_settings().FRONTEND_URL}/reset-password?token={token}"
    await get_email_service().send_password_reset(email, reset_link)


__all__ = ["send_reset_email", "send_verification_email"]
