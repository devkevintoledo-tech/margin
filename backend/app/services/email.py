"""Email delivery for password recovery.

No FastAPI types leak into the senders themselves; ``email_sender_dep`` is the
thin FastAPI dependency so routes can depend on it and tests can override it via
``app.dependency_overrides`` (mirroring ``get_db``).
"""

import logging
from abc import ABC, abstractmethod
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


class EmailSender(ABC):
    @abstractmethod
    async def send_password_reset(self, to_email: str, reset_url: str) -> None:
        ...


class ConsoleEmailSender(EmailSender):
    """Logs the reset link instead of sending — used when SMTP is unconfigured."""

    async def send_password_reset(self, to_email: str, reset_url: str) -> None:
        logger.info("Password reset link for %s: %s", to_email, reset_url)


class SmtpEmailSender(EmailSender):
    async def send_password_reset(self, to_email: str, reset_url: str) -> None:
        import aiosmtplib

        msg = EmailMessage()
        msg["From"] = settings.MAIL_FROM
        msg["To"] = to_email
        msg["Subject"] = "Reset your MARGIN password"
        msg.set_content(
            "We received a request to reset your MARGIN password.\n\n"
            f"Use this link to choose a new password:\n{reset_url}\n\n"
            "If you didn't request this, you can safely ignore this email."
        )

        send_kwargs = {
            "hostname": settings.SMTP_HOST,
            "port": settings.SMTP_PORT,
            "start_tls": settings.SMTP_USE_TLS,
        }
        if settings.SMTP_USER:
            send_kwargs["username"] = settings.SMTP_USER
        if settings.SMTP_PASSWORD:
            send_kwargs["password"] = settings.SMTP_PASSWORD

        await aiosmtplib.send(msg, **send_kwargs)


def get_email_sender() -> EmailSender:
    if settings.SMTP_HOST:
        return SmtpEmailSender()
    return ConsoleEmailSender()


def email_sender_dep() -> EmailSender:
    return get_email_sender()


def build_reset_url(token: str) -> str:
    return f"{settings.FRONTEND_BASE_URL}/reset-password?token={token}"
