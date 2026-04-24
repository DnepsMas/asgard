from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any


TASK_STORAGE_VERSION = 2
OPEN_STATUS = "open"
DONE_STATUS = "done"
CANCELLED_STATUS = "cancelled"
MAJOR_IMPORTANCE = "major"
NORMAL_IMPORTANCE = "normal"
MINOR_IMPORTANCE = "minor"
TASK_ID_PATTERN = re.compile(r"T-\d{8}-\d{3}", re.IGNORECASE)
WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
CHINESE_NUMBER_MAP: dict[str, int] = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
MAJOR_TASK_KEYWORDS = ("考试", "考核", "答辩", "面试", "报名", "申请", "截止", "ddl", "提交", "汇报", "开会", "会议", "作业", "论文", "实验", "项目", "预约", "缴费", "材料", "审批", "签字", "出差", "报销", "值班")
MINOR_TASK_KEYWORDS = ("泡茶", "喝水", "休息", "散步", "拿快递", "取快递", "买东西", "采购", "洗衣服", "收衣服", "打电话", "回消息", "整理", "清理")


# Notice storage constants
NOTICE_STORAGE_VERSION = 3
STORAGE_VERSION = 3  # alias for compatibility
ALERTS_ARCHIVE_KEY = "alerts_archive"
DIGEST_ARCHIVE_KEY = "digest_archive"
DEFAULT_NOTIFICATION_STATE: dict[str, Any] = {
    "date": "", "summary_count": 0, "morning_sent": False,
    "heartbeat_sent": False, "evening_sent": False,
}


def normalize_bucket(bucket: str | None) -> str | None:
    if bucket in {"alerts", ALERTS_ARCHIVE_KEY}:
        return ALERTS_ARCHIVE_KEY
    if bucket in {"digest", DIGEST_ARCHIVE_KEY}:
        return DIGEST_ARCHIVE_KEY
    return None


def normalize_deadline(deadline_text: str, published_at: str = "") -> str:
    """Normalize deadline text to ISO datetime string."""
    if not deadline_text:
        return ""
    combined = re.sub(r"\s+", "", deadline_text.lower())
    full = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?", combined)
    if full:
        y, m, d = int(full.group(1)), int(full.group(2)), int(full.group(3))
        time_part = re.search(r"(\d{1,2})[点时:](\d{1,2})?", combined)
        h, mi = (int(time_part.group(1)), int(time_part.group(2) or 0)) if time_part else (23, 59)
        try:
            return datetime(y, m, d, h, mi).isoformat(timespec="seconds")
        except ValueError:
            pass
    month_day = re.search(r"(\d{1,2})[-/月](\d{1,2})(?:日)?", combined)
    if month_day:
        m, d = int(month_day.group(1)), int(month_day.group(2))
        pub = parse_published_date(published_at)
        y = pub.year if pub else datetime.now().year
        try:
            return datetime(y, m, d, 23, 59).isoformat(timespec="seconds")
        except ValueError:
            pass
    return ""


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    cleaned = str(value).strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def parse_published_date(value: str) -> date | None:
    if not value:
        return None
    normalized = value.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", normalized)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def empty_storage() -> dict[str, Any]:
    return {"version": TASK_STORAGE_VERSION, "tasks": {}, "meta": {"daily_sequences": {}}}


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_int(value: Any, default: int = 0, minimum: int | None = None) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    if minimum is not None:
        normalized = max(normalized, minimum)
    return normalized


def normalize_estimated_minutes(value: Any) -> int | None:
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


def normalize_datetime_text(value: Any) -> str:
    if not value:
        return ""
    try:
        cleaned = str(value).strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
        return to_local_naive(parsed).isoformat(timespec="seconds")
    except ValueError:
        return ""


def parse_datetime(value: Any) -> datetime | None:
    try:
        cleaned = str(value or "").strip()
        if not cleaned:
            return None
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
        return to_local_naive(parsed)
    except ValueError:
        return None


def to_local_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def normalize_title(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def extract_task_id(value: Any) -> str:
    match = TASK_ID_PATTERN.search(str(value or ""))
    return match.group(0).upper() if match else ""


def status_label(status: str) -> str:
    return {OPEN_STATUS: "进行中", DONE_STATUS: "已完成", CANCELLED_STATUS: "已取消"}.get(str(status).strip().lower(), "未知状态")


def open_task_sort_key(task: dict[str, Any], now: datetime) -> tuple[int, float, float, str]:
    due_at = parse_datetime(task.get("due_at", ""))
    irank = {MAJOR_IMPORTANCE: 0, NORMAL_IMPORTANCE: 1, MINOR_IMPORTANCE: 2}.get(str(task.get("importance", NORMAL_IMPORTANCE)).strip().lower(), 1)
    if due_at is None:
        return 3, irank, float("inf"), task.get("title", "")
    if due_at < now:
        return 0, irank, due_at.timestamp(), task.get("title", "")
    if due_at <= now + timedelta(hours=24):
        return 1, irank, due_at.timestamp(), task.get("title", "")
    return 2, irank, due_at.timestamp(), task.get("title", "")


def urgent_task_sort_key(task: dict[str, Any], now: datetime) -> tuple[int, float, float, str]:
    irank = {MAJOR_IMPORTANCE: 0, NORMAL_IMPORTANCE: 1, MINOR_IMPORTANCE: 2}.get(str(task.get("importance", NORMAL_IMPORTANCE)).strip().lower(), 1)
    nra = parse_datetime(task.get("next_remind_at", ""))
    due_at = parse_datetime(task.get("due_at", ""))
    if nra is not None and nra <= now:
        return 0, irank, nra.timestamp(), task.get("title", "")
    if due_at is None:
        return 2, irank, float("inf"), task.get("title", "")
    if due_at < now:
        return 1, irank, due_at.timestamp(), task.get("title", "")
    return 2, irank, due_at.timestamp(), task.get("title", "")


def parse_due_text(value: Any, reference: datetime) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    normalized = re.sub(r"\s+", "", cleaned.lower())
    normalized = normalized.replace("：", ":").replace("点半", ":30").replace("点整", ":00").replace("点钟", ".").replace("点", ".").replace("星期", "周").replace("礼拜", "周").replace("週", "周")
    for prefix in ["截止时间", "截止", "到期时间", "到期", "due:", "due：", "due"]:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    direct = parse_absolute_due(normalized, reference)
    if direct is not None:
        return direct
    delayed = parse_delay_due(normalized, reference)
    if delayed is not None:
        return delayed
    return parse_relative_due(normalized, reference)


def parse_absolute_due(text: str, reference: datetime) -> datetime | None:
    full_date = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?(?:[t\s]?(\d{1,2})(?:[点时:](\d{1,2}))?)?", text)
    if full_date:
        year = int(full_date.group(1))
        month = int(full_date.group(2))
        day = int(full_date.group(3))
        hour, minute = (int(full_date.group(4)), int(full_date.group(5) or 0)) if full_date.group(4) is not None else extract_time(text)
        return safe_datetime(year, month, day, hour, minute)
    month_day = re.search(r"(\d{1,2})[-/月](\d{1,2})(?:日)?(?:[ t]?(\d{1,2})(?:[点时:](\d{1,2}))?)?", text)
    if month_day:
        month = int(month_day.group(1))
        day = int(month_day.group(2))
        hour, minute = (int(month_day.group(3)), int(month_day.group(4) or 0)) if month_day.group(3) is not None else extract_time(text)
        candidate = safe_datetime(reference.year, month, day, hour, minute)
        if candidate is not None and candidate < reference - timedelta(days=30):
            candidate = safe_datetime(reference.year + 1, month, day, hour, minute)
        return candidate
    return None


def parse_relative_due(text: str, reference: datetime) -> datetime | None:
    target_date: date | None = None
    if any(t in text for t in ["今天", "今日", "今晚", "今早", "今晨"]):
        target_date = reference.date()
    elif any(t in text for t in ["明天", "明日", "明晚", "明早", "明晨"]):
        target_date = reference.date() + timedelta(days=1)
    elif "后天" in text:
        target_date = reference.date() + timedelta(days=2)
    elif text in {"周末", "这周末", "本周末"}:
        target_date = next_weekday(reference.date(), 5, include_today=True)
    elif text == "下周末":
        target_date = next_weekday(reference.date(), 5, include_today=True) + timedelta(days=7)
    else:
        week_match = re.search(r"(?:([本这]周|下周))?周([一二三四五六日天])", text)
        if week_match:
            prefix = week_match.group(1) or ""
            weekday = WEEKDAY_MAP[week_match.group(2)]
            target_date = next_weekday(reference.date(), weekday, include_today=prefix != "下周")
            if prefix == "下周":
                target_date = target_date + timedelta(days=7)
    if target_date is None:
        return None
    hour, minute = extract_time(text)
    return safe_datetime(target_date.year, target_date.month, target_date.day, hour, minute)


def parse_delay_due(text: str, reference: datetime) -> datetime | None:
    fuzzy: dict[str, timedelta] = {
        "等会": timedelta(minutes=30), "等会儿": timedelta(minutes=30),
        "待会": timedelta(minutes=30), "待会儿": timedelta(minutes=30),
        "一会": timedelta(minutes=30), "一会儿": timedelta(minutes=30),
        "过会": timedelta(minutes=30), "稍后": timedelta(minutes=30),
        "晚点": timedelta(hours=2), "回头": timedelta(hours=2),
    }
    for kw, delta in fuzzy.items():
        if kw in text:
            return reference + delta
    if "半小时后" in text:
        return reference + timedelta(minutes=30)
    match = re.search(r"((?:\d+|[零一二两三四五六七八九十百半]+))(?:个)?(分钟|分|小时|时|天)?后", text)
    if not match:
        return None
    amount_text = match.group(1)
    if amount_text == "半":
        amount_val = 0.5
    else:
        parsed = parse_chinese_number(amount_text)
        if parsed is None or parsed <= 0:
            return None
        amount_val = float(parsed)
    unit = match.group(2) or "小时"
    if unit in {"分钟", "分"}:
        return reference + timedelta(minutes=amount_val)
    if unit in {"小时", "时"}:
        return reference + timedelta(hours=amount_val)
    target = reference + timedelta(days=amount_val)
    if re.search(r"(凌晨|早上|上午|中午|下午|傍晚|晚上|今晚|\d{1,2}[点时:]|[零一二三四五六七八九十]{1,3}点)", text):
        h, m = extract_time(text)
        adjusted = safe_datetime(target.year, target.month, target.day, h, m)
        return adjusted or target
    return target


def parse_chinese_number(value: str) -> int | None:
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


def next_weekday(reference_day: date, weekday: int, include_today: bool) -> date:
    delta = (weekday - reference_day.weekday()) % 7
    if delta == 0 and not include_today:
        delta = 7
    return reference_day + timedelta(days=delta)


def extract_time(text: str) -> tuple[int, int]:
    time_match = re.search(r"(\d{1,2})(?:[点时:](\d{1,2}))?", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
    else:
        cm = re.search(r"([零一二两三四五六七八九十]{1,3})点(?:([零一二三四五六七八九十]{1,3})分?)?", text)
        if cm:
            hour = parse_chinese_number(cm.group(1)) or 0
            minute = parse_chinese_number(cm.group(2) or "") or 0
        else:
            if "凌晨" in text:
                return 1, 0
            if any(t in text for t in ["今早", "今晨", "早上", "上午", "明早", "明晨"]):
                return 9, 0
            if "中午" in text:
                return 12, 0
            if "下午" in text:
                return 15, 0
            if any(t in text for t in ["傍晚", "晚上", "今晚", "明晚"]):
                return 20, 0
            return 23, 59
    if any(t in text for t in ["下午", "傍晚", "晚上", "今晚", "明晚"]) and hour < 12:
        hour += 12
    if "中午" in text and hour < 11:
        hour += 12
    if "凌晨" in text and hour == 12:
        hour = 0
    return hour, minute


def safe_datetime(year: int, month: int, day: int, hour: int, minute: int) -> datetime | None:
    try:
        return datetime.combine(date(year, month, day), time(hour, minute))
    except ValueError:
        return None


def classify_task_importance(title: str, raw_request: str, due_at: datetime | None, estimated_minutes: int | None, reference: datetime) -> tuple[str, str]:
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


def build_reminder_policy(importance: str, has_due: bool) -> str:
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


def build_task_reminder_schedule(created_at: datetime, due_at: datetime | None, importance: str) -> list[datetime]:
    if due_at is not None:
        offsets = {MAJOR_IMPORTANCE: [-48, -24, -6, -2, 0, 12], NORMAL_IMPORTANCE: [-24, -3, 0, 6], MINOR_IMPORTANCE: [-2, 0]}.get(importance, [-24, -3, 0, 6])
        schedule: list[datetime] = []
        for off in offsets:
            cand = due_at + timedelta(hours=off)
            if cand >= created_at and cand not in schedule:
                schedule.append(cand)
        if not schedule and due_at >= created_at:
            schedule.append(due_at)
        if not schedule and due_at < created_at:
            schedule.append(created_at)
        schedule.sort()
        return schedule
    if importance == MAJOR_IMPORTANCE:
        return [morning_after(created_at, days=1), morning_after(created_at, days=3), morning_after(created_at, days=7)]
    if importance == NORMAL_IMPORTANCE:
        return [morning_after(created_at, days=1), morning_after(created_at, days=4)]
    return []


def next_pending_reminder(schedule: list[datetime], last_reminded_at: datetime | None) -> datetime | None:
    if not schedule:
        return None
    if last_reminded_at is None:
        return schedule[0]
    for cand in schedule:
        if cand > last_reminded_at:
            return cand
    return None


def morning_after(reference: datetime, days: int) -> datetime:
    return datetime.combine(reference.date() + timedelta(days=max(days, 1)), time(9, 0))
