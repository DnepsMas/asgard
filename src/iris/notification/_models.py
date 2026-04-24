from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_BRAND_NAME = "阿斯加德"
USER_TITLE = "奥丁"
RAVEN_HEARTBEAT = "Huginn"
RAVEN_DIGEST = "Muninn"
HEARTBEAT_EXPANDED_ITEMS = 3
MORNING_FOCUS_LIMIT = 3
COMPETITION_KEYWORDS = ("竞赛", "报名", "选拔", "训练营", "招募", "申请", "创新")
HEARTBEAT_COMPETITION_KEYWORDS = ("竞赛", "报名", "选拔", "训练营", "招募")
HEARTBEAT_PRIMARY_KEYWORDS = (
    "竞赛", "报名", "选拔", "训练营", "招募", "学生管理", "学籍",
    "奖惩", "处分", "重修", "补修", "选课", "转专业", "保研", "培养方案",
)
HEARTBEAT_SECONDARY_KEYWORDS = (
    "计算机", "沙河", "大一", "大二", "本科生", "新生", "科研", "创新",
)
HEARTBEAT_LOW_SIGNAL_KEYWORDS = ("讲座", "活动安排", "平台", "维护", "申请说明", "办理流程", "举报电话")
HEARTBEAT_PORTAL_PRIORITY = {
    "UCloud 作业": 0,
    "校内通知": 0,
    "规章制度": 1,
    "办事指南": 2,
}
IMPORTANCE_LABELS = {
    "important": "重要",
    "watch": "可关注",
    "ignore": "低优先级",
}


@dataclass
class DeliveryPayload:
    notification_type: str
    notices: list[dict[str, Any]]
    related_news: list[dict[str, Any]] = field(default_factory=list)
    notice_summaries: list[dict[str, Any]] = field(default_factory=list)
    deadline_reminders: list[dict[str, Any]] = field(default_factory=list)
    open_tasks: list[dict[str, Any]] = field(default_factory=list)
    urgent_tasks: list[dict[str, Any]] = field(default_factory=list)
    study_plan: list[str] = field(default_factory=list)


@dataclass
class DeliveryResult:
    success: bool
    message: str
    preview_paths: list[str]
    email_sent: bool = False
    outbound_threads: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OutboundAttachment:
    filename: str
    content: bytes
    mime_type: str = "application/octet-stream"
