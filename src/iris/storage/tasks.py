from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


TASK_STORAGE_VERSION = 2
OPEN_STATUS = "open"
DONE_STATUS = "done"
CANCELLED_STATUS = "cancelled"
MAJOR_IMPORTANCE = "major"
NORMAL_IMPORTANCE = "normal"
MINOR_IMPORTANCE = "minor"
TASK_ID_PATTERN = re.compile(r"T-\d{8}-\d{3}", re.IGNORECASE)
WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
CHINESE_NUMBER_MAP = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
MAJOR_TASK_KEYWORDS = ("考试", "考核", "答辩", "面试", "报名", "申请", "截止", "ddl", "提交", "汇报", "开会", "会议", "作业", "论文", "实验", "项目", "预约", "缴费", "材料", "审批", "签字", "出差", "报销", "值班")
MINOR_TASK_KEYWORDS = ("泡茶", "喝水", "休息", "散步", "拿快递", "取快递", "买东西", "采购", "洗衣服", "收衣服", "打电话", "回消息", "整理", "清理")


@dataclass
class TaskExecutionReport:
    executed: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    changed_task_ids: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.executed) and not self.failures

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_task_ids)


class TaskStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records = self._load()
        if self._backfill_records_on_startup():
            self.save()

    def _backfill_records_on_startup(self) -> bool:
        changed = False
        if int(self.records.get("version", 0)) != TASK_STORAGE_VERSION:
            self.records["version"] = TASK_STORAGE_VERSION
            changed = True
        tasks = self.records.get("tasks", {})
        if not isinstance(tasks, dict):
            self.records["tasks"] = {}
            return True
        for task_id, task in tasks.items():
            if not isinstance(task, dict):
                continue
            before = dict(task)
            task.setdefault("task_id", str(task_id).strip())
            if "manual_reminder_disabled" not in task:
                task["manual_reminder_disabled"] = _normalize_bool(task.get("reminder_disabled", False))
            self._refresh_task_intelligence(task)
            if task != before:
                changed = True
        return changed

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_storage()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("读取任务存储失败，将以内存空状态继续: %s", exc)
            return _empty_storage()
        if not isinstance(data, dict):
            return _empty_storage()
        tasks = data.get("tasks", {})
        meta = data.get("meta", {})
        if not isinstance(tasks, dict):
            tasks = {}
        if not isinstance(meta, dict):
            meta = {}
        daily_sequences = meta.get("daily_sequences", {})
        if not isinstance(daily_sequences, dict):
            daily_sequences = {}
        normalized = _empty_storage()
        normalized["meta"]["daily_sequences"] = {
            str(key): int(value) for key, value in daily_sequences.items()
            if str(key).strip() and str(value).isdigit()
        }
        for task_id, task in tasks.items():
            record = self._normalize_task_record(task_id, task)
            if record:
                normalized["tasks"][record["task_id"]] = record
        return normalized

    def _normalize_task_record(self, task_id: str, record: Any) -> dict[str, Any] | None:
        if not isinstance(record, dict):
            return None
        normalized_id = str(record.get("task_id", task_id)).strip()
        if not normalized_id:
            return None
        status = str(record.get("status", OPEN_STATUS)).strip().lower()
        if status not in {OPEN_STATUS, DONE_STATUS, CANCELLED_STATUS}:
            status = OPEN_STATUS
        estimated_minutes = _normalize_estimated_minutes(record.get("estimated_minutes"))
        due_at = self.normalize_due_value(record.get("due_at", ""), reference=None)
        if not due_at:
            due_at = self.normalize_due_value("", deadline_text=record.get("deadline_text", ""), reference=None)
        created_at = _normalize_datetime_text(record.get("created_at", ""))
        updated_at = _normalize_datetime_text(record.get("updated_at", "")) or created_at
        last_reminded_at = _normalize_datetime_text(record.get("last_reminded_at", ""))
        normalized: dict[str, Any] = {
            "task_id": normalized_id,
            "title": str(record.get("title", "")).strip(),
            "status": status,
            "due_at": due_at,
            "estimated_minutes": estimated_minutes,
            "created_at": created_at,
            "updated_at": updated_at,
            "source_email_message_id": str(record.get("source_email_message_id", "")).strip(),
            "source_email_subject": str(record.get("source_email_subject", "")).strip(),
            "raw_request": str(record.get("raw_request", "")).strip(),
            "last_reminded_at": last_reminded_at,
            "importance": str(record.get("importance", "")).strip().lower(),
            "importance_reason": str(record.get("importance_reason", "")).strip(),
            "reminder_policy": str(record.get("reminder_policy", "")).strip(),
            "next_remind_at": _normalize_datetime_text(record.get("next_remind_at", "")),
            "reminder_count": _normalize_int(record.get("reminder_count"), default=0, minimum=0),
            "reminder_disabled": _normalize_bool(record.get("reminder_disabled", False)),
            "manual_reminder_disabled": _normalize_bool(record.get("manual_reminder_disabled", record.get("reminder_disabled", False))),
        }
        self._refresh_task_intelligence(normalized)
        return normalized

    def save(self) -> None:
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(self.records, file, ensure_ascii=False, indent=2)
        temp_path.replace(self.path)

    def list_open_tasks(self, reference: datetime | None = None, include_overdue: bool = True) -> list[dict[str, Any]]:
        now = reference or datetime.now()
        tasks: list[dict[str, Any]] = []
        for task in self.records["tasks"].values():
            if task.get("status") != OPEN_STATUS:
                continue
            self._refresh_task_intelligence(task)
            due_at = _parse_datetime(task.get("due_at", ""))
            if not include_overdue and due_at is not None and due_at < now:
                continue
            tasks.append(dict(task))
        tasks.sort(key=lambda item: _open_task_sort_key(item, now))
        return tasks

    def list_urgent_tasks(self, window_hours: int, reference: datetime | None = None) -> list[dict[str, Any]]:
        now = reference or datetime.now()
        urgent: list[dict[str, Any]] = []
        for task in self.records["tasks"].values():
            if task.get("status") != OPEN_STATUS:
                continue
            self._refresh_task_intelligence(task)
            if bool(task.get("reminder_disabled", False)):
                continue
            next_remind_at = _parse_datetime(task.get("next_remind_at", ""))
            due_at = _parse_datetime(task.get("due_at", ""))
            if next_remind_at is not None:
                if next_remind_at <= now:
                    urgent.append(dict(task))
                continue
            if due_at is None:
                continue
            upper_bound = now + timedelta(hours=max(int(window_hours), 0))
            if due_at <= upper_bound:
                urgent.append(dict(task))
        urgent.sort(key=lambda item: _urgent_task_sort_key(item, now))
        return urgent

    def mark_tasks_reminded(self, task_ids: list[str], reminded_at: datetime | None = None) -> None:
        timestamp = (reminded_at or datetime.now()).isoformat(timespec="seconds")
        for task_id in task_ids:
            task = self.records["tasks"].get(task_id)
            if not task:
                continue
            task["last_reminded_at"] = timestamp
            task["reminder_count"] = _normalize_int(task.get("reminder_count"), default=0, minimum=0) + 1
            task["updated_at"] = timestamp
            self._refresh_task_intelligence(task)

    def apply_actions(self, actions: list[dict[str, Any]], source_email_message_id: str, source_email_subject: str, raw_request: str, reference: datetime | None = None) -> TaskExecutionReport:
        report = TaskExecutionReport()
        now = reference or datetime.now()
        for action in actions:
            action_type = str(action.get("action_type", "")).strip().lower()
            if action_type == "create_task":
                outcome = self._create_task(action, source_email_message_id, source_email_subject, raw_request, now)
            elif action_type == "update_task":
                outcome = self._update_task(action, now)
            elif action_type == "complete_task":
                outcome = self._change_status(action, DONE_STATUS, now)
            elif action_type == "cancel_task":
                outcome = self._change_status(action, CANCELLED_STATUS, now)
            else:
                outcome = None
                report.failures.append(f"不支持的任务动作: {action_type or '?'}")
                continue
            if outcome is None:
                continue
            if outcome.get("success"):
                report.executed.append(outcome)
                task_id = str(outcome.get("task_id", "")).strip()
                if task_id and task_id not in report.changed_task_ids:
                    report.changed_task_ids.append(task_id)
            else:
                message = str(outcome.get("message", "")).strip()
                if message:
                    report.failures.append(message)
        if report.has_changes:
            self.save()
        return report

    def _create_task(self, action: dict[str, Any], source_email_message_id: str, source_email_subject: str, raw_request: str, now: datetime) -> dict[str, Any]:
        title = str(action.get("title", "")).strip()
        if not title:
            return {"success": False, "message": "缺少任务标题，无法创建任务。"}
        due_at = self.normalize_due_value(action.get("due_at", ""), deadline_text=action.get("deadline_text", ""), reference=now)
        estimated_minutes = _normalize_estimated_minutes(action.get("estimated_minutes"))
        task_id = self._next_task_id(now)
        record: dict[str, Any] = {
            "task_id": task_id, "title": title, "status": OPEN_STATUS,
            "due_at": due_at, "estimated_minutes": estimated_minutes,
            "created_at": now.isoformat(timespec="seconds"),
            "updated_at": now.isoformat(timespec="seconds"),
            "source_email_message_id": source_email_message_id,
            "source_email_subject": source_email_subject,
            "raw_request": raw_request, "last_reminded_at": "",
            "importance": "", "importance_reason": "",
            "reminder_policy": "", "next_remind_at": "",
            "reminder_count": 0, "reminder_disabled": False,
            "manual_reminder_disabled": False,
        }
        self._refresh_task_intelligence(record)
        self.records["tasks"][task_id] = record
        return {
            "success": True, "action_type": "create_task",
            "task_id": task_id, "title": title, "due_at": due_at,
            "estimated_minutes": estimated_minutes, "status": OPEN_STATUS,
            "importance": record.get("importance", NORMAL_IMPORTANCE),
            "importance_reason": record.get("importance_reason", ""),
            "reminder_policy": record.get("reminder_policy", ""),
            "next_remind_at": record.get("next_remind_at", ""),
            "reminder_disabled": record.get("reminder_disabled", False),
            "message": f"已创建任务 {task_id}。",
        }

    def _update_task(self, action: dict[str, Any], now: datetime) -> dict[str, Any]:
        task, error = self._resolve_task_reference(action)
        if task is None:
            return {"success": False, "message": error or "没有找到要更新的任务。"}
        changed_fields: list[str] = []
        title = str(action.get("title", "")).strip()
        if title and title != task.get("title", ""):
            task["title"] = title
            changed_fields.append("标题")
        has_due_directive = any(str(action.get(field, "")).strip() for field in ["due_at", "deadline_text"])
        if has_due_directive:
            due_at = self.normalize_due_value(action.get("due_at", ""), deadline_text=action.get("deadline_text", ""), reference=now)
            if due_at != task.get("due_at", ""):
                task["due_at"] = due_at
                changed_fields.append("截止时间")
        estimated_marker = object()
        raw_estimated = action.get("estimated_minutes", estimated_marker)
        if raw_estimated is not estimated_marker and raw_estimated not in {None, ""}:
            estimated_minutes = _normalize_estimated_minutes(raw_estimated)
            if estimated_minutes != task.get("estimated_minutes"):
                task["estimated_minutes"] = estimated_minutes
                changed_fields.append("预计时长")
        if "disable_reminder" in action:
            disable_reminder = _normalize_bool(action.get("disable_reminder"))
            if disable_reminder != _normalize_bool(task.get("manual_reminder_disabled", False)):
                task["manual_reminder_disabled"] = disable_reminder
                changed_fields.append("提醒设置")
        if not changed_fields:
            return {"success": False, "message": f"任务 {task.get('task_id', '')} 没有检测到可更新的内容。"}
        self._refresh_task_intelligence(task)
        task["updated_at"] = now.isoformat(timespec="seconds")
        return {
            "success": True, "action_type": "update_task",
            "task_id": task.get("task_id", ""), "title": task.get("title", ""),
            "due_at": task.get("due_at", ""), "estimated_minutes": task.get("estimated_minutes"),
            "status": task.get("status", OPEN_STATUS),
            "importance": task.get("importance", NORMAL_IMPORTANCE),
            "importance_reason": task.get("importance_reason", ""),
            "reminder_policy": task.get("reminder_policy", ""),
            "next_remind_at": task.get("next_remind_at", ""),
            "reminder_disabled": task.get("reminder_disabled", False),
            "message": f"已更新任务 {task.get('task_id', '')}：{', '.join(changed_fields)}。",
        }

    def _change_status(self, action: dict[str, Any], target_status: str, now: datetime) -> dict[str, Any]:
        task, error = self._resolve_task_reference(action)
        if task is None:
            action_label = "完成" if target_status == DONE_STATUS else "取消"
            return {"success": False, "message": f"{action_label}任务失败：{error or '没有找到对应任务。'}"}
        if task.get("status") == target_status:
            return {"success": False, "message": f"任务 {task.get('task_id', '')} 已经是{_status_label(target_status)}状态，无需重复操作。"}
        task["status"] = target_status
        self._refresh_task_intelligence(task)
        task["updated_at"] = now.isoformat(timespec="seconds")
        return {
            "success": True,
            "action_type": "complete_task" if target_status == DONE_STATUS else "cancel_task",
            "task_id": task.get("task_id", ""), "title": task.get("title", ""),
            "due_at": task.get("due_at", ""), "estimated_minutes": task.get("estimated_minutes"),
            "status": target_status,
            "importance": task.get("importance", NORMAL_IMPORTANCE),
            "importance_reason": task.get("importance_reason", ""),
            "reminder_policy": task.get("reminder_policy", ""),
            "next_remind_at": task.get("next_remind_at", ""),
            "reminder_disabled": task.get("reminder_disabled", False),
            "message": f"已任务 {task.get('task_id', '')} 标记为{_status_label(target_status)}。",
        }

    def _resolve_task_reference(self, action: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        task_id = _extract_task_id(action.get("target_task_id", "") or action.get("task_id", ""))
        if task_id:
            task = self.records["tasks"].get(task_id)
            if task is not None:
                return task, None
            return None, f"未找到任务 ID {task_id}。"
        raw_title = str(action.get("target_title", "")).strip()
        if not raw_title:
            raw_title = str(action.get("title", "")).strip()
        if not raw_title:
            return None, "缺少任务 ID 或标题。"
        matches = self._match_tasks_by_title(raw_title)
        if not matches:
            return None, f"没有找到标题包含“{raw_title}”的任务。"
        if len(matches) > 1:
            matched_ids = "、".join(task["task_id"] for task in matches[:5])
            return None, f"匹配到多个标题包含“{raw_title}”的任务，请改用任务 ID：{matched_ids}"
        return matches[0], None

    def _match_tasks_by_title(self, raw_title: str) -> list[dict[str, Any]]:
        normalized = _normalize_title(raw_title)
        if not normalized:
            return []
        exact: list[dict[str, Any]] = []
        fuzzy: list[dict[str, Any]] = []
        for task in self.records["tasks"].values():
            if task.get("status") == CANCELLED_STATUS:
                continue
            title = _normalize_title(task.get("title", ""))
            if not title:
                continue
            if title == normalized:
                exact.append(task)
            elif normalized in title or title in normalized:
                fuzzy.append(task)
        return exact or fuzzy

    def _refresh_task_intelligence(self, task: dict[str, Any]) -> None:
        title = str(task.get("title", "")).strip()
        raw_request = str(task.get("raw_request", "")).strip()
        due_at = _parse_datetime(task.get("due_at", ""))
        estimated_minutes = _normalize_estimated_minutes(task.get("estimated_minutes"))
        status = str(task.get("status", OPEN_STATUS)).strip().lower()
        created_at = _parse_datetime(task.get("created_at", "")) or datetime.now()
        last_reminded_at = _parse_datetime(task.get("last_reminded_at", ""))
        manual_reminder_disabled = _normalize_bool(task.get("manual_reminder_disabled", False))
        reference = datetime.now()
        importance, importance_reason = _classify_task_importance(title, raw_request, due_at, estimated_minutes, reference)
        task["importance"] = importance
        task["importance_reason"] = importance_reason
        task["reminder_policy"] = _build_reminder_policy(importance, has_due=due_at is not None)
        task["estimated_minutes"] = estimated_minutes
        if status != OPEN_STATUS:
            task["next_remind_at"] = ""
            task["reminder_disabled"] = True
            return
        if manual_reminder_disabled:
            task["next_remind_at"] = ""
            task["reminder_disabled"] = True
            task["reminder_policy"] = f"{task['reminder_policy']} 已手动关闭提醒".strip()
            return
        schedule = _build_task_reminder_schedule(created_at, due_at, importance)
        next_remind = _next_pending_reminder(schedule, last_reminded_at)
        task["next_remind_at"] = next_remind.isoformat(timespec="seconds") if next_remind else ""
        task["reminder_disabled"] = not bool(schedule and next_remind)

    def _next_task_id(self, now: datetime) -> str:
        date_key = now.strftime("%Y%m%d")
        sequences = self.records["meta"].setdefault("daily_sequences", {})
        current_value = int(sequences.get(date_key, 0)) + 1
        sequences[date_key] = current_value
        return f"T-{date_key}-{current_value:03d}"

    @classmethod
    def normalize_due_value(cls, due_at: Any, deadline_text: Any = "", reference: datetime | None = None) -> str:
        ref = reference or datetime.now()
        for value in [due_at, deadline_text]:
            parsed = _parse_due_text(value, ref)
            if parsed is not None:
                return parsed.isoformat(timespec="seconds")
        return ""


def _empty_storage() -> dict[str, Any]:
    return {"version": TASK_STORAGE_VERSION, "tasks": {}, "meta": {"daily_sequences": {}}}


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_int(value: Any, default: int = 0, minimum: int | None = None) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    if minimum is not None:
        normalized = max(normalized, minimum)
    return normalized


def _normalize_estimated_minutes(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip().lower()
    if not text:
        return None
    if "半小时" in text:
        return 30
    hour_match = re.search(r"(\d+)\s*(?:小时|h|hr|hrs|hour)", text)
    if hour_match:
        return int(hour_match.group(1)) * 60
    minute_match = re.search(r"(\d+)\s*(?:分钟|min|mins|minute|minutes)?", text)
    if minute_match:
        minutes = int(minute_match.group(1))
        return minutes if minutes > 0 else None
    return None


def _normalize_datetime_text(value: Any) -> str:
    if not value:
        return ""
    try:
        cleaned = str(value).strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
        return _to_local_naive(parsed).isoformat(timespec="seconds")
    except ValueError:
        return ""


def _parse_datetime(value: Any) -> datetime | None:
    try:
        cleaned = str(value or "").strip()
        if not cleaned:
            return None
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
        return _to_local_naive(parsed)
    except ValueError:
        return None


def _to_local_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _normalize_title(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _extract_task_id(value: Any) -> str:
    match = TASK_ID_PATTERN.search(str(value or ""))
    return match.group(0).upper() if match else ""


def _status_label(status: str) -> str:
    return {OPEN_STATUS: "进行中", DONE_STATUS: "已完成", CANCELLED_STATUS: "已取消"}.get(str(status).strip().lower(), "未知状态")


def _open_task_sort_key(task: dict[str, Any], now: datetime) -> tuple[int, float, float | int, str]:
    due_at = _parse_datetime(task.get("due_at", ""))
    importance_rank = {MAJOR_IMPORTANCE: 0, NORMAL_IMPORTANCE: 1, MINOR_IMPORTANCE: 2}.get(str(task.get("importance", NORMAL_IMPORTANCE)).strip().lower(), 1)
    if due_at is None:
        return 3, importance_rank, float("inf"), task.get("title", "")
    if due_at < now:
        return 0, importance_rank, due_at.timestamp(), task.get("title", "")
    if due_at <= now + timedelta(hours=24):
        return 1, importance_rank, due_at.timestamp(), task.get("title", "")
    return 2, importance_rank, due_at.timestamp(), task.get("title", "")


def _urgent_task_sort_key(task: dict[str, Any], now: datetime) -> tuple[int, float, float, str]:
    importance_rank = {MAJOR_IMPORTANCE: 0, NORMAL_IMPORTANCE: 1, MINOR_IMPORTANCE: 2}.get(str(task.get("importance", NORMAL_IMPORTANCE)).strip().lower(), 1)
    next_remind_at = _parse_datetime(task.get("next_remind_at", ""))
    due_at = _parse_datetime(task.get("due_at", ""))
    if next_remind_at is not None and next_remind_at <= now:
        return 0, importance_rank, next_remind_at.timestamp(), task.get("title", "")
    if due_at is None:
        return 2, importance_rank, float("inf"), task.get("title", "")
    if due_at < now:
        return 1, importance_rank, due_at.timestamp(), task.get("title", "")
    return 2, importance_rank, due_at.timestamp(), task.get("title", "")


def _parse_due_text(value: Any, reference: datetime) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    normalized = re.sub(r"\s+", "", cleaned.lower())
    normalized = normalized.replace("：", ":").replace("点", ".").replace("点半", ":30").replace("点整", ":00").replace("点钟", ".").replace("星期", "周").replace("礼拜", "周").replace("週", "周")
    for prefix in ["截止时间", "截止", "到期时间", "到期", "due:", "due：", "due"]:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    direct = _parse_absolute_due(normalized, reference)
    if direct is not None:
        return direct
    delayed = _parse_delay_due(normalized, reference)
    if delayed is not None:
        return delayed
    return _parse_relative_due(normalized, reference)


def _parse_absolute_due(text: str, reference: datetime) -> datetime | None:
    full_date = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?(?:[t\s]?(\d{1,2})(?:[点时:](\d{1,2}))?)?", text)
    if full_date:
        year = int(full_date.group(1))
        month = int(full_date.group(2))
        day = int(full_date.group(3))
        hour, minute = (int(full_date.group(4)), int(full_date.group(5) or 0)) if full_date.group(4) is not None else _extract_time(text)
        return _safe_datetime(year, month, day, hour, minute)
    month_day = re.search(r"(\d{1,2})[-/月](\d{1,2})(?:日)?(?:[ t]?(\d{1,2})(?:[点时:](\d{1,2}))?)?", text)
    if month_day:
        month = int(month_day.group(1))
        day = int(month_day.group(2))
        hour, minute = (int(month_day.group(3)), int(month_day.group(4) or 0)) if month_day.group(3) is not None else _extract_time(text)
        candidate = _safe_datetime(reference.year, month, day, hour, minute)
        if candidate is not None and candidate < reference - timedelta(days=30):
            candidate = _safe_datetime(reference.year + 1, month, day, hour, minute)
        return candidate
    return None


def _parse_relative_due(text: str, reference: datetime) -> datetime | None:
    target_date: date | None = None
    if any(token in text for token in ["今天", "今日", "今晚", "今早", "今晨"]):
        target_date = reference.date()
    elif any(token in text for token in ["明天", "明日", "明晚", "明早", "明晨"]):
        target_date = reference.date() + timedelta(days=1)
    elif "后天" in text:
        target_date = reference.date() + timedelta(days=2)
    elif text in {"周末", "这周末", "本周末"}:
        target_date = _next_weekday(reference.date(), 5, include_today=True)
    elif text == "下周末":
        target_date = _next_weekday(reference.date(), 5, include_today=True) + timedelta(days=7)
    else:
        week_match = re.search(r"(?:([本这]周|下周))?周([一二三四五六日天])", text)
        if week_match:
            prefix = week_match.group(1) or ""
            weekday = WEEKDAY_MAP[week_match.group(2)]
            target_date = _next_weekday(reference.date(), weekday, include_today=prefix != "下周")
            if prefix == "下周":
                target_date = target_date + timedelta(days=7)
    if target_date is None:
        return None
    hour, minute = _extract_time(text)
    return _safe_datetime(target_date.year, target_date.month, target_date.day, hour, minute)


def _parse_delay_due(text: str, reference: datetime) -> datetime | None:
    fuzzy_delays: dict[str, timedelta] = {
        "等会": timedelta(minutes=30), "等会儿": timedelta(minutes=30), "待会": timedelta(minutes=30),
        "待会儿": timedelta(minutes=30), "一会": timedelta(minutes=30), "一会儿": timedelta(minutes=30),
        "过会": timedelta(minutes=30), "稍后": timedelta(minutes=30), "晚点": timedelta(hours=2),
        "回头": timedelta(hours=2),
    }
    for keyword, delta in fuzzy_delays.items():
        if keyword in text:
            return reference + delta
    if "半小时后" in text:
        return reference + timedelta(minutes=30)
    match = re.search(r"((?:\d+|[_零一二两三四五六七八九十百半]+))(?:个)?(分钟|分|小时|时|天)?后", text)
    if not match:
        return None
    amount_text = match.group(1)
    amount = 0.5 if amount_text == "半" else (float(parsed) if (parsed := _parse_chinese_number(amount_text)) is not None and parsed > 0 else None)
    if amount is None:
        return None
    unit = match.group(2) or "小时"
    if unit in {"分钟", "分"}:
        return reference + timedelta(minutes=amount)
    if unit in {"小时", "时"}:
        return reference + timedelta(hours=amount)
    target = reference + timedelta(days=amount)
    if re.search(r"(凌晨|早上|上午|中午|下午|傍晚|晚上|今晚|\d{1,2}[点时:]|[零一二三四五六七八九十]{1,3}点)", text):
        hour, minute = _extract_time(text)
        adjusted = _safe_datetime(target.year, target.month, target.day, hour, minute)
        return adjusted or target
    return target


def _parse_chinese_number(value: str) -> int | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return int(cleaned)
    if cleaned == "半":
        return None
    if cleaned == "十":
        return 10
    if len(cleaned) == 2 and cleaned.startswith("十") and cleaned[1] in CHINESE_NUMBER_MAP:
        return 10 + CHINESE_NUMBER_MAP[cleaned[1]]
    if len(cleaned) == 2 and cleaned.endswith("十") and cleaned[0] in CHINESE_NUMBER_MAP:
        return CHINESE_NUMBER_MAP[cleaned[0]] * 10
    if len(cleaned) == 3 and cleaned[1] == "十":
        left = CHINESE_NUMBER_MAP.get(cleaned[0])
        right = CHINESE_NUMBER_MAP.get(cleaned[2])
        if left is not None and right is not None:
            return left * 10 + right
    return CHINESE_NUMBER_MAP.get(cleaned)


def _next_weekday(reference_day: date, weekday: int, include_today: bool) -> date:
    delta = (weekday - reference_day.weekday()) % 7
    if delta == 0 and not include_today:
        delta = 7
    return reference_day + timedelta(days=delta)


def _extract_time(text: str) -> tuple[int, int]:
    time_match = re.search(r"(\d{1,2})(?:[点时:](\d{1,2}))?", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
    else:
        chinese_match = re.search(r"([零一二两三四五六七八九十]{1,3})点(?:([零一二三四五六七八九十]{1,3})分?)?", text)
        if chinese_match:
            hour = _parse_chinese_number(chinese_match.group(1)) or 0
            minute = _parse_chinese_number(chinese_match.group(2) or "") or 0
        else:
            if "凌晨" in text:
                return 1, 0
            if any(token in text for token in ["今早", "今晨", "早上", "上午", "明早", "明晨"]):
                return 9, 0
            if "中午" in text:
                return 12, 0
            if "下午" in text:
                return 15, 0
            if any(token in text for token in ["傍晚", "晚上", "今晚", "明晚"]):
                return 20, 0
            return 23, 59
    if any(token in text for token in ["下午", "傍晚", "晚上", "今晚", "明晚"]) and hour < 12:
        hour += 12
    if "中午" in text and hour < 11:
        hour += 12
    if "凌晨" in text and hour == 12:
        hour = 0
    return hour, minute


def _safe_datetime(year: int, month: int, day: int, hour: int, minute: int) -> datetime | None:
    try:
        return datetime.combine(date(year, month, day), time(hour, minute))
    except ValueError:
        return None


def _classify_task_importance(title: str, raw_request: str, due_at: datetime | None, estimated_minutes: int | None, reference: datetime) -> tuple[str, str]:
    merged_text = f"{title} {raw_request}".strip().lower()
    major_hits = [k for k in MAJOR_TASK_KEYWORDS if k in merged_text]
    minor_hits = [k for k in MINOR_TASK_KEYWORDS if k in merged_text]
    strong_major = [k for k in major_hits if k in {"考试", "考核", "答辩", "面试", "报名", "申请", "截止", "ddl", "提交", "论文", "实验", "项目", "开会", "会议", "缴费", "审批", "签字", "出差", "报销", "值班"}]
    medium_major = [k for k in major_hits if k in {"作业", "汇报", "材料", "预约"}]
    hours_left = (due_at - reference).total_seconds() / 3600 if due_at is not None else None
    if minor_hits and (estimated_minutes or 0) <= 20:
        return MINOR_IMPORTANCE, f"检测到“{minor_hits[0]}”，而且预计很快完成，先按小事处理。"
    if strong_major:
        return MAJOR_IMPORTANCE, f"检测到“{strong_major[0]}”，默认按大事提醒。"
    if medium_major and ((estimated_minutes is not None and estimated_minutes >= 30) or (hours_left is not None and hours_left <= 24)):
        return MAJOR_IMPORTANCE, f"检测到“{medium_major[0]}”，再结合时长或截止时间，按大事处理。"
    if medium_major:
        return NORMAL_IMPORTANCE, f"检测到“{medium_major[0]}”，先按普通优先级处理。"
    if estimated_minutes is not None and estimated_minutes >= 60:
        return MAJOR_IMPORTANCE, "预计时长较长，按大事处理。"
    if due_at is not None:
        if hours_left is not None and hours_left <= 12:
            return MAJOR_IMPORTANCE, "离截止已经很近，按大事处理。"
        if hours_left is not None and hours_left <= 48 and not minor_hits:
            return NORMAL_IMPORTANCE, "离截止不远，按普通优先级持续提醒。"
    if estimated_minutes is not None and estimated_minutes <= 15 and due_at is None:
        return MINOR_IMPORTANCE, "预计很快能做完，先按小事处理。"
    return NORMAL_IMPORTANCE, "没有明显的大事或小事特征，按普通优先级处理。"


def _build_reminder_policy(importance: str, has_due: bool) -> str:
    if has_due:
        if importance == MAJOR_IMPORTANCE:
            return "按截止时间提醒：提前 48/24/6/2 小时，以及到点后跟进。"
        if importance == MINOR_IMPORTANCE:
            return "只在临近截止和到点时提醒。"
        return "按截止时间提醒：提前 24/3 小时，并在到点后跟进。"
    if importance == MAJOR_IMPORTANCE:
        return "会在创建后的第 1/3/7 天早上继续提醒。"
    if importance == MINOR_IMPORTANCE:
        return "默认不主动打扰，等你手动推进。"
    return "会在创建后的第 1/4 天早上轻提醒。"


def _build_task_reminder_schedule(created_at: datetime, due_at: datetime | None, importance: str) -> list[datetime]:
    if due_at is not None:
        offsets = {MAJOR_IMPORTANCE: [-48, -24, -6, -2, 0, 12], NORMAL_IMPORTANCE: [-24, -3, 0, 6], MINOR_IMPORTANCE: [-2, 0]}.get(importance, [-24, -3, 0, 6])
        schedule: list[datetime] = []
        for offset_hours in offsets:
            candidate = due_at + timedelta(hours=offset_hours)
            if candidate >= created_at and candidate not in schedule:
                schedule.append(candidate)
        if not schedule and due_at >= created_at:
            schedule.append(due_at)
        if not schedule and due_at < created_at:
            schedule.append(created_at)
        schedule.sort()
        return schedule
    if importance == MAJOR_IMPORTANCE:
        return [_morning_after(created_at, days=1), _morning_after(created_at, days=3), _morning_after(created_at, days=7)]
    if importance == NORMAL_IMPORTANCE:
        return [_morning_after(created_at, days=1), _morning_after(created_at, days=4)]
    return []


def _next_pending_reminder(schedule: list[datetime], last_reminded_at: datetime | None) -> datetime | None:
    if not schedule:
        return None
    if last_reminded_at is None:
        return schedule[0]
    for candidate in schedule:
        if candidate > last_reminded_at:
            return candidate
    return None


def _morning_after(reference: datetime, days: int) -> datetime:
    return datetime.combine(reference.date() + timedelta(days=max(days, 1)), time(9, 0))
