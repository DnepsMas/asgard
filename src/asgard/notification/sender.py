from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any

from .._config import Config
from ._models import OutboundAttachment

logger = logging.getLogger(__name__)

_DEFAULT_SMTP_PORT = 465
_DEFAULT_TIMEOUT = 30


class EmailSender:
    """Builds and delivers MIME email messages via SMTP.

    Reads SMTP credentials from ``config.email`` and exposes a lightweight
    ``send_email`` method as well as a ``test_email`` classmethod for
    connectivity checks.
    """

    def __init__(self, config: Config) -> None:
        email_cfg = config.email
        self.smtp_host = str(email_cfg.get("smtp_host", "")).strip()
        self.smtp_port = int(email_cfg.get("smtp_port", _DEFAULT_SMTP_PORT))
        self.username = str(email_cfg.get("username", "")).strip()
        self.password = str(email_cfg.get("password", "")).strip()
        self.from_addr = str(email_cfg.get("from_addr", "")).strip() or self.username
        self.to_addrs = [a for a in email_cfg.get("to_addrs", []) if a]
        self.use_ssl = bool(email_cfg.get("use_ssl", True))
        self.timeout = max(int(email_cfg.get("smtp_timeout_seconds", _DEFAULT_TIMEOUT)), 5)
        self.enabled = bool(email_cfg.get("enabled", False))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_email(
        self,
        sender: str,
        recipients: list[str],
        subject: str,
        html_body: str,
        attachments: list[OutboundAttachment] | None = None,
        *,
        markdown_body: str = "",
        in_reply_to: str = "",
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a MIME message and deliver it over SMTP.

        Parameters
        ----------
        sender:
            ``From`` address (overrides the configured *from_addr*).
        recipients:
            List of ``To`` addresses.
        subject:
            Email subject line.
        html_body:
            HTML alternative body.
        attachments:
            Optional file attachments.
        markdown_body:
            Plain-text fallback body (auto-generated if empty).
        in_reply_to:
            ``Message-ID`` this email is replying to.
        references:
            ``References`` header values for threading.

        Returns
        -------
        dict with keys ``message_id``, ``subject``, ``recipients``,
        ``sent_at``.
        """
        resolved_sender = sender or self.from_addr
        if not resolved_sender or not recipients:
            raise ValueError("Missing sender or recipients.")

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = resolved_sender
        message["To"] = ", ".join(recipients)

        message_id = make_msgid()
        message["Message-ID"] = message_id

        if in_reply_to:
            message["In-Reply-To"] = self._normalize_message_id(in_reply_to)

        normalized_refs = self._normalize_message_id_list(references or [])
        if in_reply_to and in_reply_to not in normalized_refs:
            normalized_refs.append(in_reply_to)
        if normalized_refs:
            message["References"] = " ".join(normalized_refs)

        plain = markdown_body or self._auto_plain_text(html_body)
        message.set_content(plain)
        message.add_alternative(html_body, subtype="html")

        for attachment in attachments or []:
            maintype, subtype = self._split_mime(attachment.mime_type)
            message.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )

        self._smtp_send(resolved_sender, recipients, message)
        return {
            "message_id": message_id,
            "subject": subject,
            "recipients": recipients,
            "sent_at": datetime.now().isoformat(timespec="seconds"),
        }

    @classmethod
    def test_email(cls, config: Config, notification_type: str = "heartbeat") -> bool:
        """Construct a temporary sender and deliver a test message.

        Returns ``True`` when the message was accepted by the SMTP server.
        """
        sender = cls(config)
        if not sender.enabled or not sender.smtp_host:
            logger.warning("Email not enabled or missing SMTP host.")
            return False

        subject = sender._test_subject(notification_type)
        html_body = (
            "<html><body>"
            "<h1>Asgard Test</h1>"
            f"<p>This is a test <strong>{notification_type}</strong> message.</p>"
            f"<p>Sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
            "</body></html>"
        )
        try:
            sender.send_email(
                sender.from_addr,
                sender.to_addrs,
                subject=subject,
                html_body=html_body,
                markdown_body=f"Asgard test email: {notification_type}",
            )
            logger.info("Test email sent successfully: %s", notification_type)
            return True
        except Exception as exc:
            logger.error("Test email failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _smtp_send(self, sender: str, recipients: list[str], message: EmailMessage) -> None:
        logger.info("Sending email via %s:%s to %s", self.smtp_host, self.smtp_port, ", ".join(recipients))
        if self.use_ssl:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=self.timeout) as smtp:
                smtp.login(self.username, self.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(message)

    @staticmethod
    def _split_mime(mime_type: str) -> tuple[str, str]:
        normalized = str(mime_type or "application/octet-stream").strip()
        if "/" not in normalized:
            return "application", "octet-stream"
        maintype, subtype = normalized.split("/", 1)
        return maintype or "application", subtype or "octet-stream"

    @staticmethod
    def _normalize_message_id(value: str) -> str:
        import re

        cleaned = str(value or "").strip()
        if not cleaned:
            return ""
        match = re.search(r"<[^>]+>", cleaned)
        return match.group(0).strip() if match else cleaned

    @staticmethod
    def _normalize_message_id_list(values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            mid = str(value or "").strip()
            if mid and mid not in normalized:
                normalized.append(mid)
        return normalized

    @staticmethod
    def _auto_plain_text(html_body: str) -> str:
        import re

        plain = re.sub(r"<[^>]+>", "", html_body)
        plain = re.sub(r"\s+", " ", plain).strip()
        return plain[:2000] if plain else "(empty)"

    def _test_subject(self, notification_type: str) -> str:
        prefix = "[Asgard]"
        if notification_type == "morning_digest":
            return f"{prefix} Muninn Test {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        if notification_type == "evening_digest":
            return f"{prefix} Evening Test {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        return f"{prefix} Huginn Test {datetime.now().strftime('%Y-%m-%d %H:%M')}"
