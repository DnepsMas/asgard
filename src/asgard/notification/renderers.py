from __future__ import annotations

from html import escape
from typing import Any

from .helpers import (
    action_text,
    count_upcoming_homework,
    count_overdue_homework,
    deadline_display_text,
    deadline_sort_key,
    deadline_datetime,
    deadline_text,
    homework_action_text,
    homework_attachment_line,
    homework_course_label,
    homework_focus_reason,
    homework_summary_text,
    homework_title,
    homework_attachments,
    importance_label,
    reason_text,
    receipt_action_label,
    summary_text,
    task_due_display_text,
    task_estimate_text,
    task_importance_label,
    task_reminder_text,
    task_status_label,
)
from ._models import IMPORTANCE_LABELS
from .templates import (
    html_note,
    html_paragraphs,
    html_section,
    notice_importance_tag_html,
    notice_title_html,
    task_importance_tag_html,
    task_source_tag_html,
    task_status_tag_html,
    task_title_html,
)


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------

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
    import re
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
        meta = [
            f"级别：{task_importance_label(task)}",
            f"截止：{task_due_display_text(task)}",
        ]
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


# ---------------------------------------------------------------------------
# HTML renderers
# ---------------------------------------------------------------------------

def render_notice_html_sections(notices: list[dict[str, Any]]) -> str:
    color_map = {"important": "#b42318", "watch": "#175cd3", "ignore": "#475467"}
    sections: list[str] = []

    for importance in ["important", "watch", "ignore"]:
        bucket = [item for item in notices if item.get("ai_result", {}).get("importance") == importance]
        if not bucket:
            continue

        cards: list[str] = []
        for item in bucket:
            ai_result = item.get("ai_result", {})
            actions_html = ""
            actions = ai_result.get("action_items", [])
            if actions:
                actions_html = "<ul>" + "".join(
                    f"<li>{escape(action)}</li>" for action in actions[:5]
                ) + "</ul>"

            deadline_html = (
                '<p style="margin:0 0 8px 0;"><strong>截止时间:</strong> '
                + escape(deadline_display_text(item))
                + "</p>"
            )

            cards.append(
                """
<article style="border:1px solid #e4e7ec;border-radius:14px;padding:16px;margin-bottom:16px;background:#ffffff;">
  <h3 style="margin:0 0 8px 0;">{title}</h3>
  <p style="margin:0 0 8px 0;color:#475467;">{source} | {portal}</p>
  <p style="margin:0 0 8px 0;"><strong>发布时间:</strong> {published_at}</p>
  <p style="margin:0 0 8px 0;"><strong>分类:</strong> {category}</p>
  <p style="margin:0 0 8px 0;"><strong>AI 摘要:</strong> {summary}</p>
  <p style="margin:0 0 8px 0;"><strong>AI 判断:</strong> {reason}</p>
  {deadline_html}
  {actions_html}
  <p style="margin:12px 0 0 0;"><a href="{url}">查看原文</a></p>
</article>
""".format(
                    title=escape(item.get("title", "")),
                    source=escape(item.get("source", "")),
                    portal=escape(item.get("portal_name", "")),
                    published_at=escape(item.get("published_at", "") or "未知"),
                    category=escape(ai_result.get("category", "综合")),
                    summary=escape(ai_result.get("summary", "")),
                    reason=escape(ai_result.get("reason", "")),
                    deadline_html=deadline_html,
                    actions_html=actions_html,
                    url=escape(item.get("url", "")),
                ).strip()
            )

        sections.append(
            """
<section style="margin-top:28px;">
  <h2 style="color:{color};border-left:6px solid {color};padding-left:10px;">{label}</h2>
  {cards}
</section>
""".format(
                color=color_map[importance],
                label=IMPORTANCE_LABELS[importance],
                cards="\n".join(cards),
            ).strip()
        )

    return "\n".join(sections)


def render_deadline_html_section(reminders: list[dict[str, Any]]) -> str:
    if not reminders:
        return ""

    cards: list[str] = []
    for item in reminders:
        ai_result = item.get("ai_result", {})
        actions = ai_result.get("action_items", [])
        actions_html = ""
        if actions:
            actions_html = "<ul>" + "".join(
                f"<li>{escape(action)}</li>" for action in actions[:3]
            ) + "</ul>"

        cards.append(
            """
<article style="border:1px dashed #f79009;border-radius:14px;padding:16px;margin-bottom:16px;background:#fffaf0;">
  <h3 style="margin:0 0 8px 0;">{title}</h3>
  <p style="margin:0 0 8px 0;"><strong>截止时间:</strong> {deadline}</p>
  <p style="margin:0 0 8px 0;"><strong>分类:</strong> {category}</p>
  <p style="margin:0 0 8px 0;"><strong>摘要:</strong> {summary}</p>
  {actions_html}
  <p style="margin:12px 0 0 0;"><a href="{url}">查看原文</a></p>
</article>
""".format(
                title=escape(item.get("title", "")),
                deadline=escape(deadline_display_text(item)),
                category=escape(ai_result.get("category", "综合")),
                summary=escape(ai_result.get("summary", "")),
                actions_html=actions_html,
                url=escape(item.get("url", "")),
            ).strip()
        )

    return """
<section style="margin-top:28px;">
  <h2 style="color:#b54708;border-left:6px solid #f79009;padding-left:10px;">未来3天截止提醒</h2>
  {cards}
</section>
""".format(cards="\n".join(cards)).strip()


def render_digest_news_html_section(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return ""
    cards = render_notice_html_sections(notices)
    return """
<section style="margin-top:28px;">
  <h2 style="color:#175cd3;border-left:6px solid #175cd3;padding-left:10px;">昨日相关校园新闻</h2>
  {cards}
</section>
""".format(cards=cards).strip()


def render_digest_notice_summary_html_section(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return ""

    cards: list[str] = []
    for item in notices:
        ai_result = item.get("ai_result", {})
        deadline_html = (
            '<p style="margin:0 0 8px 0;"><strong>截止时间:</strong> '
            + escape(deadline_display_text(item))
            + "</p>"
        )
        imp = IMPORTANCE_LABELS.get(ai_result.get("importance", "watch"), "可关注")
        cards.append(
            """
<article style="border:1px solid #e4e7ec;border-radius:14px;padding:16px;margin-bottom:16px;background:#ffffff;">
  <h3 style="margin:0 0 8px 0;">[{importance}] {title}</h3>
  <p style="margin:0 0 8px 0;color:#475467;">{source} | {portal} | {published_at}</p>
  <p style="margin:0 0 8px 0;"><strong>摘要:</strong> {summary}</p>
  {deadline_html}
  <p style="margin:12px 0 0 0;"><a href="{url}">查看原文</a></p>
</article>
""".format(
                importance=escape(imp),
                title=escape(item.get("title", "")),
                source=escape(item.get("source", "")),
                portal=escape(item.get("portal_name", "")),
                published_at=escape(item.get("published_at", "") or "未知"),
                summary=escape(ai_result.get("summary", "")),
                deadline_html=deadline_html,
                url=escape(item.get("url", "")),
            ).strip()
        )

    return """
<section style="margin-top:28px;">
  <h2 style="color:#087443;border-left:6px solid #12b76a;padding-left:10px;">昨日通知总结</h2>
  {cards}
</section>
""".format(cards="\n".join(cards)).strip()


def render_morning_focus_html(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return html_note("今天没有需要你立刻插旗处理的事项。")
    cards: list[str] = []
    for item in notices:
        deadline_html = (
            '<p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;">'
            "<strong>截止：</strong>" + escape(deadline_display_text(item)) + "</p>"
        )
        link_html = ""
        if item.get("url"):
            link_html = (
                '<p class="card-link-row" style="margin:0;padding-top:6px;">'
                '<a class="card-link" href="' + escape(item.get("url", "")) + '" '
                'style="display:inline-block;padding:10px 14px;border-radius:999px;background:#e8efff;color:#175cd3;font-size:14px;font-weight:600;text-decoration:none;">'
                "查看原文</a></p>"
            )
        cards.append(
            """
<article class="notice-card" style="border:1px solid #d0d5dd;border-radius:18px;padding:18px;background:#ffffff;margin-bottom:14px;">
  {title_html}
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>你为什么该看：</strong>{reason}</p>
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>现在建议：</strong>{action}</p>
  {deadline_html}
  {link_html}
</article>
""".format(
                title_html=notice_title_html(item, item.get("title", "")),
                reason=escape(reason_text(item)),
                action=escape(action_text(item)),
                deadline_html=deadline_html,
                link_html=link_html,
            ).strip()
        )
    return "\n".join(cards)


def render_related_news_html(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return html_note("昨日没有筛到与你强相关的校园新闻。")
    cards: list[str] = []
    for item in notices:
        action = action_text(item, fallback="")
        action_html = ""
        if action:
            action_html = (
                '<p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;">'
                "<strong>顺手留意：</strong>" + escape(action) + "</p>"
            )
        cards.append(
            """
<article class="notice-card" style="border:1px solid #d0d5dd;border-radius:18px;padding:18px;background:#ffffff;margin-bottom:14px;">
  <h3 class="card-title" style="margin:0 0 12px 0;font-size:18px;line-height:1.5;color:#101828;">{title}</h3>
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>一句话：</strong>{summary}</p>
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>与你有关：</strong>{reason}</p>
  {action_html}
  <p class="card-link-row" style="margin:0;padding-top:6px;"><a class="card-link" href="{url}" style="display:inline-block;padding:10px 14px;border-radius:999px;background:#e8efff;color:#175cd3;font-size:14px;font-weight:600;text-decoration:none;">查看原文</a></p>
</article>
""".format(
                title=escape(item.get("title", "")),
                summary=escape(summary_text(item)),
                reason=escape(reason_text(item)),
                action_html=action_html,
                url=escape(item.get("url", "")),
            ).strip()
        )
    return "\n".join(cards)


def render_notice_summaries_html(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return html_note("昨日没有新增需要额外记住的通知总结。")
    cards: list[str] = []
    for item in notices:
        deadline_html = (
            '<p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;">'
            "<strong>截止：</strong>" + escape(deadline_display_text(item)) + "</p>"
        )
        cards.append(
            """
<article class="notice-card" style="border:1px solid #d0d5dd;border-radius:18px;padding:18px;background:#ffffff;margin-bottom:14px;">
  {title_html}
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>一句话摘要：</strong>{summary}</p>
  {deadline_html}
  <p class="card-link-row" style="margin:0;padding-top:6px;"><a class="card-link" href="{url}" style="display:inline-block;padding:10px 14px;border-radius:999px;background:#e8efff;color:#175cd3;font-size:14px;font-weight:600;text-decoration:none;">查看原文</a></p>
</article>
""".format(
                title_html=notice_title_html(item, item.get("title", "")),
                summary=escape(summary_text(item)),
                deadline_html=deadline_html,
                url=escape(item.get("url", "")),
            ).strip()
        )
    return "\n".join(cards)


def render_deadline_reminders_html(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return html_note("未来3天没有识别到需要你特别卡点的截止项。")
    cards: list[str] = []
    for item in sorted(notices, key=deadline_sort_key):
        cards.append(
            """
<article class="notice-card notice-card-warning" style="border:1px dashed #f79009;border-radius:18px;padding:18px;background:#fffaeb;margin-bottom:14px;">
  {title_html}
  <p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;"><strong>截止：</strong>{deadline}</p>
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>现在建议：</strong>{action}</p>
  <p class="card-link-row" style="margin:0;padding-top:6px;"><a class="card-link" href="{url}" style="display:inline-block;padding:10px 14px;border-radius:999px;background:#fff4db;color:#b54708;font-size:14px;font-weight:600;text-decoration:none;">查看原文</a></p>
</article>
""".format(
                title_html=notice_title_html(item, item.get("title", "")),
                deadline=escape(deadline_display_text(item)),
                action=escape(action_text(item)),
                url=escape(item.get("url", "")),
            ).strip()
        )
    return "\n".join(cards)


def render_task_digest_html(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return html_note("当前没有未完成任务。")
    cards: list[str] = []
    for task in tasks:
        estimate = task_estimate_text(task)
        estimate_html = (
            '<p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;">'
            "<strong>" + escape(estimate) + "</strong></p>"
        ) if estimate else ""
        cards.append(
            """
<article class="notice-card" style="border:1px solid #d0d5dd;border-radius:18px;padding:18px;background:#ffffff;margin-bottom:14px;">
  {title_html}
  <p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;"><strong>状态：</strong>{status}</p>
  <p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;"><strong>截止：</strong>{due_at}</p>
  {estimate_html}
</article>
""".format(
                title_html=task_title_html(task),
                status=escape(task_status_label(task)),
                due_at=escape(task_due_display_text(task)),
                estimate_html=estimate_html,
            ).strip()
        )
    return "\n".join(cards)


def render_evening_focus_html(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return html_note("今晚没有仍在待办列表中的 UCloud 作业。")
    items: list[str] = []
    for index, item in enumerate(notices, start=1):
        items.append(
            """
<article class="notice-card notice-card-warning" style="border:1px dashed #f79009;border-radius:18px;padding:18px;background:#fffaeb;margin-bottom:14px;">
  <p class="card-kicker" style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:#b54708;font-weight:700;">第 {index} 个推进</p>
  <h3 class="card-title" style="margin:0 0 10px 0;font-size:18px;line-height:1.5;color:#101828;">[{course}] {title}</h3>
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>推进理由：</strong>{reason}</p>
  <p class="card-text" style="margin:0;font-size:15px;line-height:1.75;color:#344054;"><strong>今晚先做到：</strong>{action}</p>
</article>
""".format(
                index=index,
                title=escape(homework_title(item)),
                course=escape(homework_course_label(item)),
                reason=escape(homework_focus_reason(item)),
                action=escape(homework_action_text(item)),
            ).strip()
        )
    return "\n".join(items)


def render_study_plan_html(lines: list[str]) -> str:
    if not lines:
        return html_note("暂无可用建议。")
    items = "\n".join(
        f"<li>{escape(str(line).strip())}</li>"
        for line in lines if str(line).strip()
    )
    if not items:
        return html_note("暂无可用建议。")
    return '<ul style="margin:0;padding-left:22px;line-height:1.8;color:#344054;">' + items + "</ul>"


def render_homework_rollup_html(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return html_note("当前没有待完成作业。")
    cards: list[str] = []
    for item in notices:
        attachment_line = homework_attachment_line(item)
        attachment_html = ""
        if attachment_line:
            attachment_html = (
                '<p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;">'
                "<strong>附件：</strong>" + escape(attachment_line.removeprefix("附件：")) + "</p>"
            )
        cards.append(
            """
<article class="notice-card" style="border:1px solid #d0d5dd;border-radius:18px;padding:18px;background:#ffffff;margin-bottom:14px;">
  <h3 class="card-title" style="margin:0 0 12px 0;font-size:18px;line-height:1.5;color:#101828;">[{course}] {title}</h3>
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>作业内容：</strong>{summary}</p>
  <p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;"><strong>截止：</strong>{deadline}</p>
  {attachment_html}
  <p class="card-link-row" style="margin:0;padding-top:6px;"><a class="card-link" href="{url}" style="display:inline-block;padding:10px 14px;border-radius:999px;background:#e8efff;color:#175cd3;font-size:14px;font-weight:600;text-decoration:none;">查看作业</a></p>
</article>
""".format(
                title=escape(homework_title(item)),
                course=escape(homework_course_label(item)),
                deadline=escape(deadline_display_text(item)),
                summary=escape(homework_summary_text(item)),
                attachment_html=attachment_html,
                url=escape(item.get("url", "")),
            ).strip()
        )
    return "\n".join(cards)


def render_urgent_tasks_html(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return html_note("目前没有到达提醒点的任务。")
    cards: list[str] = []
    for task in tasks:
        estimate = task_estimate_text(task)
        estimate_html = (
            '<p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;">'
            "<strong>" + escape(estimate) + "</strong></p>"
        ) if estimate else ""
        reminder = task_reminder_text(task)
        reminder_html = (
            '<p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;">'
            "<strong>提醒：</strong>" + escape(reminder) + "</p>"
        ) if reminder else ""
        cards.append(
            """
<article class="notice-card notice-card-warning" style="border:1px dashed #f79009;border-radius:18px;padding:18px;background:#fffaeb;margin-bottom:14px;">
  {title_html}
  <p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;"><strong>级别：</strong>{importance}</p>
  <p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;"><strong>截止：</strong>{due_at}</p>
  {estimate_html}
  {reminder_html}
</article>
""".format(
                title_html=task_title_html(task, include_status_tag=True),
                importance=escape(task_importance_label(task)),
                due_at=escape(task_due_display_text(task)),
                estimate_html=estimate_html,
                reminder_html=reminder_html,
            ).strip()
        )
    return "\n".join(cards)


def render_heartbeat_items_html(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return html_note("这一轮没有适合展开的新消息。")
    cards: list[str] = []
    for item in notices:
        meta_lines: list[str] = []
        meta_lines.append(
            '<p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;">'
            "<strong>截止：</strong>" + escape(deadline_display_text(item)) + "</p>"
        )
        if item.get("source"):
            meta_lines.append(
                '<p class="card-meta" style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:#475467;">'
                "<strong>来源：</strong>" + escape(item.get("source", "")) + "</p>"
            )
        cards.append(
            """
<article class="notice-card" style="border:1px solid #d0d5dd;border-radius:18px;padding:18px;background:#ffffff;margin-bottom:14px;">
  {title_html}
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>为什么与你有关：</strong>{reason}</p>
  <p class="card-text" style="margin:0 0 8px 0;font-size:15px;line-height:1.75;color:#344054;"><strong>现在建议：</strong>{action}</p>
  {meta_html}
  <p class="card-link-row" style="margin:0;padding-top:6px;"><a class="card-link" href="{url}" style="display:inline-block;padding:10px 14px;border-radius:999px;background:#e8efff;color:#175cd3;font-size:14px;font-weight:600;text-decoration:none;">查看原文</a></p>
</article>
""".format(
                title_html=notice_title_html(item, item.get("title", "")),
                reason=escape(reason_text(item)),
                action=escape(action_text(item)),
                meta_html="".join(meta_lines),
                url=escape(item.get("url", "")),
            ).strip()
        )
    return "\n".join(cards)


def render_quick_scan_html(notices: list[dict[str, Any]]) -> str:
    if not notices:
        return ""
    items_html: list[str] = []
    for item in notices[:6]:
        tail_parts = [f"截止：{deadline_display_text(item)}"]
        if item.get("source"):
            tail_parts.append(f"来源：{item.get('source', '')}")
        tail_html = ""
        if tail_parts:
            tail_html = (
                '<p class="quick-scan-meta" style="margin:4px 0 0 0;font-size:13px;line-height:1.7;color:#667085;">'
                + escape(" | ".join(tail_parts))
                + "</p>"
            )
        items_html.append(
            """
<li class="quick-scan-item" style="margin:0 0 10px 0;padding:0 0 10px 0;border-bottom:1px solid #eaecf0;list-style:none;">
  <p class="quick-scan-title" style="margin:0;font-size:14px;line-height:1.7;color:#344054;">
    <strong>[{importance}]</strong> {title}
  </p>
  {tail_html}
</li>
""".format(
                importance=escape(importance_label(item)),
                title=escape(item.get("title", "")),
                tail_html=tail_html,
            ).strip()
        )
    summary_html = ""
    if len(notices) > 6:
        summary_html = (
            '<p class="quick-scan-summary" style="margin:6px 0 0 0;font-size:13px;line-height:1.7;color:#667085;">'
            + f"另有 {len(notices) - 6} 条已收起。</p>"
        )
    return """
<div class="email-note quick-scan-box" style="margin:0;padding:16px;border-radius:16px;background:#ffffff;border:1px solid #e4e7ec;color:#475467;">
  <p class="note-text" style="margin:0 0 12px 0;font-size:14px;line-height:1.75;color:#344054;"><strong>其余速览</strong></p>
  <ul class="quick-scan-list" style="margin:0;padding:0;list-style:none;">
    {items_html}
  </ul>
  {summary_html}
</div>
""".format(
        items_html="".join(items_html),
        summary_html=summary_html,
    ).strip()


def render_heartbeat_deadlines_html(notices: list[dict[str, Any]]) -> str:
    deadline_items = [item for item in notices if deadline_text(item)]
    if not deadline_items:
        return html_note("这轮没有识别到明确截止时间。")
    cards: list[str] = []
    ranked_deadlines = sorted(deadline_items, key=deadline_sort_key)
    for item in ranked_deadlines[:3]:
        cards.append(
            """
<article style="border:1px dashed #f79009;border-radius:16px;padding:16px;background:#fffaeb;margin-bottom:14px;">
  <h3 style="margin:0 0 10px 0;">[{importance}] {title}</h3>
  <p style="margin:0 0 6px 0;"><strong>截止：</strong>{deadline}</p>
  <p style="margin:0 0 6px 0;"><strong>现在建议：</strong>{action}</p>
</article>
""".format(
                importance=escape(importance_label(item)),
                title=escape(item.get("title", "")),
                deadline=escape(deadline_display_text(item)),
                action=escape(action_text(item)),
            ).strip()
        )
    if len(ranked_deadlines) > 3:
        cards.append(html_note(f"其余还有 {len(ranked_deadlines) - 3} 条带截止时间的消息，已收进文末速览。"))
    return "\n".join(cards)


# ---------------------------------------------------------------------------
# Task receipt HTML renderers
# ---------------------------------------------------------------------------

def render_task_receipt_results_html(executed_actions: list[dict[str, Any]]) -> str:
    if not executed_actions:
        return '<p style="margin:0;font-size:14px;line-height:1.75;color:#475467;">这次没有成功执行的任务操作。</p>'
    items: list[str] = []
    for item in executed_actions:
        details = [
            f"动作：{receipt_action_label(item)}",
            f"状态：{task_status_label(item)}",
            f"级别：{task_importance_label(item)}",
            f"截止：{task_due_display_text(item)}",
        ]
        estimate = task_estimate_text(item)
        if estimate:
            details.append(estimate)
        reminder = task_reminder_text(item)
        if reminder:
            details.append(f"提醒：{reminder}")
        details_text = " | ".join(details)
        message = escape(str(item.get("message", "")).strip())
        title = escape(str(item.get("title", "")).strip())
        task_id = escape(str(item.get("task_id", "")).strip())
        items.append(
            f'<li style="margin:0 0 10px 0;line-height:1.75;color:#344054;"><strong>[{task_id}] {title}</strong><br>'
            + escape(details_text)
            + f"<br>结果：{message}</li>"
        )
    return '<ul style="margin:0;padding-left:20px;">' + "".join(items) + "</ul>"


def render_task_receipt_answers_html(answers: list[str]) -> str:
    if not answers:
        return '<p style="margin:0;font-size:14px;line-height:1.75;color:#475467;">这次没有单独的信息答复。</p>'
    items = "".join(
        f'<li style="margin:0 0 8px 0;line-height:1.75;color:#344054;">{escape(item)}</li>'
        for item in answers
    )
    return '<ul style="margin:0;padding-left:20px;">' + items + "</ul>"


def render_task_receipt_failures_html(failures: list[str]) -> str:
    if not failures:
        return '<p style="margin:0;font-size:14px;line-height:1.75;color:#475467;">本次没有未执行项。</p>'
    items = "".join(
        f'<li style="margin:0 0 8px 0;line-height:1.75;color:#344054;">{escape(item)}</li>'
        for item in failures
    )
    return '<ul style="margin:0;padding-left:20px;">' + items + "</ul>"
