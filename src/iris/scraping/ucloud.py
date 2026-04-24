from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import requests
from bs4 import BeautifulSoup

from ._models import Notice


logger = logging.getLogger(__name__)
RESOURCE_OAUTH_SECRET = "gZTwLteBkHIxHhXFMcQvUMjosqYWPuzTcQwYKpFidkFcradHFm"


class UcloudHomeworkScraper:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.runtime = config["runtime"]
        self.ucloud = config.get("ucloud", {})
        self.timeout = int(self.runtime.get("request_timeout", 15))
        self.max_items = int(self.ucloud.get("max_items", 30))
        self.session = requests.Session()
        self.session.trust_env = bool(self.runtime.get("trust_env_proxy", False))
        self._apply_cookie_config()

    def enabled(self) -> bool:
        return bool(self.ucloud.get("enabled", False)) and bool(self.ucloud.get("base_url", ""))

    def _apply_cookie_config(self) -> None:
        cookie_str = str(self.runtime.get("cookies", "")).strip()
        if not cookie_str:
            return
        try:
            for pair in cookie_str.split(";"):
                pair = pair.strip()
                if "=" not in pair:
                    continue
                key, value = pair.split("=", 1)
                self.session.cookies.set(key.strip(), value.strip())
        except Exception as exc:
            logger.warning("解析 cookie 失败: %s", exc)

    def collect_notices(self) -> list[Notice]:
        if not self.enabled():
            return []
        try:
            self._ensure_auth()
            items = self._fetch_undone_list()
            notices: list[Notice] = []
            for item in items[:self.max_items]:
                try:
                    detail = self._fetch_assignment_detail(item["activity_id"])
                    notice = self._build_notice(item, detail)
                    if notice:
                        notices.append(notice)
                except Exception as exc:
                    logger.warning("获取作业详情失败 (%s): %s", item.get("activity_name", "?"), exc)
            notices.sort(key=lambda n: n.metadata.get("deadline_timestamp", 0))
            return notices
        except Exception as exc:
            logger.error("UCloud 作业抓取失败: %s", exc)
            return []

    def _ensure_auth(self) -> None:
        base_url = str(self.ucloud.get("base_url", "")).rstrip("/")
        ping_url = f"{base_url}/api/assignment/undone-list"
        try:
            resp = self.session.get(ping_url, timeout=self.timeout)
            if resp.status_code < 400:
                return
        except requests.RequestException:
            pass
        self._login_with_bupt_auth_flow()

    def _login_with_bupt_auth_flow(self) -> None:
        base_url = str(self.ucloud.get("base_url", "")).rstrip("/")
        oauth_url = f"{base_url}/oauth2/authorization/bupt-oauth2?{urlencode({'redirect_uri': base_url + '/login/oauth2/code/bupt-oauth2'})}"
        try:
            resp = self.session.get(oauth_url, timeout=self.timeout, allow_redirects=True)
            ticket = self._extract_ticket_from_location(resp.url)
            if not ticket:
                return
            token_data = self._exchange_ticket_for_token(ticket)
            access_token = token_data.get("access_token", "")
            if access_token:
                self.session.headers.update({"Authorization": f"Bearer {access_token}"})
        except Exception as exc:
            logger.warning("UCloud OAuth 登录失败: %s", exc)

    def _fetch_undone_list(self) -> list[dict[str, Any]]:
        base_url = str(self.ucloud.get("base_url", "")).rstrip("/")
        data = self._request_json(f"{base_url}/api/assignment/undone-list")
        items: list[dict[str, Any]] = []
        for entry in data if isinstance(data, list) else data.get("data", []):
            if isinstance(entry, dict) and entry.get("activity_id"):
                items.append({
                    "site_id": str(entry.get("site_id", "")),
                    "site_name": str(entry.get("site_name", "")),
                    "activity_name": str(entry.get("activity_name", "")),
                    "activity_id": str(entry.get("activity_id", "")),
                    "assignment_type": str(entry.get("assignment_type", "")),
                    "end_time": str(entry.get("end_time", "")),
                })
        return items

    def _fetch_assignment_detail(self, activity_id: str) -> dict[str, Any]:
        base_url = str(self.ucloud.get("base_url", "")).rstrip("/")
        return self._request_json(f"{base_url}/api/assignment/{activity_id}")

    def _request_json(self, endpoint: str) -> dict[str, Any]:
        resp = self.session.get(endpoint, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _exchange_ticket_for_token(self, ticket: str) -> dict[str, Any]:
        base_url = str(self.ucloud.get("base_url", "")).rstrip("/")
        resp = self.session.post(
            f"{base_url}/api/oauth2/token",
            json={"ticket": ticket, "secret": RESOURCE_OAUTH_SECRET},
            timeout=self.timeout,
        )
        if resp.status_code == 200:
            return resp.json()
        return {}

    def _extract_ticket_from_location(self, location: str) -> str:
        parsed = urlparse(location)
        params = dict(p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
        return params.get("ticket", "")

    def _build_notice(self, item: dict[str, Any], detail: dict[str, Any]) -> Notice | None:
        title = str(item.get("activity_name", "")).strip()
        if not title:
            return None
        activity_id = item["activity_id"]
        site_name = item.get("site_name", "")
        end_time = item.get("end_time", "")
        deadline_ts = self._parse_deadline_timestamp(end_time)
        content_text = self._extract_content_text(detail)
        attachments = self._extract_attachments(detail)
        md5 = hashlib.md5(f"ucloud:{activity_id}".encode()).hexdigest()[:12]
        return Notice(
            portal_name="UCloud 作业",
            title=f"[{site_name}] {title}" if site_name else title,
            url=self._build_assignment_url(activity_id, title),
            published_at=end_time,
            source="ucloud",
            list_summary=content_text[:200] if content_text else "",
            content=content_text,
            notice_id=f"ucloud-{activity_id}-{md5}",
            metadata={
                "ucloud_attachments": attachments,
                "deadline_timestamp": deadline_ts,
                "activity_id": activity_id,
                "site_name": site_name,
            },
        )

    def _extract_content_text(self, detail: dict[str, Any]) -> str:
        content = detail.get("content", "") or detail.get("instructions", "") or ""
        if isinstance(content, str):
            return self._html_to_text(content)
        return ""

    def _extract_attachments(self, detail: dict[str, Any]) -> list[dict[str, str]]:
        attachments: list[dict[str, str]] = []
        for entry in detail.get("attachments", detail.get("resources", [])):
            if isinstance(entry, dict):
                name = str(entry.get("name", entry.get("filename", ""))).strip()
                resource_id = str(entry.get("id", entry.get("resource_id", ""))).strip()
                if resource_id:
                    attachments.append({"filename": name, "resource_id": resource_id})
        return attachments

    def _build_assignment_url(self, activity_id: str, title: str) -> str:
        base_url = str(self.ucloud.get("base_url", "")).rstrip("/")
        return f"{base_url}/assignment/{activity_id}"

    def _parse_deadline_timestamp(self, end_time: str) -> float:
        cleaned = re.sub(r"\s+", " ", str(end_time or "")).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(cleaned, fmt).timestamp()
            except ValueError:
                continue
        return 0.0

    @staticmethod
    def _html_to_text(html: str) -> str:
        text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
        return re.sub(r"\n{3,}", "\n\n", unescape(text)).strip()
