from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Notice:
    portal_name: str
    title: str
    url: str
    published_at: str
    source: str
    list_summary: str = ""
    content: str = ""
    notice_id: str = ""
    ai_result: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    detail_selector: str | list[str] | None = None
    requires_js: bool = False
    wait_selector: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "notice_id": self.notice_id,
            "portal_name": self.portal_name,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "source": self.source,
            "list_summary": self.list_summary,
            "content": self.content,
            "ai_result": self.ai_result,
            "metadata": self.metadata,
        }
