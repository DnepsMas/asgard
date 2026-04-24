from __future__ import annotations

import json
import logging
import re
from typing import Any

from .llm import OpenAIChatGateway
from ..scraping._models import Notice


logger = logging.getLogger(__name__)

DEFAULT_PRIORITY_KEYWORDS = [
    "计算机学院", "计算机", "程序设计", "大一", "大二",
    "低年级", "新生", "沙河", "选课", "考试", "补考", "成绩",
    "报名", "截止", "奖学金", "助学金", "竞赛", "选拔", "训练营",
    "创新", "实习", "招聘", "保研", "推免", "转专业", "毕业",
    "答辩", "宿舍", "停电", "停水", "校园卡", "网络", "放假",
    "注册", "调课",
]
DEFAULT_IGNORE_KEYWORDS = [
    "干部任免", "正式任职", "试用期满", "售房", "招标", "采购", "党委",
]
IMPORTANCE_ALIASES: dict[str, str] = {
    "important": "important", "high": "important", "urgent": "important",
    "关键": "important", "重要": "important",
    "watch": "watch", "medium": "watch", "关注": "watch", "一般": "watch",
    "ignore": "ignore", "low": "ignore", "忽略": "ignore", "无关": "ignore",
}


class NoticeAIParser:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.assistant_config = config["assistant"]
        self.llm_config = config["llm"]
        self.ai_disabled_reason = ""

        self.priority_keywords = DEFAULT_PRIORITY_KEYWORDS + list(
            self.assistant_config.get("priority_keywords", [])
        )
        self.ignore_keywords = DEFAULT_IGNORE_KEYWORDS + list(
            self.assistant_config.get("ignore_keywords", [])
        )
        self.max_input_chars = int(self.llm_config.get("max_input_chars", 4000))
        self.title_batch_size = int(self.llm_config.get("title_batch_size", 40))
        self.body_batch_size = int(self.llm_config.get("body_batch_size", 8))
        self.body_excerpt_chars = int(self.llm_config.get("body_excerpt_chars", 1800))

        self.client = None
        if (
            self.llm_config.get("enabled")
            and (self.llm_config.get("api_key") or self.llm_config.get("backup_api_key"))
        ):
            gateway = OpenAIChatGateway(
                self.llm_config,
                logger=logger,
                client_label="通知分析",
            )
            if gateway.available:
                self.client = gateway
                logger.info("AI 分析已启用，模型: %s", self.llm_config["model"])
            else:
                logger.warning("AI 分析未启用：OpenAI 配置不可用。")
        elif self.llm_config.get("enabled") and not self.llm_config.get("api_key"):
            logger.warning("AI 分析未启用：缺少 api_key。")
        else:
            logger.info("AI 分析已关闭，将使用规则模式。")

    def triage_titles(self, notices: list[Notice]) -> dict[str, dict[str, Any]]:
        if not notices:
            return {}

        if self.client is None:
            return {n.notice_id: self._fallback_title_triage(n) for n in notices}

        results: dict[str, dict[str, Any]] = {}
        for batch in self._batch(notices, self.title_batch_size):
            try:
                batch_results = self._triage_titles_with_llm(batch)
            except Exception as exc:
                logger.warning("标题初筛失败，回退到规则模式: %s", exc)
                self._disable_ai_after_failure(exc)
                batch_results = {
                    n.notice_id: self._fallback_title_triage(n) for n in batch
                }
            for notice in batch:
                results[notice.notice_id] = batch_results.get(
                    notice.notice_id,
                    self._fallback_title_triage(notice),
                )
        return results

    def refine_notice_bodies(
        self,
        notices: list[Notice],
        title_results: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if not notices:
            return {}

        if self.client is None:
            return {
                n.notice_id: self._fallback_body_refine(n, title_results.get(n.notice_id, {}))
                for n in notices
            }

        results: dict[str, dict[str, Any]] = {}
        for batch in self._batch(notices, self.body_batch_size):
            try:
                batch_results = self._refine_bodies_with_llm(batch, title_results)
            except Exception as exc:
                logger.warning("正文精炼失败，回退到规则模式: %s", exc)
                self._disable_ai_after_failure(exc)
                batch_results = {
                    n.notice_id: self._fallback_body_refine(
                        n, title_results.get(n.notice_id, {})
                    )
                    for n in batch
                }
            for notice in batch:
                results[notice.notice_id] = batch_results.get(
                    notice.notice_id,
                    self._fallback_body_refine(
                        notice, title_results.get(notice.notice_id, {})
                    ),
                )
        return results

    def analyze_notice(self, notice: Notice) -> dict[str, Any]:
        title_result = self.triage_titles([notice]).get(
            notice.notice_id,
            self._fallback_title_triage(notice),
        )
        if title_result["importance"] == "ignore":
            return title_result
        return self.refine_notice_bodies(
            [notice], {notice.notice_id: title_result}
        ).get(
            notice.notice_id,
            self._fallback_body_refine(notice, title_result),
        )

    def _triage_titles_with_llm(self, notices: list[Notice]) -> dict[str, dict[str, Any]]:
        system_prompt = (
            "你是校园网标题初筛助手。"
            "任务是只看标题、来源、栏目和发布时间，判断哪些通知值得进一步阅读全文。"
            "优先考虑用户画像，不要泛泛而谈。"
        )
        items_text: list[str] = []
        for notice in notices:
            items_text.append(
                "\n".join([
                    f"id: {notice.notice_id}",
                    f"title: {notice.title}",
                    f"source: {notice.source}",
                    f"portal: {notice.portal_name}",
                    f"published_at: {notice.published_at}",
                ])
            )

        user_prompt = (
            f"用户画像:\n{self.assistant_config.get('user_profile', '').strip()}\n\n"
            f"附加偏好:\n{self.assistant_config.get('extra_instruction', '').strip()}\n\n"
            "请只输出一个 JSON 对象，不允许输出任何其他说明。\n"
            "格式必须是：\n"
            '{\n  "items": [\n    {\n'
            '      "id": "通知id",\n'
            '      "importance": "important/watch/ignore",\n'
            '      "category": "分类",\n'
            '      "summary": "一句话说明为什么值得或不值得继续看正文",\n'
            '      "reason": "结合用户画像的判断理由",\n'
            '      "deadline": "没有就空字符串",\n'
            '      "action_items": ["没有就空数组"],\n'
            '      "should_fetch_body": true\n    }\n  ]\n}\n\n'
            "候选标题如下：\n\n" + "\n\n".join(items_text)
        )

        parsed = self._call_json(system_prompt, user_prompt)
        items = parsed.get("items", [])
        results: dict[str, dict[str, Any]] = {}
        for item in items:
            notice_id = str(item.get("id", "")).strip()
            if not notice_id:
                continue
            notice = next((e for e in notices if e.notice_id == notice_id), None)
            if notice is None:
                continue
            results[notice_id] = self._normalize_result(item, notice, stage="title")
        return results

    def _refine_bodies_with_llm(
        self,
        notices: list[Notice],
        title_results: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        system_prompt = (
            "你是校园网正文精读助手。"
            "你会接收已经通过标题初筛的校园通知正文，输出精炼、可执行、面向学生的结论。"
            "优先突出与计算机学院、大一大二、沙河校区、竞赛报名和选拔相关的信息。"
        )
        items_text: list[str] = []
        for notice in notices:
            title_result = title_results.get(notice.notice_id, {})
            body = notice.content or notice.list_summary or notice.title
            clipped_body = body[: self.body_excerpt_chars]
            items_text.append(
                "\n".join([
                    f"id: {notice.notice_id}",
                    f"title: {notice.title}",
                    f"source: {notice.source}",
                    f"portal: {notice.portal_name}",
                    f"published_at: {notice.published_at}",
                    f"title_stage_reason: {title_result.get('reason', '')}",
                    f"body:\n{clipped_body}",
                ])
            )

        user_prompt = (
            f"用户画像:\n{self.assistant_config.get('user_profile', '').strip()}\n\n"
            f"附加偏好:\n{self.assistant_config.get('extra_instruction', '').strip()}\n\n"
            "请只输出一个 JSON 对象，不允许输出任何其他说明。\n"
            "格式必须是：\n"
            '{\n  "items": [\n    {\n'
            '      "id": "通知id",\n'
            '      "importance": "important/watch/ignore",\n'
            '      "category": "分类",\n'
            '      "summary": "一句话总结，突出学生真正要知道的内容",\n'
            '      "reason": "为什么和用户相关",\n'
            '      "deadline": "没有就空字符串",\n'
            '      "action_items": ["建议动作"],\n'
            '      "confidence": 0.95\n    }\n  ]\n}\n\n'
            "需要精读的通知正文如下：\n\n" + "\n\n".join(items_text)
        )

        parsed = self._call_json(system_prompt, user_prompt)
        items = parsed.get("items", [])
        results: dict[str, dict[str, Any]] = {}
        for item in items:
            notice_id = str(item.get("id", "")).strip()
            if not notice_id:
                continue
            notice = next((e for e in notices if e.notice_id == notice_id), None)
            if notice is None:
                continue
            results[notice_id] = self._normalize_result(item, notice, stage="body")
        return results

    def _call_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("AI 客户端未初始化。")

        response = self.client.create_chat_completion(
            model=self.llm_config["model"],
            temperature=float(self.llm_config.get("temperature", 0.1)),
            max_tokens=int(self.llm_config.get("max_tokens", 2000)),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[: self.max_input_chars * 4]},
            ],
        )
        raw_content = response.choices[0].message.content or "{}"
        return self._extract_json(raw_content)

    def _disable_ai_after_failure(self, exc: Exception) -> None:
        if self.client is None:
            return
        message = str(exc)
        fatal_markers = ["401", "quota", "额度", "insufficient", "invalid api key", "令牌"]
        if any(m.lower() in message.lower() for m in fatal_markers):
            self.ai_disabled_reason = message
            self.client = None
            logger.warning("后续通知将跳过 AI 请求，直接使用规则模式。原因: %s", message)

    def _fallback_title_triage(self, notice: Notice) -> dict[str, Any]:
        combined = "\n".join(
            p for p in [notice.title, notice.source, notice.portal_name] if p
        )
        importance = self._rule_importance(combined)
        return {
            "importance": importance,
            "category": self._guess_category(combined),
            "summary": notice.title,
            "reason": self._rule_reason(combined, importance, stage="title"),
            "deadline": self._extract_deadline(combined),
            "action_items": [] if importance == "ignore" else ["阅读全文确认细节"],
            "confidence": 0.55 if importance == "watch" else 0.7,
            "analysis_stage": "title",
        }

    def _fallback_body_refine(
        self, notice: Notice, title_result: dict[str, Any]
    ) -> dict[str, Any]:
        combined = "\n".join(
            p for p in [notice.title, notice.source, notice.portal_name, notice.content] if p
        )
        importance = self._rule_importance(combined)
        summary = notice.list_summary or self._excerpt(notice.content) or notice.title
        deadline = self._extract_deadline(combined)
        action_items: list[str] = []
        if deadline:
            action_items.append(f"留意截止时间：{deadline}")
        if importance != "ignore":
            action_items.append("打开原文确认细则与附件")
        return {
            "importance": importance,
            "category": self._guess_category(combined),
            "summary": summary[:120],
            "reason": title_result.get("reason")
            or self._rule_reason(combined, importance, stage="body"),
            "deadline": deadline,
            "action_items": action_items,
            "confidence": 0.6 if importance == "watch" else 0.72,
            "analysis_stage": "body",
        }

    def _normalize_result(
        self, result: dict[str, Any], notice: Notice, stage: str
    ) -> dict[str, Any]:
        importance = IMPORTANCE_ALIASES.get(
            str(result.get("importance", "watch")).strip().lower(), "watch"
        )
        action_items = result.get("action_items", [])
        if not isinstance(action_items, list):
            action_items = [str(action_items)] if action_items else []
        summary = str(result.get("summary", "")).strip()
        if not summary:
            summary = notice.list_summary or self._excerpt(notice.content) or notice.title
        return {
            "importance": importance,
            "category": str(result.get("category", "")).strip()
            or self._guess_category(notice.title),
            "summary": summary[:120],
            "reason": str(result.get("reason", "")).strip() or "AI 未返回原因。",
            "deadline": str(result.get("deadline", "")).strip()
            or self._extract_deadline(notice.content or notice.title),
            "action_items": [
                str(i).strip() for i in action_items if str(i).strip()
            ][:5],
            "confidence": self._safe_float(result.get("confidence", 0.7)),
            "analysis_stage": stage,
        }

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        candidates: list[str] = []
        if "{" in cleaned and "}" in cleaned:
            candidates.append(cleaned[cleaned.find("{") : cleaned.rfind("}") + 1])
        if "[" in cleaned and "]" in cleaned:
            candidates.append(cleaned[cleaned.find("[") : cleaned.rfind("]") + 1])
        candidates.append(cleaned)
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    return {"items": parsed}
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        raise ValueError(f"模型没有返回可解析的 JSON。原始返回: {cleaned[:200]}")

    def _rule_importance(self, text: str) -> str:
        importance = "watch"
        for kw in self.ignore_keywords:
            if kw in text:
                importance = "ignore"
                break
        if importance != "ignore":
            for kw in self.priority_keywords:
                if kw in text:
                    importance = "important"
                    break
        return importance

    def _rule_reason(self, text: str, importance: str, stage: str) -> str:
        if importance == "important":
            if any(k in text for k in ["计算机学院", "计算机", "大一", "大二", "沙河"]):
                return "通知与计算机学院、低年级学生或沙河校区高度相关，值得优先查看。"
            return "通知与学业安排、竞赛报名、选拔机会或重要截止时间高度相关。"
        if importance == "ignore":
            return "从标题看更像行政或背景性信息，对你当前关注方向的直接价值较低。"
        if stage == "title":
            return "标题和来源可能与你有关，建议进入正文进一步确认。"
        return "正文里有一定相关信息，但暂未识别为最高优先级。"

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return 0.7

    @staticmethod
    def _excerpt(text: str, limit: int = 120) -> str:
        return re.sub(r"\s+", " ", text).strip()[:limit]

    @staticmethod
    def _extract_deadline(text: str) -> str:
        normalized = re.sub(r"\s+", "", text)
        patterns = [
            r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?",
            r"\d{1,2}月\d{1,2}日",
            r"\d{1,2}月\d{1,2}日前",
            r"\d{1,2}日\d{1,2}:\d{2}前",
        ]
        for pattern in patterns:
            m = re.search(pattern, normalized)
            if m:
                return m.group(0)
        return ""

    @staticmethod
    def _guess_category(text: str) -> str:
        rules = {
            "计算机院": ["计算机学院", "计算机", "程序设计"],
            "教务": ["选课", "考试", "成绩", "补考", "转专业", "教学"],
            "机会": ["奖学金", "竞赛", "招聘", "实习", "报名", "招募", "选拔", "训练营"],
            "校园生活": ["宿舍", "停水", "停电", "食堂", "超市", "校园卡", "网络", "放假", "沙河"],
            "行政": ["任免", "党委", "干部", "采购", "招标"],
        }
        for category, keywords in rules.items():
            if any(kw in text for kw in keywords):
                return category
        return "综合"

    @staticmethod
    def _batch(items: list[Notice], size: int) -> list[list[Notice]]:
        return [items[i : i + size] for i in range(0, len(items), size)]
