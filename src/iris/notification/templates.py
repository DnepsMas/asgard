from __future__ import annotations

import re
from datetime import datetime
from html import escape
from typing import Any

from ._models import IMPORTANCE_LABELS


def section_accent_color(title: str) -> str:
    text = str(title or "").strip()
    if "未来3天截止" in text or "临近截止" in text or "截止提醒" in text:
        return "#f79009"
    if "我的任务" in text:
        return "#12b76a"
    if "昨日" in text:
        return "#667085"
    if "今日" in text:
        return "#4f46e5"
    if "全部作业" in text:
        return "#b54708"
    if "未执行项" in text:
        return "#b42318"
    if "本次处理结果" in text:
        return "#0e9384"
    if "我的回答" in text:
        return "#175cd3"
    return "#175cd3"


def html_section(title: str, body: str) -> str:
    accent_color = section_accent_color(title)
    return (
        """
<section class="email-section" style="margin-top:28px;">
  <h2 class="section-title" style="margin:0 0 14px 0;color:#101828;border-left:6px solid {accent_color};padding-left:10px;font-size:21px;line-height:1.4;">{title}</h2>
  {body}
</section>
""".format(title=escape(title), body=body, accent_color=accent_color).strip()
    )


def html_note(text: str) -> str:
    return (
        '<div class="email-note" style="margin:0;padding:16px;border-radius:16px;background:#ffffff;border:1px solid #e4e7ec;color:#475467;">'
        + '<p class="note-text" style="margin:0;font-size:14px;line-height:1.75;color:#475467;">'
        + escape(text)
        + "</p></div>"
    )


def html_paragraphs(lines: list[str]) -> str:
    return "".join(
        '<p class="lead-text" style="margin:0 0 10px 0;font-size:15px;line-height:1.75;color:#344054;">'
        + escape(line)
        + "</p>"
        for line in lines
    )


def html_tag(text: str, bg_color: str, border_color: str, text_color: str) -> str:
    return (
        '<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
        f'background:{bg_color};border:1px solid {border_color};color:{text_color};'
        'font-size:12px;font-weight:700;line-height:1.4;margin:0 6px 6px 0;">'
        f"{escape(text)}"
        "</span>"
    )


def notice_importance_tag_html(item: dict[str, Any]) -> str:
    importance = str(item.get("ai_result", {}).get("importance", "watch")).strip().lower()
    if importance == "important":
        return html_tag("重要消息", "#fee4e2", "#fecdca", "#b42318")
    if importance == "ignore":
        return html_tag("低优先消息", "#f2f4f7", "#eaecf0", "#475467")
    return html_tag("一般消息", "#eff8ff", "#d1e9ff", "#175cd3")


def task_source_tag_html(task: dict[str, Any]) -> str:
    source_label = _task_source_label(task)
    if source_label == "回复设置任务":
        return html_tag(source_label, "#ecfdf3", "#abefc6", "#067647")
    return html_tag(source_label, "#f9f5ff", "#e9d7fe", "#6941c6")


def _task_source_label(task: dict[str, Any]) -> str:
    source_email_message_id = str(task.get("source_email_message_id", "")).strip()
    if source_email_message_id:
        return "回复设置任务"
    return "自动任务"


def task_importance_tag_html(task: dict[str, Any]) -> str:
    importance = str(task.get("importance", "")).strip().lower()
    if importance == "major":
        return html_tag("大事", "#fef3f2", "#fecdca", "#b42318")
    if importance == "minor":
        return html_tag("小事", "#f2f4f7", "#eaecf0", "#475467")
    return html_tag("普通", "#eff8ff", "#d1e9ff", "#175cd3")


def task_status_tag_html(task: dict[str, Any]) -> str:
    status = str(task.get("status", "")).strip().lower()
    if status == "done":
        return html_tag("已完成", "#ecfdf3", "#abefc6", "#067647")
    if status == "cancelled":
        return html_tag("已取消", "#fff6ed", "#fedf89", "#b54708")
    return html_tag("进行中", "#eff8ff", "#d1e9ff", "#175cd3")


def task_title_html(task: dict[str, Any], include_status_tag: bool = False) -> str:
    tags = [task_source_tag_html(task), task_importance_tag_html(task)]
    if include_status_tag:
        tags.append(task_status_tag_html(task))
    task_id = escape(str(task.get("task_id", "")).strip())
    title = escape(str(task.get("title", "")).strip())
    return (
        '<p style="margin:0 0 8px 0;line-height:1;">' + "".join(tags) + "</p>"
        '<h3 class="card-title" style="margin:0 0 12px 0;font-size:18px;line-height:1.5;color:#101828;">'
        f"[{task_id}] {title}"
        "</h3>"
    )


def notice_title_html(item: dict[str, Any], title: Any) -> str:
    safe_title = escape(str(title or "").strip())
    return (
        '<p style="margin:0 0 8px 0;line-height:1;">' + notice_importance_tag_html(item) + "</p>"
        '<h3 class="card-title" style="margin:0 0 12px 0;font-size:18px;line-height:1.5;color:#101828;">'
        + safe_title
        + "</h3>"
    )


def html_metric_row(items: list[str]) -> str:
    cards = "".join(
        '<div class="metric-card" style="flex:1;min-width:180px;background:#ffffff;border:1px solid #e4e7ec;border-radius:16px;padding:14px;box-sizing:border-box;">'
        '<p class="metric-text" style="margin:0;font-size:14px;line-height:1.6;color:#344054;">'
        + escape(item)
        + "</p></div>"
        for item in items
    )
    return '<section class="metric-row" style="display:flex;gap:12px;flex-wrap:wrap;margin-top:20px;">' + cards + "</section>"


def email_css() -> str:
    return """
body, table, td, p, a {
  -webkit-text-size-adjust: 100%;
  -ms-text-size-adjust: 100%;
}
a {
  color: #175cd3;
  text-decoration: none;
}
.email-shell, .notice-card, .email-note, .metric-card, .footer-banner, .hero, .email-section {
  box-sizing: border-box;
}
.hero-title, .card-title, .card-text, .card-meta, .lead-text, .note-text, .metric-text, .hero-subtitle, .hero-meta {
  word-break: break-word;
  overflow-wrap: anywhere;
}
.card-link {
  word-break: break-word;
  overflow-wrap: anywhere;
}
@media only screen and (max-width: 640px) {
  .email-body { padding:12px 8px !important; }
  .hero { padding:18px !important; border-radius:18px !important; }
  .hero-title { font-size:24px !important; line-height:1.4 !important; }
  .hero-subtitle, .lead-text, .card-text, .footer-banner { font-size:14px !important; line-height:1.75 !important; }
  .hero-meta, .hero-label, .metric-text, .card-meta, .note-text, .card-link { font-size:13px !important; line-height:1.7 !important; }
  .metric-row { display:block !important; margin-top:16px !important; }
  .metric-card { display:block !important; width:100% !important; min-width:0 !important; margin-bottom:10px !important; }
  .email-section { margin-top:20px !important; }
  .section-title { font-size:18px !important; margin-bottom:10px !important; }
  .notice-card, .email-note, .footer-banner { padding:14px !important; border-radius:16px !important; }
  .card-title { font-size:17px !important; line-height:1.5 !important; margin-bottom:10px !important; }
  .card-link { display:block !important; text-align:center !important; padding:11px 14px !important; }
}
""".strip()


def build_email_shell(
    label: str,
    title: str,
    subtitle: str,
    generated_at: datetime,
    accent_start: str,
    accent_end: str,
    metric_items: list[str],
    sections: list[str],
    footer_text: str,
) -> str:
    sections_html = "\n".join(section for section in sections if section)
    metrics_html = html_metric_row(metric_items) if metric_items else ""
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <meta name="x-apple-disable-message-reformatting">
    <style>
      {email_css()}
    </style>
  </head>
  <body class="email-body" style="margin:0;padding:24px 12px;background:#f6f8fb;color:#101828;font-family:'Segoe UI',sans-serif;">
    <main class="email-shell" style="max-width:860px;margin:0 auto;">
      <section class="hero" style="background:linear-gradient(135deg,{accent_start},{accent_end});color:#ffffff;border-radius:22px;padding:24px;">
        <p class="hero-label" style="margin:0 0 8px 0;font-size:14px;line-height:1.6;opacity:0.9;">{escape(label)}</p>
        <h1 class="hero-title" style="margin:0 0 12px 0;font-size:30px;line-height:1.35;color:#ffffff;">{escape(title)}</h1>
        <p class="hero-subtitle" style="margin:0 0 12px 0;font-size:15px;line-height:1.75;opacity:0.92;">{escape(subtitle)}</p>
        <p class="hero-meta" style="margin:0;font-size:13px;line-height:1.6;opacity:0.8;">生成时间：{escape(generated_at.strftime('%Y-%m-%d %H:%M:%S'))}</p>
      </section>
      {metrics_html}
      {sections_html}
      <section class="footer-banner" style="margin-top:28px;padding:18px 20px;border-radius:18px;background:#eef2ff;color:#344054;font-size:15px;line-height:1.75;">
        {escape(footer_text)}
      </section>
    </main>
  </body>
</html>""".strip()


def render_simple_markdown_html(markdown_body: str) -> str:
    blocks = re.split(r"\n\s*\n", str(markdown_body or "").strip())
    html_blocks: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if all(line.startswith(("- ", "* ")) for line in lines):
            items = "".join(
                '<li style="margin:0 0 8px 0;line-height:1.75;color:#344054;">'
                + escape(line[2:].strip())
                + "</li>"
                for line in lines
            )
            html_blocks.append(f'<ul style="margin:0;padding-left:20px;">{items}</ul>')
            continue
        text = "<br>".join(escape(line) for line in lines)
        html_blocks.append(
            '<p style="margin:0;font-size:14px;line-height:1.85;color:#344054;">' + text + "</p>"
        )
    return "".join(html_blocks) or '<p style="margin:0;font-size:14px;line-height:1.75;color:#475467;">（空）</p>'
