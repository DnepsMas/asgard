from __future__ import annotations

import re
from typing import Any

from .helpers import (
    action_text,
    deadline_display_text,
    deadline_sort_key,
    deadline_text,
    homework_action_text,
    homework_attachment_line,
    homework_course_label,
    homework_focus_reason,
    homework_summary_text,
    homework_title,
    importance_label,
    reason_text,
    summary_text,
    task_due_display_text,
    task_estimate_text,
    task_importance_label,
    task_reminder_text,
    task_status_label,
)
from ._models import IMPORTANCE_LABELS


def render_digest_notice_summary_markdown(notices: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in notices:
        ai_result = item.get("ai_result", {})
        importance = IMPORTANCE_LABELS.get(ai_result.get("importance", "watch"), "可关注")
        lines.append(f"- [{importance}] {item.get('title', '')}")
        lines.append(
            f"- 来源: {item.get('source', '')} | 栏目: {item.get('portal_name', '')} | 发布时间: {item.get('published_at', '') or '未知'}"
        )
        lines.append(f"- 摘要: {ai_result.get('summary', '')}")
        lines.append(f"- 截止时间: {deadline_display_text(item)}")
        lines.append(f"- 原文链接: {item.get('url', '')}")
        lines.append("")
    return lines


def render_notice_markdown_sections(notices: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for importance in ["important", "watch", "ignore"]:
        bucket = [item for item in notices if item.get("ai_result", {}).get("importance") == importance]
        if not bucket:
            continue
        lines.append(f"### {IMPORTANCE_LABELS[importance]}")
        lines.append("")
        for item in bucket:
            ai_result = item.get("ai_result", {})
            lines.append(f"- 标题: {item.get('title', '')}")
            lines.append(
                f"- 来源: {item.get('source', '')} | 栏目: {item.get('portal_name', '')} | 发布时间: {item.get('published_at', '') or '未知'}"
            )
            lines.append(f"- 分类: {ai_result.get('category', '综合')}")
            lines.append(f"- AI 摘要: {ai_result.get('summary', '')}")
            lines.append(f"- AI 判断: {ai_result.get('reason', '')}")
            lines.append(f"- 截止时间: {deadline_display_text(item)}")
            actions = ai_result.get("action_items", [])
            if actions:
                lines.append(f"- 建议动作: {'；'.join(actions)}")
            lines.append(f"- 原文链接: {item.get('url', '')}")
            lines.append("")
    return lines


def render_deadline_markdown(notices: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in notices:
        ai_result = item.get("ai_result", {})
        lines.append(f"- 标题: {item.get('title', '')}")
        lines.append(f"- 截止时间: {deadline_display_text(item)}")
        lines.append(f"- 分类: {ai_result.get('category', '综合')}")
        lines.append(f"- 摘要: {ai_result.get('summary', '')}")
        actions = ai_result.get("action_items", [])
        if actions:
            lines.append(f"- 建议动作: {'；'.join(actions[:3])}")
        lines.append(f"- 原文链接: {item.get('url', '')}")
        lines.append("")
    return lines


def render_morning_focus_markdown(notices: list[dict[str, Any]]) -> list[str]:
    if not notices:
        return ["- 今天没有需要你立刻插旗处理的事项。", ""]
    lines: list[str] = []
    for item in notices:
        lines.append(f"- [{importance_label(item)}] {item.get('title', '')}")
        lines.append(f"- 你为什么该看：{reason_text(item)}")
        lines.append(f"- 现在建议：{action_text(item)}")
        lines.append(f"- 截止：{deadline_display_text(item)}")
        if item.get("url"):
            lines.append(f"- 原文：{item.get('url', '')}")
        lines.append("")
    return lines


def render_related_news_markdown(notices: list[dict[str, Any]]) -> list[str]:
    if not notices:
        return ["- 昨日没有筛到与你强相关的校园新闻。", ""]
    lines: list[str] = []
    for item in notices:
        lines.append(f"### {item.get('title', '')}")
        lines.append(f"- 一句话：{summary_text(item)}")
        lines.append(f"- 与你有关：{reason_text(item)}")
        action = action_text(item, fallback="")
        if action:
            lines.append(f"- 顺手留意：{action} | 原文：{item.get('url', '')}")
        else:
            lines.append(f"- 原文：{item.get('url', '')}")
        lines.append("")
    return lines


def render_notice_summaries_markdown(notices: list[dict[str, Any]]) -> list[str]:
    if not notices:
        return ["- 昨日没有新增需要额外记住的通知总结。", ""]
    lines: list[str] = []
    for item in notices:
        tail = f"截止：{deadline_display_text(item)} | 原文：{item.get('url', '')}"
        lines.append(f"- [{importance_label(item)}] {item.get('title', '')}")
        lines.append(f"- 一句话摘要：{summary_text(item)}")
        lines.append(f"- {tail}")
        lines.append("")
    return lines


def render_deadline_reminders_markdown(notices: list[dict[str, Any]]) -> list[str]:
    if not notices:
        return ["- 未来3天没有识别到需要你特别卡点的截止项。", ""]
    lines: list[str] = []
    for item in sorted(notices, key=deadline_sort_key):
        lines.append(f"- [{importance_label(item)}] {item.get('title', '')}")
        lines.append(f"- 截止：{deadline_display_text(item)}")
        lines.append(f"- 现在建议：{action_text(item)}")
        lines.append(f"- 原文：{item.get('url', '')}")
        lines.append("")
    return lines


def render_study_plan_markdown(lines_in: list[str]) -> list[str]:
    if not lines_in:
        return ["- 暂无可用建议。", ""]
    rendered: list[str] = []
    for line in lines_in:
        text = str(line).strip()
        if not text:
            continue
        if re.match(r"^\d+\.\s", text):
            rendered.append(text)
        else:
            rendered.append(f"- {text}")
    rendered.append("")
    return rendered


def render_task_digest_markdown(tasks: list[dict[str, Any]]) -> list[str]:
    if not tasks:
        return ["- 当前没有未完成任务。", ""]
    lines: list[str] = []
    for task in tasks:
        meta = [
            f"状态：{task_status_label(task)}",
            f"级别：{task_importance_label(task)}",
            f"截止：{task_due_display_text(task)}",
        ]
        estimated = task_estimate_text(task)
        if estimated:
            meta.append(estimated)
        lines.append(f"- [{task.get('task_id', '')}] {task.get('title', '')}")
        lines.append(f"- {' | '.join(meta)}")
        reminder = task_reminder_text(task)
        if reminder:
            lines.append(f"- 提醒：{reminder}")
        lines.append("")
    return lines


def render_evening_focus_markdown(notices: list[dict[str, Any]]) -> list[str]:
    if not notices:
        return ["- 今晚没有仍在待办列表中的 UCloud 作业。", ""]
    lines: list[str] = []
    for index, item in enumerate(notices, start=1):
        lines.append(f"{index}. [{homework_course_label(item)}] {homework_title(item)}")
        lines.append(f"推进理由：{homework_focus_reason(item)}")
        lines.append(f"今晚先做到：{homework_action_text(item)}")
        lines.append("")
    return lines


def render_homework_rollup_markdown(notices: list[dict[str, Any]]) -> list[str]:
    if not notices:
        return ["- 当前没有待完成作业。", ""]
    lines: list[str] = []
    for item in notices:
        lines.append(f"- [{homework_course_label(item)}] {homework_title(item)}")
        lines.append(f"- 作业内容：{homework_summary_text(item)}")
        lines.append(f"- 截止：{deadline_display_text(item)}")
        attachment = homework_attachment_line(item)
        if attachment:
            lines.append(f"- {attachment}")
        lines.append(f"- 查看作业：{item.get('url', '')}")
        lines.append("")
    return lines


def render_urgent_tasks_markdown(tasks: list[dict[str, Any]]) -> list[str]:
    if not tasks:
        return ["- 目前没有到达提醒点的任务。", ""]
    lines: list[str] = []
    for task in tasks:
        meta = [f"级别：{task_importance_label(task)}", f"截止：{task_due_display_text(task)}"]
        estimated = task_estimate_text(task)
        if estimated:
            meta.append(estimated)
        lines.append(f"- [{task_status_label(task)}] {task.get('task_id', '')} | {task.get('title', '')}")
        lines.append(f"- {' | '.join(meta)}")
        reminder = task_reminder_text(task)
        if reminder:
            lines.append(f"- 提醒：{reminder}")
        lines.append("")
    return lines


def render_heartbeat_items_markdown(notices: list[dict[str, Any]]) -> list[str]:
    if not notices:
        return ["- 这一轮没有适合展开的新消息。", ""]
    lines: list[str] = []
    for item in notices:
        tail_parts = [f"截止：{deadline_display_text(item)}"]
        if item.get("source"):
            tail_parts.append(f"来源：{item.get('source', '')}")
        tail_parts.append(f"原文：{item.get('url', '')}")
        lines.append(f"- [{importance_label(item)}] {item.get('title', '')}")
        lines.append(f"- 为什么与你有关：{reason_text(item)}")
        lines.append(f"- 现在建议：{action_text(item)}")
        lines.append(f"- {' | '.join(tail_parts)}")
        lines.append("")
    return lines


def render_quick_scan_markdown(notices: list[dict[str, Any]]) -> list[str]:
    if not notices:
        return []
    lines = ["其余速览：", ""]
    for item in notices[:6]:
        tail_parts = [f"截止：{deadline_display_text(item)}"]
        if item.get("source"):
            tail_parts.append(f"来源：{item.get('source', '')}")
        title_line = f"- [{importance_label(item)}] {item.get('title', '')}"
        if tail_parts:
            title_line += f" | {' | '.join(tail_parts)}"
        lines.append(title_line)
    if len(notices) > 6:
        lines.append(f"- 另有 {len(notices) - 6} 条已收起。")
    lines.append("")
    return lines


def render_heartbeat_deadlines_markdown(notices: list[dict[str, Any]]) -> list[str]:
    deadline_items = [item for item in notices if deadline_text(item)]
    if not deadline_items:
        return ["- 这轮没有识别到明确截止时间。", ""]
    lines: list[str] = []
    ranked_deadlines = sorted(deadline_items, key=deadline_sort_key)
    for item in ranked_deadlines[:3]:
        lines.append(f"- [{importance_label(item)}] {item.get('title', '')}")
        lines.append(f"- 截止：{deadline_display_text(item)}")
        lines.append(f"- 现在建议：{action_text(item)}")
        lines.append("")
    if len(ranked_deadlines) > 3:
        lines.append(f"- 其余还有 {len(ranked_deadlines) - 3} 条带截止时间的消息，已收进文末速览。")
        lines.append("")
    return lines
