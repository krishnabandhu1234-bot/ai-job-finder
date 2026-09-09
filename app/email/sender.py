"""SMTP sending (sections 11-12). Supports SMTP with an app-specific
password (the common path for Gmail/Microsoft/most providers without
implementing a full OAuth flow) - see the docstring on `EmailSettingsPage`
for why plain SMTP is preferred here over an in-app OAuth flow: it's
what an app-specific password already covers securely without shipping
OAuth client secrets inside a distributed desktop executable.

Never logs the password; connection failures are wrapped in
`EmailSendError` with a message safe to show directly in the UI
(section 23: never silently fail, always surface something useful).
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailSendError(Exception):
    pass


@dataclass
class EmailRuntimeConfig:
    recipient: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str

    def is_configured(self) -> bool:
        return bool(self.recipient and self.smtp_host and self.smtp_username and self.smtp_password)


def resolve_email_config(session, context) -> EmailRuntimeConfig:
    cfg = context.config
    repo = context.settings_repo
    prefix = "email."
    return EmailRuntimeConfig(
        recipient=repo.get(session, prefix + "recipient", cfg.email_to),
        smtp_host=repo.get(session, prefix + "smtp_host", cfg.smtp_host),
        smtp_port=repo.get_int(session, prefix + "smtp_port", cfg.smtp_port),
        smtp_username=repo.get(session, prefix + "smtp_username", cfg.smtp_username),
        smtp_password=repo.get(session, prefix + "smtp_password", cfg.smtp_app_password),
    )


def send_email(email_config: EmailRuntimeConfig, subject: str, html_body: str, text_body: str) -> None:
    """Raises `EmailSendError` on any failure - never raises a raw
    smtplib/socket exception up to the caller, and never partially
    "succeeds" silently."""
    if not email_config.is_configured():
        raise EmailSendError(
            "Email isn't fully configured yet - set your recipient address, SMTP host, "
            "username, and app password on the Email Settings page."
        )

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = email_config.smtp_username
    message["To"] = email_config.recipient
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(email_config.smtp_host, email_config.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(email_config.smtp_username, email_config.smtp_password)
            server.sendmail(email_config.smtp_username, [email_config.recipient], message.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        logger.warning("SMTP authentication failed for %s", email_config.smtp_username)
        raise EmailSendError(
            "SMTP login failed - check your username and app password on the Email Settings page."
        ) from exc
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        logger.warning("SMTP send failed: %s", exc)
        raise EmailSendError(f"Could not send email: {exc}") from exc
