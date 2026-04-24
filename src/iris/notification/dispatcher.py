from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ._models import DeliveryPayload, DeliveryResult
from .helpers import build_outbound_thread_record, notification_label
from .renderers import (
    render_deadline_html_section, render_deadline_reminders_html,
    render_digest_news_html_section, render_digest_notice_summary_html_section,
    render_evening_focus_html, render_homework_rollup_html,
    render_heartbeat_items_html, render_morning_focus_html,
    render_notice_html_sections, render_related_news_html,
    render_study_plan_html, render_task_digest_html, render_urgent_tasks_html,
)
from .sender import EmailSender
from .._config import Config


logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Orchestrates notification construction, rendering, and delivery."""

    def __init__(self, config: dict[str, Any] | Config) -> None:
        if isinstance(config, Config):
            self._raw = config._raw
        else:
            self._raw = config
        self.sender = self._build_sender()

    def _build_sender(self) -> EmailSender | None:
        if isinstance(self._raw, dict):
            cfg_obj = Config({}, Path())
            cfg_obj._raw = self._raw
            return EmailSender(cfg_obj)
        return None

    def dispatch(self, payload: DeliveryPayload, preview_only: bool = False) -> DeliveryResult:
        if preview_only:
            return self._preview_only(payload)
        if self.sender is None:
            return DeliveryResult(success=False, message="发件器未初始化", preview_paths=[])
        if not self.sender.enabled:
            logger.info("邮件发送未启用，跳过发送。")
            return DeliveryResult(success=True, message="邮件未启用，跳过", preview_paths=[], email_sent=False)

        html_body = self._render(payload)
        subject = self._build_subject(payload)
        sent_meta = self.sender.send_email(
            sender=self.sender.from_addr,
            recipients=self.sender.to_addrs,
            subject=subject,
            html_body=html_body,
        )
        if sent_meta:
            thread_record = build_outbound_thread_record(payload, sent_meta)
            return DeliveryResult(
                success=True, message="已发送",
                preview_paths=[], email_sent=True,
                outbound_threads=[thread_record],
            )
        return DeliveryResult(success=False, message="发送失败", preview_paths=[])

    def _preview_only(self, payload: DeliveryPayload) -> DeliveryResult:
        import uuid
        output_dir = Path(self._raw.get("output", {}).get("path", "output"))
        output_dir.mkdir(parents=True, exist_ok=True)
        html_body = self._render(payload)
        preview_path = output_dir / f"preview_{uuid.uuid4().hex[:8]}.html"
        preview_path.write_text(html_body, encoding="utf-8")
        logger.info("预览已保存: %s", preview_path)
        return DeliveryResult(success=True, message="预览已保存", preview_paths=[str(preview_path)])

    def send_test_email(self, notification_type: str = "heartbeat") -> DeliveryResult:
        payload = DeliveryPayload(
            notification_type=notification_type,
            notices=[],
            study_plan=["这是一封测试邮件，来自阿斯加德系统。"],
        )
        return self.dispatch(payload, preview_only=False)

    def write_analysis_preview(self, notices: list[dict[str, Any]]) -> list[str]:
        import uuid
        output_dir = Path(self._raw.get("output", {}).get("path", "output"))
        output_dir.mkdir(parents=True, exist_ok=True)
        md = render_heartbeat_markdown(notices)
        preview_path = output_dir / f"analysis_{uuid.uuid4().hex[:8]}.md"
        preview_path.write_text("\n".join(md), encoding="utf-8")
        logger.info("分析预览已写入: %s", preview_path)
        return [str(preview_path)]

    def _render(self, payload: DeliveryPayload) -> str:
        ntype = payload.notification_type
        parts: list[str] = []
        if ntype == "morning_digest":
            if payload.notices:
                parts.append(render_morning_focus_html(payload.notices))
            if payload.notice_summaries:
                parts.append(render_digest_notice_summary_html_section(payload.notice_summaries))
            if payload.related_news:
                parts.append(render_related_news_html(payload.related_news))
            if payload.deadline_reminders:
                parts.append(render_deadline_reminders_html(payload.deadline_reminders))
            if payload.open_tasks:
                parts.append(render_task_digest_html(payload.open_tasks))
            if payload.study_plan:
                parts.append(render_study_plan_html(payload.study_plan))
        elif ntype == "evening_digest":
            if payload.notices:
                parts.append(render_evening_focus_html(payload.notices))
            if payload.deadline_reminders:
                parts.append(render_deadline_reminders_html(payload.deadline_reminders))
            if payload.urgent_tasks:
                parts.append(render_urgent_tasks_html(payload.urgent_tasks))
            if payload.open_tasks:
                parts.append(render_task_digest_html(payload.open_tasks))
        else:  # heartbeat
            if payload.notices:
                parts.append(render_heartbeat_items_html(payload.notices))
            if payload.deadline_reminders:
                parts.append(render_deadline_html_section(payload.deadline_reminders))
            if payload.open_tasks:
                parts.append(render_task_digest_html(payload.open_tasks))
        body = "\n".join(parts) if parts else "<p>暂无新内容</p>"
        return f"<div style=\"font-family:sans-serif;max-width:680px;margin:0 auto;padding:20px;\">{body}</div>"

    def _build_subject(self, payload: DeliveryPayload) -> str:
        label = notification_label(payload.notification_type)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"{label} | {now_str}"
