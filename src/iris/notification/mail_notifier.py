from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ._models import DeliveryResult
from .helpers import build_task_receipt_thread_record
from .sender import EmailSender
from .._config import Config


logger = logging.getLogger(__name__)


class MailNotifier:
    """Handles task-oriented email delivery (agent replies and receipts)."""

    def __init__(self, config: dict[str, Any] | Config) -> None:
        if isinstance(config, Config):
            self._raw = config._raw
        else:
            self._raw = config
        self.email_config = self._raw.get("email", {})
        if isinstance(config, Config):
            self.sender = EmailSender(config)
        else:
            cfg_obj = Config({}, Path())
            cfg_obj._raw = self._raw
            self.sender = EmailSender(cfg_obj)

    def deliver_agent_reply(
        self,
        *,
        recipient: str,
        subject: str,
        markdown_body: str,
        preview_only: bool = False,
        thread_subject: str = "",
        in_reply_to: str = "",
        references: list[str] | None = None,
        thread_notification_type: str = "",
        thread_context: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        preview_paths = self._write_preview(markdown_body, "reply")
        if preview_only or not self.sender.enabled:
            return DeliveryResult(
                success=True,
                message="回复预览已生成，未发送邮件。" if preview_only else "邮件未启用，跳过发送。",
                preview_paths=preview_paths,
                email_sent=False,
            )
        display_subject = thread_subject or subject or "Re: 任务邮件"
        html_body = self._md_to_html(markdown_body)
        try:
            sent_meta = self.sender.send_email(
                sender=self.sender.from_addr,
                recipients=[recipient],
                subject=display_subject,
                html_body=html_body,
                markdown_body=markdown_body,
                in_reply_to=in_reply_to,
                references=references or [],
            )
            thread_record = build_task_receipt_thread_record(
                sent_meta=sent_meta,
                thread_subject=display_subject,
                thread_notification_type=thread_notification_type or "agent_reply",
                thread_context=thread_context or {},
            )
            return DeliveryResult(
                success=True,
                message=f"回复已发送到 {recipient}。",
                preview_paths=preview_paths,
                email_sent=True,
                outbound_threads=[thread_record] if sent_meta.get("message_id") else [],
            )
        except Exception as exc:
            logger.error("回复发送失败: %s", exc)
            return DeliveryResult(
                success=False,
                message=f"回复发送失败: {exc}",
                preview_paths=preview_paths,
                email_sent=False,
            )

    def deliver_task_receipt(
        self,
        *,
        recipient: str,
        executed_actions: list[dict[str, Any]],
        answers: list[str],
        failures: list[str],
        raw_request: str,
        preview_only: bool = False,
        thread_subject: str = "",
        in_reply_to: str = "",
        references: list[str] | None = None,
        thread_notification_type: str = "",
        thread_context: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        preview_body = self._build_receipt_markdown(executed_actions, answers, failures, raw_request)
        preview_paths = self._write_preview(preview_body, "receipt")
        if preview_only or not self.sender.enabled:
            return DeliveryResult(
                success=True,
                message="任务回执预览已生成，未发送邮件。",
                preview_paths=preview_paths,
                email_sent=False,
            )
        generated_at = datetime.now()
        subject = thread_subject or f"任务回执 {generated_at.strftime('%Y-%m-%d %H:%M')}"
        html_body = self._md_to_html(preview_body)
        try:
            sent_meta = self.sender.send_email(
                sender=self.sender.from_addr,
                recipients=[recipient],
                subject=subject,
                html_body=html_body,
                markdown_body=preview_body,
                in_reply_to=in_reply_to,
                references=references or [],
            )
            thread_record = build_task_receipt_thread_record(
                sent_meta=sent_meta,
                thread_subject=subject,
                thread_notification_type=thread_notification_type or "task_receipt",
                thread_context=thread_context or {},
            )
            return DeliveryResult(
                success=True,
                message=f"任务回执已发送到 {recipient}。",
                preview_paths=preview_paths,
                email_sent=True,
                outbound_threads=[thread_record] if sent_meta.get("message_id") else [],
            )
        except Exception as exc:
            logger.error("任务回执发送失败: %s", exc)
            return DeliveryResult(
                success=False,
                message=f"任务回执发送失败: {exc}",
                preview_paths=preview_paths,
                email_sent=False,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_preview(self, body: str, prefix: str) -> list[str]:
        output_dir = Path(self._raw.get("output", {}).get("path", "output"))
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{prefix}_{uuid.uuid4().hex[:8]}.md"
        path.write_text(body, encoding="utf-8")
        logger.info("%s 预览已保存: %s", prefix, path)
        return [str(path)]

    @staticmethod
    def _md_to_html(markdown_body: str) -> str:
        lines = []
        for line in markdown_body.split("\n"):
            if line.startswith("# "):
                lines.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):
                lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("- "):
                lines.append(f"<li>{line[2:]}</li>")
            elif line.strip():
                lines.append(f"<p>{line}</p>")
        body = "\n".join(lines)
        return f"<div style=\"font-family:sans-serif;max-width:680px;margin:0 auto;padding:20px;\">{body}</div>"

    @staticmethod
    def _build_receipt_markdown(
        executed_actions: list[dict[str, Any]],
        answers: list[str],
        failures: list[str],
        raw_request: str,
    ) -> str:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines: list[str] = [f"# 阿斯加德 | 任务回执\n\n生成时间: {now_str}\n"]
        if raw_request:
            lines.append(f"\n## 原始请求\n\n{raw_request}\n")
        if executed_actions:
            lines.append("\n## 已执行操作\n")
            for action in executed_actions:
                title = action.get("title", action.get("message", ""))
                lines.append(f"- {action.get('action_type', '操作')}: {title}")
        if answers:
            lines.append("\n## 回答\n")
            for ans in answers:
                lines.append(f"- {ans}")
        if failures:
            lines.append("\n## 失败/警告\n")
            for f in failures:
                lines.append(f"- {f}")
        return "\n".join(lines)
