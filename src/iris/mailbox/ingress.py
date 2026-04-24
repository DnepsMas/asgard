from __future__ import annotations

import imaplib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAILBOX_STATE_VERSION = 2


@dataclass
class InboundMail:
    uid: str
    message_id: str
    subject: str
    command_subject: str
    from_addr: str
    reply_to: str
    body: str
    received_at: str
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    thread_message_id: str = ""
    thread_notification_type: str = ""
    thread_subject: str = ""
    thread_context: dict[str, Any] = field(default_factory=dict)


class MailIngress:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.mail_config = config["inbound_email"]
        self.state_path = Path(self.mail_config["state_path"])
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def enabled(self) -> bool:
        return bool(self.mail_config.get("enabled", False))

    def register_outbound_threads(self, thread_records: list[dict[str, Any]]) -> None:
        if not thread_records:
            return

        outbound_threads = self.state.setdefault("outbound_threads", {})
        changed = False
        for record in thread_records:
            if not isinstance(record, dict):
                continue
            message_id = self._normalize_message_id(record.get("message_id", ""))
            if not message_id:
                continue
            outbound_threads[message_id] = {
                "message_id": message_id,
                "notification_type": str(record.get("notification_type", "")).strip(),
                "subject": str(record.get("subject", "")).strip(),
                "sent_at": str(record.get("sent_at", "")).strip(),
                "context": record.get("context", {}) if isinstance(record.get("context", {}), dict) else {},
            }
            changed = True
        if changed:
            self.save_state()

    def poll_commands(self) -> list[InboundMail]:
        if not self.enabled():
            return []

        if not self.mail_config.get("allowed_from_addrs"):
            logger.info("IMAP 已启用但未配置 allowed_from_addrs，跳过收信。")
            return []

        allowed_addrs = _normalize_address_list(self.mail_config["allowed_from_addrs"])
        subject_prefix = str(self.mail_config.get("subject_prefix", "")).strip()
        accept_standalone = bool(self.mail_config.get("accept_standalone_commands", False))
        folder = str(self.mail_config.get("folder", "INBOX"))
        mark_seen = bool(self.mail_config.get("mark_seen_after_process", True))

        try:
            connection = self._connect_imap()
        except (OSError, imaplib.IMAP4.error) as exc:
            logger.warning("IMAP 连接失败: %s", exc)
            return []

        try:
            connection.select(folder)
            _maybe_create_folder(connection, folder)

            processed_uids: list[str] = []
            mails: list[InboundMail] = []

            for uid, raw_message in _fetch_unseen_messages(connection, allowed_addrs):
                mail = self._parse_inbound_mail(
                    uid, raw_message, subject_prefix, accept_standalone, allowed_addrs
                )
                if mail is None:
                    continue

                if mark_seen:
                    processed_uids.append(uid)

                if self._is_duplicate(mail):
                    continue

                mails.append(mail)

            if mark_seen and processed_uids:
                connection.uid("STORE", ",".join(processed_uids), "+FLAGS", "\\Seen")

            return mails
        except (OSError, imaplib.IMAP4.error) as exc:
            logger.warning("IMAP 操作失败: %s", exc)
            return []
        finally:
            try:
                connection.close()
                connection.logout()
            except Exception:
                pass

    def mark_processed(self, mail: InboundMail, outcome: str = "", detail: str = "") -> None:
        seen = self.state.setdefault("processed_uids", {})
        seen[mail.uid] = {
            "uid": mail.uid,
            "message_id": mail.message_id,
            "subject": mail.subject,
            "processed_at": datetime.now().isoformat(timespec="seconds"),
            "outcome": outcome,
            "detail": detail,
        }
        self._trim_processed_uids()
        self.save_state()

    def _is_duplicate(self, mail: InboundMail) -> bool:
        seen = self.state.get("processed_uids", {})
        existing = seen.get(mail.uid, {})
        if not existing:
            return False

        thread_id = self._resolve_thread_id(mail)
        existing_thread = existing.get("detected_thread_id", "")
        return bool(thread_id and existing_thread == thread_id)

    def _resolve_thread_id(self, mail: InboundMail) -> str:
        return mail.thread_message_id or mail.in_reply_to or mail.message_id

    def _trim_processed_uids(self, max_count: int = 2000) -> None:
        seen = self.state.get("processed_uids", {})
        if len(seen) <= max_count:
            return
        sorted_uids = sorted(seen.items(), key=lambda item: item[1].get("processed_at", ""))
        for uid, _ in sorted_uids[: len(sorted_uids) - max_count]:
            del seen[uid]

    def _connect_imap(self) -> imaplib.IMAP4:
        host = str(self.mail_config["imap_host"])
        port = int(self.mail_config.get("imap_port", 993))
        use_ssl = bool(self.mail_config.get("use_ssl", True))
        username = str(self.mail_config["username"])
        password = str(self.mail_config["password"])

        if use_ssl:
            connection: imaplib.IMAP4 = imaplib.IMAP4_SSL(host, port)
        else:
            connection = imaplib.IMAP4(host, port)

        connection.login(username, password)
        timeout_value = self.mail_config.get("imap_timeout_seconds", None)
        if timeout_value is not None:
            connection.timeout = int(timeout_value)
        return connection

    def _parse_inbound_mail(
        self,
        uid: str,
        raw_message: bytes,
        subject_prefix: str,
        accept_standalone: bool,
        allowed_addrs: list[str],
    ) -> InboundMail | None:
        try:
            msg = message_from_bytes(raw_message)
        except Exception as exc:
            logger.warning("解析邮件失败 (UID %s): %s", uid, exc)
            return None

        message_id = _decode_header_value(msg.get("Message-ID", ""))
        subject = _decode_header_value(msg.get("Subject", ""))
        from_addr = _decode_header_value(msg.get("From", ""))
        reply_to_addr = _extract_reply_to(msg)
        in_reply_to = _normalize_message_id(_decode_header_value(msg.get("In-Reply-To", "")))
        references_raw = _decode_header_value(msg.get("References", ""))
        references = _parse_references(references_raw)
        body = _extract_body(msg)

        sender_email = parseaddr(from_addr)[1].lower()
        if not accept_standalone and not any(
            sender_email.endswith("@" + addr) or sender_email == addr for addr in allowed_addrs
        ):
            return None

        command_subject = subject
        if subject_prefix and subject.startswith(subject_prefix):
            command_subject = subject[len(subject_prefix):].strip()
        elif not accept_standalone:
            return None

        received_at = msg.get("Date", "")
        try:
            dt = parsedate_to_datetime(received_at)
            if dt is not None:
                received_at = dt.isoformat(timespec="seconds")
        except Exception:
            pass

        thread_message_id = _find_outbound_thread_message_id(
            self.state.get("outbound_threads", {}),
            in_reply_to,
            references,
        )
        thread_info = self.state.get("outbound_threads", {}).get(thread_message_id, {}) if thread_message_id else {}
        thread_notification_type = str(thread_info.get("notification_type", "")) if isinstance(thread_info, dict) else ""
        thread_subject = str(thread_info.get("subject", "")) if isinstance(thread_info, dict) else ""
        thread_context = thread_info.get("context", {}) if isinstance(thread_info, dict) else {}

        return InboundMail(
            uid=uid,
            message_id=message_id,
            subject=subject,
            command_subject=command_subject,
            from_addr=from_addr,
            reply_to=reply_to_addr,
            body=body,
            received_at=received_at,
            in_reply_to=in_reply_to,
            references=references,
            thread_message_id=thread_message_id or in_reply_to or "",
            thread_notification_type=thread_notification_type,
            thread_subject=thread_subject,
            thread_context=thread_context,
        )

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"version": MAILBOX_STATE_VERSION, "processed_uids": {}}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return {"version": MAILBOX_STATE_VERSION, "processed_uids": {}}

    def save_state(self) -> None:
        self.state["version"] = MAILBOX_STATE_VERSION
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_message_id(value: str) -> str:
        return _normalize_message_id(value)


# --- Module-level helpers ---


def _normalize_message_id(value: str) -> str:
    value = str(value).strip()
    if not value:
        return ""
    value = value.strip("<>").strip()
    return f"<{value}>"


def _normalize_address_list(addrs: Any) -> list[str]:
    if isinstance(addrs, str):
        return [addrs.strip().lower()]
    if isinstance(addrs, list):
        return [str(a).strip().lower() for a in addrs if a]
    return []


def _decode_header_value(value: Any) -> str:
    if value is None:
        return ""
    decoded_parts: list[str] = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            try:
                decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                decoded_parts.append(part.decode("utf-8", errors="replace"))
        elif isinstance(part, str):
            decoded_parts.append(part)
    return " ".join(decoded_parts)


def _extract_reply_to(msg: Message) -> str:
    reply_to = _decode_header_value(msg.get("Reply-To", ""))
    if reply_to:
        return parseaddr(reply_to)[1]
    return parseaddr(_decode_header_value(msg.get("From", "")))[1]


def _extract_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        return payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        return payload.decode("utf-8", errors="replace")
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        decoded = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        decoded = payload.decode("utf-8", errors="replace")
                    soup = BeautifulSoup(decoded, "html.parser")
                    return soup.get_text(separator="\n", strip=True)

    payload = msg.get_payload(decode=True)
    if payload:
        charset = msg.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return payload.decode("utf-8", errors="replace")
    return ""


def _parse_references(references_raw: str) -> list[str]:
    if not references_raw:
        return []
    return [_normalize_message_id(ref) for ref in re.split(r"[\s,]+", references_raw) if ref.strip()]


def _find_outbound_thread_message_id(
    outbound_threads: dict[str, Any],
    in_reply_to: str,
    references: list[str],
) -> str:
    candidates = [in_reply_to] + references
    for cid in candidates:
        normalized = _normalize_message_id(cid)
        if normalized in outbound_threads:
            return normalized
    return ""


def _maybe_create_folder(connection: imaplib.IMAP4, folder: str) -> None:
    try:
        connection.create(folder)
    except Exception:
        pass


def _fetch_unseen_messages(
    connection: imaplib.IMAP4,
    allowed_addrs: list[str],
) -> list[tuple[str, bytes]]:
    search_criteria = "UNSEEN"
    try:
        _, uid_data = connection.uid("SEARCH", None, search_criteria)
    except imaplib.IMAP4.error:
        return []

    uid_list = uid_data[0].split() if uid_data[0] else []
    if not uid_list:
        return []

    messages: list[tuple[str, bytes]] = []
    uid_chunks = [uid_list[i:i + 30] for i in range(0, len(uid_list), 30)]

    for chunk in uid_chunks:
        uids = ",".join(uid.decode() if isinstance(uid, bytes) else str(uid) for uid in chunk)
        try:
            _, data = connection.uid("FETCH", uids, "(RFC822 FLAGS)")
        except imaplib.IMAP4.error:
            continue

        for i in range(0, len(data), 2):
            raw_data = data[i]
            if not isinstance(raw_data, tuple) or len(raw_data) < 2:
                continue
            raw_bytes = raw_data[1]
            uid_str = chunk[i // 2].decode() if isinstance(chunk[i // 2], bytes) else str(chunk[i // 2])

            if allowed_addrs:
                try:
                    msg = message_from_bytes(raw_bytes)
                    sender = parseaddr(_decode_header_value(msg.get("From", "")))[1].lower()
                    if not any(sender.endswith("@" + addr) or sender == addr for addr in allowed_addrs):
                        continue
                except Exception:
                    pass

            messages.append((uid_str, raw_bytes))

    return messages
