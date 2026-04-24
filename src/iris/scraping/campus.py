from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests import HTTPError, RequestException

from ._models import Notice


logger = logging.getLogger(__name__)


class CampusScraper:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.runtime = config["runtime"]
        self.timeout = self.runtime["request_timeout"]
        self.max_items_per_portal = self.runtime["max_items_per_portal"]
        self.max_detail_chars = self.runtime["max_detail_chars"]
        self.page_delay_seconds = float(self.runtime.get("page_delay_seconds", 0.0))
        self.request_retries = int(self.runtime.get("request_retries", 2))
        self.retry_backoff_seconds = float(self.runtime.get("retry_backoff_seconds", 1.0))

        self.session = requests.Session()
        self.session.trust_env = bool(self.runtime.get("trust_env_proxy", False))
        self.session.headers.update({
            "User-Agent": self.runtime["user_agent"],
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self.session.headers.update(config.get("request_headers", {}))
        self._apply_cookie_config()
        self._auth_bootstrapped = False

    def collect_notices(self) -> list[Notice]:
        if not self._auth_bootstrapped:
            self._ensure_auth()

        notices: list[Notice] = []
        seen_keys: set[str] = set()
        for portal in self.config.get("portals", []):
            portal_notices = self._collect_portal(portal)
            for notice in portal_notices:
                key = f"{notice.url}\n{notice.title}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                notices.append(notice)
        return notices

    def enrich_notice_content(self, notice: Notice) -> None:
        if notice.content or not notice.detail_selector:
            return
        try:
            html = self._fetch_html(
                notice.url,
                requires_js=notice.requires_js,
                wait_selector=notice.wait_selector,
            )
            soup = BeautifulSoup(html, "html.parser")
            detail_text = self._extract_by_selectors(soup, notice.detail_selector)
            if detail_text:
                notice.content = detail_text[: self.max_detail_chars]
        except Exception as exc:
            logger.warning("抓取详情失败 [%s]: %s", notice.title, exc)

    def _collect_portal(self, portal: dict[str, Any]) -> list[Notice]:
        notices: list[Notice] = []
        url_template = portal.get("url", "").strip()
        if not url_template:
            logger.warning("跳过未配置 url 的门户: %s", portal.get("name", "未命名门户"))
            return notices

        pages = int(portal.get("pages", 1))
        page_start = int(portal.get("page_start", 0))
        selectors = portal.get("selectors", {})
        item_selector = selectors.get("item", "")
        if not item_selector:
            logger.warning("门户缺少 item 选择器: %s", portal.get("name", "未命名门户"))
            return notices

        for page_number in range(page_start, page_start + pages):
            page_url = self._format_page_url(url_template, page_number)
            logger.info("抓取列表页: %s", page_url)
            try:
                html = self._fetch_html(
                    page_url,
                    requires_js=portal.get("requires_js", False),
                    wait_selector=portal.get("wait_selector", ""),
                )
                page_notices = self._parse_list_page(html, page_url, portal)
                notices.extend(page_notices[: self.max_items_per_portal])
            except Exception as exc:
                logger.warning("抓取门户失败 [%s]: %s", portal.get("name", "未命名门户"), exc)
                continue
            if self.page_delay_seconds > 0:
                time.sleep(self.page_delay_seconds)
        return notices[: self.max_items_per_portal]

    def _parse_list_page(
        self, html: str, page_url: str, portal: dict[str, Any]
    ) -> list[Notice]:
        soup = BeautifulSoup(html, "html.parser")
        selectors = portal.get("selectors", {})
        items = soup.select(selectors["item"])
        notices: list[Notice] = []

        for item in items:
            title_node = self._select_relative(item, selectors.get("title"))
            link_node = self._select_relative(item, selectors.get("link")) or title_node
            if not title_node or not link_node:
                continue
            title = self._extract_title(title_node)
            url = self._extract_url(link_node, page_url)
            if not title or not url:
                continue

            published_at = self._extract_text(
                self._select_relative(item, selectors.get("published_at"))
            )
            source = self._extract_text(
                self._select_relative(item, selectors.get("source"))
            ) or portal.get("source", portal.get("name", "校园网"))
            list_summary = self._extract_text(
                self._select_relative(item, selectors.get("summary"))
            )

            notice = Notice(
                portal_name=portal.get("name", "校园网"),
                title=title,
                url=url,
                published_at=published_at,
                source=source,
                list_summary=list_summary,
                detail_selector=selectors.get("detail_content"),
                requires_js=portal.get("requires_js", False),
                wait_selector=portal.get("wait_selector", ""),
                metadata={"page_url": page_url},
            )
            notices.append(notice)
        return notices

    def _ensure_auth(self) -> None:
        if self._auth_bootstrapped:
            return
        self._auth_bootstrapped = True
        auth_config = self.config.get("auth", {})
        if not auth_config.get("enabled"):
            return
        auth_type = auth_config.get("type", "").lower()
        if auth_type != "cas":
            raise ValueError(f"暂不支持的认证类型: {auth_type}")
        self._login_with_cas(auth_config)

    def _login_with_cas(self, auth_config: dict[str, Any]) -> None:
        username = auth_config.get("username", "").strip()
        password = auth_config.get("password", "").strip()
        login_url = auth_config.get("login_url", "").strip()
        service_url = auth_config.get("service_url", "").strip()
        if not username or not password or not login_url:
            raise ValueError("CAS 登录配置不完整，请检查用户名、密码和登录地址。")

        logger.info("开始执行 CAS 登录")
        params = {"service": service_url} if service_url and "service=" not in login_url else None
        first_response = self._request("GET", login_url, params=params)
        first_response.raise_for_status()

        soup = BeautifulSoup(first_response.text, "html.parser")
        form = soup.find("form")
        if form is None:
            raise RuntimeError("CAS 登录页未找到表单。")

        payload: dict[str, str] = {}
        for inp in form.select("input[name]"):
            name = inp.get("name", "").strip()
            if not name:
                continue
            payload[name] = inp.get("value", "")

        payload[auth_config.get("username_field", "username")] = username
        payload[auth_config.get("password_field", "password")] = password
        payload.setdefault("_eventId", "submit")
        payload.setdefault("submit", "登录")
        payload.setdefault("type", "username_password")

        action = form.get("action") or login_url
        submit_url = urljoin(first_response.url, action)
        submit_response = self._request("POST", submit_url, data=payload, allow_redirects=True)
        try:
            submit_response.raise_for_status()
        except HTTPError as exc:
            raise RuntimeError(
                f"CAS 登录被拒绝，HTTP {submit_response.status_code}。"
                "请检查账号密码是否正确，或改用手动导出的 Cookie。"
            ) from exc

        if "login" in submit_response.url.lower() and "authserver" in submit_response.url.lower():
            raise RuntimeError("CAS 登录后仍停留在登录页，请检查账号密码或是否需要验证码。")

        logger.info("CAS 登录成功")

    def _apply_cookie_config(self) -> None:
        cookies = self.config.get("cookies", {})
        cookie_map = cookies.get("map", {}) or {}
        if cookie_map:
            self.session.cookies.update(cookie_map)
            return
        cookie_header = cookies.get("header", "").strip()
        if cookie_header:
            self.session.headers["Cookie"] = cookie_header
            for pair in cookie_header.split(";"):
                if "=" not in pair:
                    continue
                key, value = pair.split("=", 1)
                self.session.cookies.set(key.strip(), value.strip())

    def _fetch_html(
        self, url: str, requires_js: bool = False, wait_selector: str = ""
    ) -> str:
        if requires_js:
            return self._fetch_with_playwright(url, wait_selector)
        response = self._request("GET", url)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        return response.text

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        attempts = max(self.request_retries, 0) + 1
        retry_codes = {429, 500, 502, 503, 504}
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if response.status_code in retry_codes and attempt < attempts:
                    logger.warning(
                        "请求返回 %s，准备重试 %s/%s: %s",
                        response.status_code, attempt, attempts - 1, url,
                    )
                    self._sleep_before_retry(attempt)
                    continue
                return response
            except RequestException as exc:
                last_exc = exc
                if attempt >= attempts:
                    raise
                logger.warning(
                    "请求异常，准备重试 %s/%s [%s %s]: %s",
                    attempt, attempts - 1, method.upper(), url, exc,
                )
                self._sleep_before_retry(attempt)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"请求失败: {method.upper()} {url}")

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff_seconds <= 0:
            return
        time.sleep(self.retry_backoff_seconds * attempt)

    def _fetch_with_playwright(self, url: str, wait_selector: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "页面配置为 requires_js=true，但当前环境未安装 playwright。"
            ) from exc

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.runtime["user_agent"])
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=self.timeout * 1000)
            else:
                page.wait_for_load_state("networkidle", timeout=self.timeout * 1000)
            html = page.content()
            context.close()
            browser.close()
            return html

    @staticmethod
    def _format_page_url(url_template: str, page_number: int) -> str:
        if "{page}" in url_template:
            return url_template.format(page=page_number)
        return url_template

    @staticmethod
    def _select_relative(node: Any, selector: str | None) -> Any:
        if not selector:
            return None
        return node.select_one(selector)

    @staticmethod
    def _extract_title(node: Any) -> str:
        if node is None:
            return ""
        return node.get("title", "").strip() or CampusScraper._extract_text(node)

    @staticmethod
    def _extract_url(node: Any, base_url: str) -> str:
        if node is None:
            return ""
        href = node.get("href", "").strip()
        if not href:
            return ""
        return urljoin(base_url, href)

    @staticmethod
    def _extract_text(node: Any) -> str:
        if node is None:
            return ""
        raw = node.get_text("\n", strip=True)
        lines = []
        for line in raw.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)

    @staticmethod
    def _extract_by_selectors(
        soup: BeautifulSoup, selector_config: str | list[str] | None
    ) -> str:
        selectors: list[str] = []
        if isinstance(selector_config, str) and selector_config.strip():
            selectors = [selector_config.strip()]
        elif isinstance(selector_config, list):
            selectors = [s.strip() for s in selector_config if s.strip()]
        for sel in selectors:
            node = soup.select_one(sel)
            text = CampusScraper._extract_text(node)
            if text:
                return text
        return ""
