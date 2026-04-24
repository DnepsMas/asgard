from __future__ import annotations

import logging
import time
from datetime import datetime, time as clock_time, timedelta
from typing import Any, Callable

from .._logging import emit_console_summary


def parse_clock(value: str) -> clock_time:
    """Parse a ``HH:MM`` string into a ``datetime.time``."""
    hour_text, minute_text = str(value).split(":", 1)
    return clock_time(hour=int(hour_text), minute=int(minute_text))


def build_schedule_slots(day: datetime, scheduler: dict[str, Any]) -> list[datetime]:
    """Build all candidate execution slots for *day* given *scheduler* config."""
    active_start = parse_clock(scheduler["active_start"])
    active_end = parse_clock(scheduler["active_end"])
    digest_time = parse_clock(scheduler["morning_digest_time"])
    evening_time = parse_clock(scheduler.get("evening_digest_time", "20:00"))
    interval_hours = max(int(scheduler.get("heartbeat_interval_hours", 2)), 1)

    start_at = datetime.combine(day.date(), active_start)
    end_at = datetime.combine(day.date(), active_end)
    slots: list[datetime] = []
    current = start_at
    while current < end_at:
        slots.append(current)
        current += timedelta(hours=interval_hours)

    digest_at = datetime.combine(day.date(), digest_time)
    if start_at <= digest_at < end_at and digest_at not in slots:
        slots.append(digest_at)

    evening_at = datetime.combine(day.date(), evening_time)
    if start_at <= evening_at < end_at and evening_at not in slots:
        slots.append(evening_at)

    slots.sort()
    return slots


def next_scheduled_run(reference: datetime, scheduler: dict[str, Any]) -> datetime:
    """Return the next datetime >= *reference* that matches *scheduler* config."""
    reference_floor = reference.replace(second=0, microsecond=0)
    for day_offset in range(0, 8):
        day = reference_floor + timedelta(days=day_offset)
        for slot in build_schedule_slots(day, scheduler):
            if slot >= reference_floor:
                return slot
    raise RuntimeError("未找到未来 7 天内的有效执行时间，请检查 scheduler 配置。")


def resolve_delivery_mode(scheduled_at: datetime, scheduler: dict[str, Any]) -> str:
    """Determine delivery mode for a scheduled datetime."""
    digest_time = parse_clock(scheduler["morning_digest_time"])
    evening_time = parse_clock(scheduler.get("evening_digest_time", "20:00"))
    if scheduled_at.hour == digest_time.hour and scheduled_at.minute == digest_time.minute:
        return "morning_digest"
    if scheduled_at.hour == evening_time.hour and scheduled_at.minute == evening_time.minute:
        return "evening_digest"
    return "heartbeat"


def sleep_until(target: datetime, polling_interval: int) -> None:
    """Sleep until *target*, waking periodically to check for interrupts."""
    chunk = max(1, min(max(polling_interval, 1), 300))
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, chunk))


class Scheduler:
    """Main loop scheduler that handles timing and dispatch orchestration.

    Parameters
    ----------
    config_factory : () -> dict
        Callable that returns a fresh config dict on every invocation.
    cycle_fn : (config, delivery_mode) -> int
        Called when a scheduled notification cycle is due.
    mailbox_fn : (config) -> None, optional
        Called when a standalone mailbox poll is due (between scheduled cycles).
    """

    def __init__(
        self,
        config_factory: Callable[[], dict[str, Any]],
        cycle_fn: Callable[[dict[str, Any], str], int],
        mailbox_fn: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config_factory = config_factory
        self.cycle_fn = cycle_fn
        self.mailbox_fn = mailbox_fn
        self.next_notice_after = datetime.now()
        self.next_mail_after = datetime.now()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, preview_only: bool = False) -> int:
        """Enter the main scheduler loop (blocks indefinitely)."""
        config = self.config_factory()
        scheduler_cfg = config["scheduler"]
        poll_interval = int(config["runtime"]["polling_interval"])

        if not scheduler_cfg.get("enabled", True):
            return self._run_compat(poll_interval, preview_only)

        return self._run_scheduled(poll_interval, preview_only)

    # ------------------------------------------------------------------
    # Compatibility polling mode (scheduler disabled)
    # ------------------------------------------------------------------

    def _run_compat(self, poll_interval: int, preview_only: bool) -> int:
        logger = logging.getLogger(__name__)
        interval = max(poll_interval, 1)
        emit_console_summary("heartbeat | 调度器关闭，按兼容轮询模式运行")
        while True:
            try:
                config = self.config_factory()
                if self.mailbox_fn and config["inbound_email"].get("enabled", False) and not preview_only:
                    self.mailbox_fn(config)
                self.cycle_fn(config, "heartbeat")
                time.sleep(interval)
            except KeyboardInterrupt:
                logger.info("收到中断信号，已退出。")
                emit_console_summary("阿斯加德已停止")
                return 0
            except Exception as exc:
                logger.error("运行失败: %s", exc)
                time.sleep(interval)

    # ------------------------------------------------------------------
    # Scheduled mode
    # ------------------------------------------------------------------

    def _run_scheduled(self, poll_interval: int, preview_only: bool) -> int:
        logger = logging.getLogger(__name__)
        while True:
            try:
                config = self.config_factory()
                scheduler = config["scheduler"]
                poll_int = max(int(config["runtime"]["polling_interval"]), 1)
                mail_poll = int(config["inbound_email"].get("poll_interval_seconds", 300))

                scheduled_at = next_scheduled_run(self.next_notice_after, scheduler)
                delivery_mode = resolve_delivery_mode(scheduled_at, scheduler)

                mail_due_at: datetime | None = None
                if self.mailbox_fn and config["inbound_email"].get("enabled", False) and not preview_only:
                    mail_due_at = self.next_mail_after

                next_wake = scheduled_at if mail_due_at is None else min(scheduled_at, mail_due_at)
                mode_label = (
                    "早报" if delivery_mode == "morning_digest"
                    else "晚报" if delivery_mode == "evening_digest"
                    else "heartbeat"
                )
                mail_info = (
                    f"；邮箱轮询 {mail_due_at.strftime('%Y-%m-%d %H:%M:%S')}"
                    if mail_due_at else ""
                )
                logger.info(
                    "下一次计划执行时间：%s (%s)%s",
                    scheduled_at.strftime("%Y-%m-%d %H:%M:%S"),
                    mode_label,
                    mail_info,
                )
                sleep_until(next_wake, poll_int)

                config = self.config_factory()
                now = datetime.now()

                cycle_due = now >= scheduled_at
                mail_due = mail_due_at is not None and now >= mail_due_at

                if mail_due and not cycle_due and self.mailbox_fn:
                    self.mailbox_fn(config)
                    self.next_mail_after = now + timedelta(seconds=mail_poll)
                elif cycle_due:
                    exit_code = self.cycle_fn(config, delivery_mode)
                    if exit_code != 0:
                        logger.warning("本轮计划任务执行失败，将等待下一个有效时段继续运行。")
                    self.next_notice_after = max(now, scheduled_at + timedelta(minutes=1))
                    if mail_due:
                        self.next_mail_after = now + timedelta(seconds=mail_poll)
            except KeyboardInterrupt:
                logger.info("收到中断信号，已退出。")
                emit_console_summary("阿斯加德已停止")
                return 0
            except Exception as exc:
                logger.error("计划任务执行失败: %s", exc)
