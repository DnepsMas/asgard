from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from ..analysis.llm import OpenAIChatGateway
from ..notification._models import DeliveryPayload


logger = logging.getLogger(__name__)


WEEKDAY_CN_TO_ISO = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}


@dataclass
class CourseSlot:
    weekday: int
    start_time: time
    end_time: time
    course_name: str


def build_morning_study_plan(
    payload: DeliveryPayload,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Build a morning study plan from the delivery payload context."""
    if not config:
        return _simple_plan(payload)
    schedule_cfg = config.get("schedule", {})
    if not bool(schedule_cfg.get("enabled", False)):
        return ["课程表规划未启用。"]
    planner = CourseSchedulePlanner(schedule_cfg)
    now = datetime.now()
    slots = planner.load_today_slots(now)
    holiday_signal = planner.detect_holiday_signal(now, payload.notices)
    if holiday_signal.get("today_no_class"):
        slots = []
    free_windows = planner.free_windows_for_today(now, slots)
    lines = planner.compose_fallback_plan_lines(
        now=now, slots=slots, free_windows=free_windows,
        open_tasks=payload.open_tasks,
        homework_notices=_homework_from_notices(payload.notices),
    )
    return planner.normalize_plan_lines(lines, max_lines=8)


def _simple_plan(payload: DeliveryPayload) -> list[str]:
    """Simple plan when no schedule config is available."""
    urgent_count = len(payload.urgent_tasks)
    open_count = len(payload.open_tasks)
    deadline_count = len(payload.deadline_reminders)
    lines: list[str] = []
    if urgent_count:
        lines.append(f"有 {urgent_count} 项紧急任务需要优先处理。")
    if deadline_count:
        lines.append(f"有 {deadline_count} 项通知即将截止。")
    if open_count:
        lines.append(f"待完成任务共 {open_count} 项。")
    if not lines:
        lines.append("当前没有待办任务，可以自由安排学习时间。")
    return lines


def _homework_from_notices(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [n for n in notices if n.get("portal_name") == "UCloud 作业"]


class CourseSchedulePlanner:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.excel_path = Path(str(config.get("excel_path", "")).strip())
        self.sheet_name = str(config.get("sheet_name", "")).strip()
        self.day_start_hour = max(int(config.get("day_start_hour", 8)), 0)
        self.day_end_hour = min(max(int(config.get("day_end_hour", 22)), 1), 23)
        self.max_suggestions = max(int(config.get("max_daily_suggestions", 4)), 1)

    def load_today_slots(self, reference: datetime) -> list[CourseSlot]:
        if not self.excel_path.exists():
            return self._load_manual_schedule(reference)
        try:
            import openpyxl
            wb = openpyxl.load_workbook(self.excel_path, data_only=True)
            sheet = wb[self.sheet_name] if self.sheet_name else wb.active
            return self._parse_excel_slots(sheet, reference)
        except Exception as exc:
            logger.warning("读取课程表失败: %s", exc)
            return self._load_manual_schedule(reference)

    def _load_manual_schedule(self, reference: datetime) -> list[CourseSlot]:
        manual = self.config.get("manual_schedule", [])
        if not isinstance(manual, list):
            return []
        target_wd = reference.isoweekday()
        slots: list[CourseSlot] = []
        for entry in manual:
            if not isinstance(entry, dict):
                continue
            wd_name = str(entry.get("weekday", "")).strip()
            wd = WEEKDAY_CN_TO_ISO.get(wd_name, 0)
            if wd != target_wd:
                continue
            start_str = str(entry.get("start", "08:00")).strip()
            end_str = str(entry.get("end", "09:35")).strip()
            name = str(entry.get("name", "课程")).strip()
            try:
                sh, sm = start_str.split(":")
                eh, em = end_str.split(":")
                slots.append(CourseSlot(
                    weekday=target_wd,
                    start_time=time(int(sh), int(sm)),
                    end_time=time(int(eh), int(em)),
                    course_name=name,
                ))
            except (ValueError, IndexError):
                continue
        return sorted(slots, key=lambda s: s.start_time)

    def _parse_excel_slots(self, sheet: Any, reference: datetime) -> list[CourseSlot]:
        slots: list[CourseSlot] = []
        target_wd = reference.isoweekday()
        try:
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if not row or len(row) < 4:
                    continue
                wd = int(row[0]) if isinstance(row[0], (int, float)) else 0
                if wd != target_wd:
                    continue
                name = str(row[3] or "").strip()
                if not name:
                    continue
                try:
                    st = row[1]
                    et = row[2]
                    if isinstance(st, datetime):
                        st = st.time()
                    if isinstance(et, datetime):
                        et = et.time()
                    slots.append(CourseSlot(
                        weekday=target_wd,
                        start_time=st if isinstance(st, time) else time(8, 0),
                        end_time=et if isinstance(et, time) else time(9, 35),
                        course_name=name,
                    ))
                except (ValueError, TypeError):
                    continue
        except Exception as exc:
            logger.warning("解析 Excel 课程表失败: %s", exc)
        return sorted(slots, key=lambda s: s.start_time)

    def detect_holiday_signal(self, reference: datetime, notice_items: list[dict[str, Any]]) -> dict[str, Any]:
        if not notice_items:
            return {"today_no_class": False, "summary": ""}
        positive_signals: list[str] = []
        for item in notice_items[:80]:
            if not isinstance(item, dict):
                continue
            text = " ".join(str(v) for v in [item.get("title", ""), item.get("ai_result", {}).get("summary", ""), item.get("ai_result", {}).get("reason", "")] if v)
            if re.search(r"放假|停课|不上课|暂停教学|课程暂停|调休", text):
                positive_signals.append(str(item.get("title", "")).strip() or "相关通知")
        if not positive_signals:
            return {"today_no_class": False, "summary": ""}
        return {
            "today_no_class": True,
            "summary": f"检测到可能的放假/停课通知（{'；'.join(positive_signals[:2])}），今日按弹性安排处理。",
        }

    def free_windows_for_today(self, reference: datetime, slots: list[CourseSlot]) -> list[tuple[datetime, datetime]]:
        day_start = datetime.combine(reference.date(), time(self.day_start_hour, 0))
        day_end = datetime.combine(reference.date(), time(self.day_end_hour, 0))
        if not slots:
            return [(day_start, day_end)]
        windows: list[tuple[datetime, datetime]] = []
        current = day_start
        for slot in slots:
            slot_start = datetime.combine(reference.date(), slot.start_time)
            if current < slot_start:
                windows.append((current, slot_start))
            current = datetime.combine(reference.date(), slot.end_time)
        if current < day_end:
            windows.append((current, day_end))
        return windows

    def compose_fallback_plan_lines(
        self,
        now: datetime,
        slots: list[CourseSlot],
        free_windows: list[tuple[datetime, datetime]],
        open_tasks: list[dict[str, Any]],
        homework_notices: list[dict[str, Any]],
    ) -> list[str]:
        lines: list[str] = []
        if slots:
            slot_desc = "、".join(f"{s.course_name}({s.start_time.strftime('%H:%M')}-{s.end_time.strftime('%H:%M')})" for s in slots)
            lines.append(f"今日课程：{slot_desc}")
        elif not free_windows:
            lines.append("今天没有排课，也没有课程表数据，可以自由安排。")
        if free_windows:
            total_free = sum((end - start).seconds for start, end in free_windows) // 60
            lines.append(f"空闲时间共约 {total_free} 分钟。")
        open_count = len(open_tasks)
        hw_count = len(homework_notices)
        if hw_count:
            lines.append(f"待完成作业 {hw_count} 项。")
        if open_count:
            lines.append(f"待办任务 {open_count} 项。")
        return lines

    def normalize_plan_lines(self, lines: list[str], max_lines: int = 8) -> list[str]:
        cleaned = [l for l in lines if l and l.strip()]
        return cleaned[:max_lines]

    def refine_plan_with_llm(
        self,
        config: dict[str, Any],
        reference: datetime,
        open_tasks: list[dict[str, Any]],
        homework_notices: list[dict[str, Any]],
        notice_context: list[dict[str, Any]],
        slots: list[CourseSlot],
        free_windows: list[tuple[datetime, datetime]],
        fallback_lines: list[str],
    ) -> list[str]:
        if not config.get("llm", {}).get("api_key", ""):
            return fallback_lines
        try:
            gateway = OpenAIChatGateway(config)
            prompt = self._build_llm_prompt(reference, open_tasks, homework_notices, slots, free_windows)
            response = gateway.chat_completion("你是一个学习规划助手。", prompt)
            data = json.loads(response)
            if isinstance(data, list):
                return [str(item) for item in data if item]
        except Exception:
            logger.debug("LLM 规划失败，使用备用方案")
        return fallback_lines

    @staticmethod
    def _build_llm_prompt(
        reference: datetime,
        open_tasks: list[dict[str, Any]],
        homework_notices: list[dict[str, Any]],
        slots: list[CourseSlot],
        free_windows: list[tuple[datetime, datetime]],
    ) -> str:
        tasks_str = "; ".join(f"{t.get('title', '?')}(截止:{t.get('due_at','?')})" for t in open_tasks[:5])
        hw_str = "; ".join(h.get("title", "?") for h in homework_notices[:5])
        window_str = "; ".join(f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}" for s, e in free_windows)
        return f"""今天是{reference.strftime('%Y-%m-%d %H:%M')}。
空闲时间段：{window_str or '全天自由'}
待办任务：{tasks_str or '无'}
作业：{hw_str or '无'}
请生成今天的学习计划，输出JSON字符串数组，每条建议一句话。"""
