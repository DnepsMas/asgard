from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from ._models import (
    COMPETITION_KEYWORDS,
    HEARTBEAT_COMPETITION_KEYWORDS,
    HEARTBEAT_LOW_SIGNAL_KEYWORDS,
    HEARTBEAT_PORTAL_PRIORITY,
    HEARTBEAT_PRIMARY_KEYWORDS,
    HEARTBEAT_SECONDARY_KEYWORDS,
    IMPORTANCE_LABELS,
    RAVEN_DIGEST,
    RAVEN_HEARTBEAT,
    DeliveryPayload,
)


def parse_datetime(value: str) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def published_timestamp(item: dict[str, Any]) -> float:
    published_at = str(item.get("published_at", "")).strip()
    normalized = published_at.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", normalized)
    if not match:
        return 0.0
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))).timestamp()
    except ValueError:
        return 0.0


def count_by_importance(notices: list[dict[str, Any]]) -> dict[str, int]:
    counters: dict[str, int] = {"important": 0, "watch": 0, "ignore": 0}
    for item in notices:
        importance = item.get("ai_result", {}).get("importance", "watch")
        counters[importance] = counters.get(importance, 0) + 1
    return counters


def notification_label(notification_type: str) -> str:
    if notification_type == "morning_digest":
        return f"{RAVEN_DIGEST}晨报"
    if notification_type == "evening_digest":
        return "晚报"
    return f"{RAVEN_HEARTBEAT}来报"


def importance_label(item: dict[str, Any]) -> str:
    importance = str(item.get("ai_result", {}).get("importance", "watch")).strip().lower()
    return IMPORTANCE_LABELS.get(importance, "可关注")


def summary_text(item: dict[str, Any]) -> str:
    ai_result = item.get("ai_result", {})
    return str(ai_result.get("summary", "")).strip() or item.get("title", "")


def reason_text(item: dict[str, Any]) -> str:
    ai_result = item.get("ai_result", {})
    reason = str(ai_result.get("reason", "")).strip()
    return reason or summary_text(item)


def action_text(item: dict[str, Any], fallback: str = "打开原文确认细则。") -> str:
    actions = item.get("ai_result", {}).get("action_items", [])
    if isinstance(actions, list):
        for action in actions:
            cleaned = str(action).strip()
            if cleaned:
                return cleaned
    return fallback


def deadline_text(item: dict[str, Any]) -> str:
    return str(item.get("ai_result", {}).get("deadline", "")).strip()


def deadline_datetime(item: dict[str, Any]) -> datetime | None:
    dt = parse_datetime(item.get("deadline_at", ""))
    if dt is not None:
        return dt
    return parse_datetime(deadline_text(item))


def deadline_display_text(item: dict[str, Any]) -> str:
    text = deadline_text(item)
    if text:
        return text
    dt = deadline_datetime(item)
    if dt is not None:
        return dt.strftime("%Y-%m-%d %H:%M")
    return "无"


def task_due_display_text(task: dict[str, Any]) -> str:
    due_dt = parse_datetime(task.get("due_at", ""))
    if due_dt is None:
        return "无"
    return due_dt.strftime("%Y-%m-%d %H:%M")


def task_importance_label(task: dict[str, Any]) -> str:
    importance = str(task.get("importance", "")).strip().lower()
    if importance == "major":
        return "大事"
    if importance == "minor":
        return "小事"
    return "普通"


def task_reminder_text(task: dict[str, Any]) -> str:
    if task.get("status") != "open":
        return ""
    if bool(task.get("reminder_disabled", False)):
        policy = str(task.get("reminder_policy", "")).strip()
        return policy or "当前不再主动提醒。"
    next_remind_dt = parse_datetime(task.get("next_remind_at", ""))
    policy = str(task.get("reminder_policy", "")).strip()
    if next_remind_dt is not None:
        next_text = next_remind_dt.strftime("%Y-%m-%d %H:%M")
        if policy:
            return f"下一次 {next_text} | {policy}"
        return f"下一次 {next_text}"
    return policy


def task_status_label(task: dict[str, Any]) -> str:
    status = str(task.get("status", "")).strip().lower()
    if status == "done":
        return "已完成"
    if status == "cancelled":
        return "已取消"
    return "进行中"


def task_estimate_text(task: dict[str, Any]) -> str:
    estimated_minutes = task.get("estimated_minutes")
    if isinstance(estimated_minutes, int) and estimated_minutes > 0:
        return f"预计时长：{estimated_minutes} 分钟"
    return ""


def task_source_label(task: dict[str, Any]) -> str:
    source_email_message_id = str(task.get("source_email_message_id", "")).strip()
    if source_email_message_id:
        return "回复设置任务"
    return "自动任务"


def receipt_action_label(item: dict[str, Any]) -> str:
    action_type = str(item.get("action_type", "")).strip().lower()
    return {
        "create_task": "创建任务",
        "update_task": "更新任务",
        "complete_task": "完成任务",
        "cancel_task": "取消任务",
    }.get(action_type, "任务操作")


def homework_title(item: dict[str, Any]) -> str:
    raw_title = str(item.get("title", "")).strip()
    source = homework_course_label(item)
    candidates = [f"[{source}] ", f"{source} "]
    for prefix in candidates:
        if source and raw_title.startswith(prefix):
            return raw_title[len(prefix):].strip()
    return raw_title


def homework_course_label(item: dict[str, Any]) -> str:
    source = str(item.get("source", "")).strip()
    return source or "课程作业"


def homework_summary_text(item: dict[str, Any]) -> str:
    summary = summary_text(item)
    summary = re.sub(r"\s+", " ", summary).strip()
    if not summary:
        return "无"
    if len(summary) > 140:
        return summary[:137].rstrip() + "..."
    return summary


def homework_attachment_line(item: dict[str, Any]) -> str:
    attachments = homework_attachments(item)
    if not attachments:
        return ""
    filenames = [
        str(attachment.get("filename", "")).strip()
        for attachment in attachments
        if str(attachment.get("filename", "")).strip()
    ]
    if not filenames:
        return ""
    return f"附件：{'、'.join(filenames)}"


def homework_attachments(item: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = item.get("metadata", {})
    if not isinstance(metadata, dict):
        return []
    attachments = metadata.get("ucloud_attachments", [])
    if not isinstance(attachments, list):
        return []
    return [attachment for attachment in attachments if isinstance(attachment, dict)]


def homework_focus_reason(item: dict[str, Any]) -> str:
    dt = deadline_datetime(item)
    if dt is not None:
        delta = dt - datetime.now()
        hours = delta.total_seconds() / 3600
        if hours < 0:
            return "它已经过了系统识别的截止时间，今晚最好先确认是否还能补交。"
        if hours <= 24:
            return "它离截止已经很近，今晚不动手，明天就容易被时间追上。"
        if hours <= 72:
            return "它这几天就要到点，今晚先推进一部分最稳。"
        if hours <= 24 * 7:
            return "它会在这一周内截止，今晚先摸清要求能少踩很多坑。"
    return "它还在待办列表里，今晚先把题目和提交方式确认清楚会更从容。"


def homework_action_text(item: dict[str, Any]) -> str:
    merged = merged_text(item)
    dt = deadline_datetime(item)
    if dt is not None:
        hours = (dt - datetime.now()).total_seconds() / 3600
        if hours < 0:
            return "先打开作业页确认是否还能补交，并尽快补上可提交的部分。"
        if hours <= 24:
            return "今晚优先完成并提交，至少先把已经能交的部分交上去。"
        if hours <= 72:
            return "今晚先完成第一部分或列出解题步骤，给后续修改留缓冲。"
    if "附件" in merged or "见附件" in merged:
        return "先下载附件或题面，把格式、提交入口和要求确认清楚。"
    return "今晚先打开作业页确认要求，再决定安排到哪天完成。"


def merged_text(item: dict[str, Any]) -> str:
    ai_result = item.get("ai_result", {})
    return "\n".join(
        str(part) for part in [
            item.get("title", ""), ai_result.get("summary", ""), ai_result.get("reason", "")
        ] if part
    )


def headline_text(item: dict[str, Any]) -> str:
    ai_result = item.get("ai_result", {})
    return "\n".join(
        str(part) for part in [
            item.get("title", ""), item.get("portal_name", ""), ai_result.get("category", "")
        ] if part
    )


def count_upcoming_homework(notices: list[dict[str, Any]], hours: int) -> int:
    now = datetime.now()
    upper = now + timedelta(hours=max(hours, 0))
    count = 0
    for item in notices:
        dt = deadline_datetime(item)
        if dt is None:
            continue
        if now <= dt <= upper:
            count += 1
    return count


def count_overdue_homework(notices: list[dict[str, Any]]) -> int:
    now = datetime.now()
    count = 0
    for item in notices:
        dt = deadline_datetime(item)
        if dt is not None and dt < now:
            count += 1
    return count


def build_evening_overview_markdown(notices: list[dict[str, Any]]) -> list[str]:
    if not notices:
        return ["- 今晚没有待完成作业。", ""]
    upcoming_48 = count_upcoming_homework(notices, hours=48)
    upcoming_week = count_upcoming_homework(notices, hours=24 * 7)
    lines = [
        f"- 今晚共有 {len(notices)} 项待完成作业，其中 {upcoming_48} 项会在 48 小时内到点，{upcoming_week} 项会在 7 天内截止。",
    ]
    first_due = next((item for item in notices if deadline_datetime(item) is not None), None)
    if first_due:
        lines.append(
            f"- 最先该动手的是《{homework_title(first_due)}》，截止 {deadline_display_text(first_due)}。"
        )
    else:
        lines.append("- 这些作业里暂时没有识别到明确截止时间，今晚更适合先把题目和提交要求摸清。")
    lines.append("")
    return lines


def render_evening_overview_html(notices: list[dict[str, Any]]) -> str:
    from .templates import html_paragraphs
    lines = [
        line[2:] if line.startswith("- ") else line
        for line in build_evening_overview_markdown(notices)
        if line
    ]
    return html_paragraphs(lines)


def morning_focus_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    importance = item.get("ai_result", {}).get("importance", "watch")
    deadline_dt = parse_datetime(item.get("deadline_at", "")) if deadline_text(item) else None
    is_competition = any(keyword in merged_text(item) for keyword in COMPETITION_KEYWORDS)
    if importance == "important" and deadline_dt is not None:
        bucket = 0
    elif importance == "important" and is_competition:
        bucket = 1
    elif importance == "important":
        bucket = 2
    else:
        bucket = 3
    return (bucket, deadline_dt or datetime.max, -published_timestamp(item), item.get("title", ""))


def huginn_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    importance = item.get("ai_result", {}).get("importance", "watch")
    importance_rank = 0 if importance == "important" else 1 if importance == "watch" else 2
    deadline_dt_val = deadline_datetime(item)
    return (
        importance_rank,
        heartbeat_focus_rank(item),
        heartbeat_portal_rank(item),
        heartbeat_deadline_status_rank(item),
        deadline_dt_val or datetime.max,
        -published_timestamp(item),
        item.get("title", ""),
    )


def heartbeat_focus_rank(item: dict[str, Any]) -> int:
    headline = headline_text(item)
    merged = merged_text(item)
    if any(keyword in headline for keyword in HEARTBEAT_COMPETITION_KEYWORDS):
        return 0
    if any(keyword in headline for keyword in HEARTBEAT_PRIMARY_KEYWORDS):
        return 1
    if any(keyword in merged for keyword in HEARTBEAT_SECONDARY_KEYWORDS):
        return 2
    if deadline_is_upcoming(item):
        return 3
    if any(keyword in headline for keyword in HEARTBEAT_LOW_SIGNAL_KEYWORDS):
        return 5
    return 4


def heartbeat_portal_rank(item: dict[str, Any]) -> int:
    return HEARTBEAT_PORTAL_PRIORITY.get(str(item.get("portal_name", "")).strip(), 3)


def heartbeat_deadline_status_rank(item: dict[str, Any]) -> int:
    dt = deadline_datetime(item)
    if dt is None:
        return 1
    today = datetime.now().date()
    if dt.date() < today:
        return 2
    if dt.date() <= today + timedelta(days=7):
        return 0
    return 1


def deadline_is_upcoming(item: dict[str, Any]) -> bool:
    return heartbeat_deadline_status_rank(item) == 0


def deadline_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (deadline_datetime(item) or datetime.max, item.get("title", ""))


def normalize_message_id(value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    match = re.search(r"<[^>]+>", cleaned)
    return match.group(0).strip() if match else cleaned


def normalize_message_id_list(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        message_id = normalize_message_id(value)
        if message_id and message_id not in normalized:
            normalized.append(message_id)
    return normalized


def build_outbound_thread_record(
    payload: DeliveryPayload,
    sent_meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "message_id": str(sent_meta.get("message_id", "")).strip(),
        "notification_type": payload.notification_type,
        "subject": str(sent_meta.get("subject", "")).strip(),
        "sent_at": str(sent_meta.get("sent_at", "")).strip(),
        "context": {
            "notification_type": payload.notification_type,
            "notices": payload.notices,
            "related_news": payload.related_news,
            "notice_summaries": payload.notice_summaries,
            "deadline_reminders": payload.deadline_reminders,
            "open_tasks": payload.open_tasks,
            "urgent_tasks": payload.urgent_tasks,
            "study_plan": payload.study_plan,
        },
    }


def build_task_receipt_thread_record(
    sent_meta: dict[str, Any],
    thread_subject: str,
    thread_notification_type: str,
    thread_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "message_id": str(sent_meta.get("message_id", "")).strip(),
        "notification_type": str(thread_notification_type or "task_receipt").strip(),
        "subject": str(thread_subject or sent_meta.get("subject", "")).strip(),
        "sent_at": str(sent_meta.get("sent_at", "")).strip(),
        "context": thread_context if isinstance(thread_context, dict) else {},
    }
