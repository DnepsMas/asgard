from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..analysis.llm import OpenAIChatGateway
from ..storage.tasks import TaskStore


logger = logging.getLogger(__name__)


ALLOWED_ACTION_TYPES = {"create_task", "update_task", "complete_task", "cancel_task"}
TASK_TOOL_NAMES = (*sorted(ALLOWED_ACTION_TYPES), "send_email")
TASK_REQUEST_HINTS = (
    "提醒我", "提醒一个", "提醒", "记得", "记一个", "记下", "帮我记",
    "待办", "todo", "todolist", "新建", "创建", "新增",
    "安排一个", "安排", "计划提醒", "follow up", "follow-up",
)


@dataclass
class TaskParseResult:
    actions: list[dict[str, Any]] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    parser_mode: str = "rule"
    raw_output: str = ""
    ai_failure_message: str = ""

    @property
    def success(self) -> bool:
        return bool(self.actions or self.answers) and not self.errors


class TaskCommandParser:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.llm_config = config["llm"]
        self.max_input_chars = int(self.llm_config.get("max_input_chars", 4000))
        self.client: OpenAIChatGateway | None = None
        if (
            self.llm_config.get("enabled")
            and (self.llm_config.get("api_key") or self.llm_config.get("backup_api_key"))
        ):
            gateway = OpenAIChatGateway(self.llm_config, logger=logger, client_label="任务邮件解析")
            if gateway.available:
                self.client = gateway

    def parse_email(
        self,
        subject: str,
        body: str,
        reference: datetime | None = None,
        thread_context: dict[str, Any] | None = None,
        open_tasks: list[dict[str, Any]] | None = None,
    ) -> TaskParseResult:
        now = reference or datetime.now()
        request_text = compose_request_text(subject, body)
        if not request_text:
            return TaskParseResult(errors=["邮件正文为空，无法识别任务指令。"], parser_mode="empty")

        if self.client is not None:
            try:
                return self._parse_with_llm(subject, body, request_text, now, thread_context or {}, open_tasks or [])
            except Exception as exc:
                logger.warning("任务邮件 AI 解析失败，回退规则模式: %s", exc)
                fallback = self._parse_with_rules(request_text, now, thread_context or {}, open_tasks or [], allow_create_task=False)
                fallback.ai_failure_message = f"任务邮件 AI 解析失败，已先提醒并按有限规则兜底：{exc}"
                return fallback

        return self._parse_with_rules(request_text, now, thread_context or {}, open_tasks or [])

    def _parse_with_llm(self, subject: str, body: str, request_text: str, now: datetime, thread_context: dict[str, Any], open_tasks: list[dict[str, Any]]) -> TaskParseResult:
        if self.client is None:
            raise RuntimeError("AI 客户端未初始化。")

        system_prompt = (
            "你是个人待办任务邮件解析器。"
            "你只负责把自然语言邮件解析成任务操作 JSON，或者在用户只是提问时给出简短回答，不执行任何系统命令。"
            "允许的 action_type 只能是 create_task、update_task、complete_task、cancel_task。"
            "当用户表达不再提醒/恢复提醒时，请使用 update_task，并通过 disable_reminder 字段传递 true/false。"
            "如果用户只是询问当前邮件线程里的内容、截止时间、附件或现有任务情况，就把回答写进 answers，actions 保持空数组。"
            "如果信息不足，就把原因写进 errors，不要猜。"
        )
        user_prompt = (
            f"当前本地时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            "请只输出一个 JSON 对象，不允许输出任何解释。\n"
            '格式必须是:\n{\n'
            '  "actions": [\n'
            "    {\n"
            '      "action_type": "create_task/update_task/complete_task/cancel_task",\n'
            '      "target_task_id": "没有就空字符串",\n'
            '      "target_title": "没有就空字符串",\n'
            '      "title": "create/update 时的新标题，没有就空字符串",\n'
            '      "due_at": "标准时间或空字符串，例如 2026-03-25 23:59",\n'
            '      "deadline_text": "原始时间表达，没有就空字符串",\n'
            '      "estimated_minutes": 60,\n'
            '      "disable_reminder": true,\n'
            '      "reason": "解析依据，简短说明"\n'
            "    }\n"
            "  ],\n"
            '  "answers": ["用户只是发问时的简短答复，没有就空数组"],\n'
            '  "errors": ["没有就空数组"]\n'
            "}\n\n"
            f"回复线程上下文:\n{compact_thread_context(thread_context, open_tasks)}\n\n"
            f"主题:\n{subject.strip()}\n\n"
            f"正文:\n{body.strip()}\n\n"
            f"合并后的任务请求:\n{request_text}"
        )

        response = self.client.create_chat_completion(
            model=self.llm_config["model"],
            temperature=float(self.llm_config.get("temperature", 0.1)),
            max_tokens=int(self.llm_config.get("max_tokens", 1600)),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:self.max_input_chars * 4]},
            ],
        )
        raw_output = response.choices[0].message.content or "{}"
        parsed = extract_json(raw_output)
        actions = _normalize_actions(parsed.get("actions", []), now)
        answers = [str(item).strip() for item in parsed.get("answers", []) if str(item).strip()]
        errors = [str(item).strip() for item in parsed.get("errors", []) if str(item).strip()]
        if not actions and not answers and not errors:
            errors.append("AI 没有解析出可执行的任务操作，也没有给出可用答复。")
        return TaskParseResult(actions=actions, answers=answers, errors=errors, parser_mode="ai", raw_output=raw_output)

    # ---- Rule-based parsing methods ----

    def _parse_with_rules(self, request_text: str, now: datetime, thread_context: dict[str, Any], open_tasks: list[dict[str, Any]], allow_create_task: bool = True) -> TaskParseResult:
        actions: list[dict[str, Any]] = []
        answers: list[str] = []
        errors: list[str] = []
        lines = sanitize_request_lines(request_text)
        if not lines:
            return TaskParseResult(errors=["邮件正文为空或只有签名噪音，无法识别任务指令。"], parser_mode="rule")

        combined = "\n".join(lines).strip()
        collapsed = re.sub(r"\s+", "", combined.lower())
        no_create_tokens = {"不用创建任务", "别创建任务", "不要创建任务", "只需要回答", "只要回答", "只回答", "不用记任务", "不是任务"}
        if any(t in collapsed for t in no_create_tokens):
            answers = _answer_with_rules(combined, thread_context, open_tasks)
            if not answers:
                answers = ["这次按普通回复处理，没有创建新任务。"]
            return TaskParseResult(actions=actions, answers=answers, parser_mode="rule")

        multi_create = _looks_like_multi_create(lines)
        if multi_create and allow_create_task:
            for line in lines:
                action = _build_create_action(line, now)
                if action is None:
                    errors.append(f"无法从这一行识别任务：{line}")
                    continue
                actions.append(action)
            return TaskParseResult(actions=actions, answers=answers, errors=errors, parser_mode="rule")
        if multi_create and not allow_create_task:
            errors.append("AI 解析失败后，本次规则兜底不会自动批量新建任务；请等待 AI 恢复后重试。")
            return TaskParseResult(actions=actions, answers=answers, errors=errors, parser_mode="rule")

        task_id = extract_task_id(combined)
        if any(t in combined for t in ["完成", "done", "已完成"]):
            actions.append({"action_type": "complete_task", "target_task_id": task_id, "target_title": _extract_target_title(combined, task_id), "title": "", "due_at": "", "deadline_text": "", "estimated_minutes": None, "disable_reminder": None, "reason": "规则识别为完成任务。"})
            return TaskParseResult(actions=actions, answers=answers, parser_mode="rule")

        if any(t in combined for t in ["取消", "作废", "不用做", "撤销"]):
            actions.append({"action_type": "cancel_task", "target_task_id": task_id, "target_title": _extract_target_title(combined, task_id), "title": "", "due_at": "", "deadline_text": "", "estimated_minutes": None, "disable_reminder": None, "reason": "规则识别为取消任务。"})
            return TaskParseResult(actions=actions, answers=answers, parser_mode="rule")

        if any(t in combined for t in ["不再提醒", "别提醒", "停止提醒", "不用再提醒", "先别提醒", "免打扰"]):
            actions.append({"action_type": "update_task", "target_task_id": task_id, "target_title": _extract_target_title(combined, task_id), "title": "", "due_at": "", "deadline_text": "", "estimated_minutes": None, "disable_reminder": True, "reason": "规则识别为关闭任务提醒。"})
            return TaskParseResult(actions=actions, answers=answers, parser_mode="rule")

        if any(t in combined for t in ["恢复提醒", "继续提醒", "重新提醒", "重新开始提醒"]):
            actions.append({"action_type": "update_task", "target_task_id": task_id, "target_title": _extract_target_title(combined, task_id), "title": "", "due_at": "", "deadline_text": "", "estimated_minutes": None, "disable_reminder": False, "reason": "规则识别为恢复任务提醒。"})
            return TaskParseResult(actions=actions, answers=answers, parser_mode="rule")

        if any(t in combined for t in ["更新", "修改", "改成", "改到", "延期", "顺延"]):
            title = _extract_new_title(combined)
            due_text = extract_due_phrase(combined)
            actions.append({"action_type": "update_task", "target_task_id": task_id, "target_title": _extract_target_title(combined, task_id), "title": title, "due_at": TaskStore.normalize_due_value("", due_text, now), "deadline_text": due_text, "estimated_minutes": extract_estimated_minutes(combined), "disable_reminder": None, "reason": "规则识别为更新任务。"})
            return TaskParseResult(actions=actions, answers=answers, parser_mode="rule")

        if _looks_like_plain_question(combined, thread_context, open_tasks):
            answers = _answer_with_rules(combined, thread_context, open_tasks)
            if not answers:
                answers = ["我这次按普通问答处理，没有创建新任务。"]
            return TaskParseResult(actions=actions, answers=answers, errors=errors, parser_mode="rule")

        create_action = _build_create_action(combined, now) if allow_create_task else None
        if create_action is None:
            if not allow_create_task and _looks_like_task_line(combined):
                errors.append("AI 解析失败后，本次规则兜底不会自动新建任务；如需创建任务，请在下一封邮件中明确说明或等待 AI 恢复。")
            elif _looks_like_question(combined):
                answers = _answer_with_rules(combined, thread_context, open_tasks)
                if not answers:
                    answers = ["我理解成你是在提问，所以没有创建任务。"]
            else:
                errors.append("规则模式没有识别出可执行的任务操作，请在邮件里明确写出要创建、更新、完成或取消的任务。")
        else:
            actions.append(create_action)
        return TaskParseResult(actions=actions, answers=answers, errors=errors, parser_mode="rule")


# ---- Module-level helper functions (shared with agent.py) ----


def normalize_optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "open", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "close", "disable", "disabled"}:
        return False
    return None


def compact_thread_context(thread_context: dict[str, Any], open_tasks: list[dict[str, Any]]) -> str:
    payload: dict[str, Any] = {
        "notification_type": thread_context.get("notification_type", ""),
        "notices": [{"title": item.get("title", ""), "summary": item.get("ai_result", {}).get("summary", ""), "deadline": item.get("ai_result", {}).get("deadline", ""), "attachments": item.get("metadata", {}).get("ucloud_attachments", []), "url": item.get("url", "")} for item in thread_context.get("notices", [])[:8] if isinstance(item, dict)],
        "open_tasks": [{"task_id": item.get("task_id", ""), "title": item.get("title", ""), "due_at": item.get("due_at", "")} for item in open_tasks[:12] if isinstance(item, dict)],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def extract_json(raw_content: str) -> dict[str, Any]:
    cleaned = str(raw_content or "").strip()
    if not cleaned:
        return {}
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def extract_task_id(value: Any) -> str:
    match = re.search(r"T-\d{8}-\d{3}", str(value or ""), re.IGNORECASE)
    return match.group(0).upper() if match else ""


def compose_request_text(subject: str, body: str) -> str:
    subject_text = str(subject or "").strip()
    body_text = str(body or "").strip()
    if re.fullmatch(r"(新建任务|创建任务|新增任务|更新任务|修改任务|完成任务|取消任务|任务)", subject_text):
        subject_text = ""
    if subject_text and body_text:
        return f"{subject_text}\n{body_text}".strip()
    return subject_text or body_text


def sanitize_request_lines(request_text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in str(request_text or "").splitlines():
        cleaned = _clean_line(raw_line)
        if not cleaned:
            continue
        if _is_signature_start(cleaned):
            break
        if _is_noise_line(cleaned):
            continue
        lines.append(cleaned)
    return lines


def _clean_line(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^[>\-*\d\.\)\(、\s]+", "", cleaned)
    return cleaned.strip()


def _is_signature_start(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if "get outlook for android" in lowered:
        return True
    if lowered.startswith(("from:", "sent:", "to:", "subject:", "发件人:", "发送时间:", "收件人:", "主题:")):
        return True
    if lowered.startswith(("sent from my", "发自我的 iphone", "发自我的 ipad", "发自我的 android")):
        return True
    return bool(re.fullmatch(r"[_=\-]{6,}", lowered))


def _is_noise_line(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return True
    if _is_signature_start(lowered):
        return True
    if re.fullmatch(r"https?://\S+", lowered):
        return True
    if re.fullmatch(r"[_=\-]{4,}", lowered):
        return True
    return False


def _looks_like_multi_create(lines: list[str]) -> bool:
    effective_lines = [line for line in lines if not re.fullmatch(r"(新建任务|创建任务|新增任务|任务|待办)", line)]
    if len(effective_lines) < 2:
        return False
    if any(_looks_like_question(line) for line in effective_lines):
        return False
    return all(_looks_like_task_line(line) for line in effective_lines)


def _looks_like_task_line(text: str) -> bool:
    cleaned = _clean_line(text)
    if not cleaned or _is_noise_line(cleaned) or _looks_like_plain_question(cleaned, {}, []):
        return False
    collapsed = re.sub(r"\s+", "", cleaned.lower())
    if any(t in collapsed for t in TASK_REQUEST_HINTS):
        return True
    title = _strip_metadata(cleaned)
    if extract_due_phrase(cleaned) or extract_estimated_minutes(cleaned):
        return bool(title)
    if re.search(r"https?://", cleaned):
        return False
    return 2 <= len(title) <= 40


def _looks_like_question(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if "?" in cleaned or "？" in cleaned:
        return True
    question_tokens = ["什么时候", "何时", "几点", "多少", "有哪些", "还有哪些", "什么", "哪个", "哪项", "附件", "截止", "作业", "任务", "能不能", "可不可以"]
    return any(t in cleaned for t in question_tokens)


def _looks_like_plain_question(text: str, thread_context: dict[str, Any] | None = None, open_tasks: list[dict[str, Any]] | None = None) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned or not _looks_like_question(cleaned):
        return False
    collapsed = re.sub(r"\s+", "", cleaned.lower())
    no_create_tokens = {"不用创建任务", "别创建任务", "不要创建任务", "只需要回答", "只要回答", "只回答", "不用记任务", "不是任务"}
    if any(t in collapsed for t in no_create_tokens):
        return True
    if any(t in collapsed for t in TASK_REQUEST_HINTS):
        return False
    if re.search(r"(能不能|可不可以|麻烦|请).*(提醒|记得|安排|创建|新建|新增)", cleaned):
        return False
    return True


def _answer_with_rules(request_text: str, thread_context: dict[str, Any], open_tasks: list[dict[str, Any]]) -> list[str]:
    text = str(request_text or "").strip()
    answers: list[str] = []
    context_items = _thread_context_items(thread_context)
    target_item = _match_context_item(text, context_items)

    if any(t in text for t in ["哪些任务", "我的任务", "还有什么任务"]) and open_tasks:
        titles = "、".join(f"{item.get('task_id', '')} {item.get('title', '')}".strip() for item in open_tasks[:6])
        answers.append(f"你当前未完成的任务有：{titles}。")
        return answers

    if target_item and any(t in text for t in ["什么时候", "何时", "截止", "到期"]):
        deadline = str(target_item.get("ai_result", {}).get("deadline", "")).strip() or "当前没有识别到明确截止时间。"
        answers.append(f"《{target_item.get('title', '')}》的截止信息是：{deadline}。")
        return answers

    if target_item and "附件" in text:
        attachments = target_item.get("metadata", {}).get("ucloud_attachments", [])
        if isinstance(attachments, list) and attachments:
            names = "、".join(str(item.get("filename", "")).strip() for item in attachments if isinstance(item, dict) and str(item.get("filename", "")).strip())
            if names:
                answers.append(f"《{target_item.get('title', '')}》当前附件是：{names}。")
                return answers
        answers.append(f"《{target_item.get('title', '')}》当前没有识别到附件。")
        return answers

    return answers[:3]


def _thread_context_items(thread_context: dict[str, Any]) -> list[dict[str, Any]]:
    notices = thread_context.get("notices", [])
    return [item for item in notices if isinstance(item, dict)]


def _match_context_item(request_text: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    quoted = re.search(r"[“\"'《](.+?)[”\"'》]", request_text)
    requested = quoted.group(1).strip() if quoted else ""
    normalized_request = _normalize_lookup_text(requested or request_text)
    if not normalized_request:
        return items[0] if len(items) == 1 else None
    for item in items:
        title = str(item.get("title", "")).strip()
        normalized_title = _normalize_lookup_text(title)
        if not normalized_title:
            continue
        if requested and requested in title:
            return item
        if normalized_request == normalized_title or normalized_request in normalized_title or normalized_title in normalized_request:
            return item
    return items[0] if len(items) == 1 else None


def _normalize_lookup_text(text: str) -> str:
    cleaned = str(text or "").strip().lower()
    cleaned = re.sub(r"^(re|fw|fwd)\s*:\s*", "", cleaned)
    cleaned = re.sub(r"[\[\]（）()《》“”\"'：:,，。.!！?？\-_\s]+", "", cleaned)
    cleaned = cleaned.replace("作业", "").replace("任务", "").replace("邮件", "")
    return cleaned


def _build_create_action(text: str, reference: datetime) -> dict[str, Any] | None:
    cleaned = _clean_line(text)
    if not cleaned or _is_noise_line(cleaned) or _looks_like_plain_question(cleaned, {}, []):
        return None
    collapsed = re.sub(r"\s+", "", cleaned.lower())
    no_create_tokens = {"不用创建任务", "别创建任务", "不要创建任务", "只需要回答", "只要回答", "只回答", "不用记任务", "不是任务"}
    if any(t in collapsed for t in no_create_tokens):
        return None
    due_text = extract_due_phrase(cleaned)
    estimated = extract_estimated_minutes(cleaned)
    title = _strip_metadata(cleaned)
    if not title:
        return None
    return {
        "action_type": "create_task", "target_task_id": "", "target_title": "",
        "title": title, "due_at": TaskStore.normalize_due_value("", due_text, reference),
        "deadline_text": due_text, "estimated_minutes": estimated,
        "disable_reminder": None, "reason": "规则识别为创建任务。",
    }


def _normalize_actions(raw_actions: Any, reference: datetime) -> list[dict[str, Any]]:
    if not isinstance(raw_actions, list):
        return []
    actions: list[dict[str, Any]] = []
    for item in raw_actions:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("action_type", "")).strip().lower()
        if action_type not in ALLOWED_ACTION_TYPES:
            continue
        due_at = TaskStore.normalize_due_value(item.get("due_at", ""), deadline_text=item.get("deadline_text", ""), reference=reference)
        actions.append({
            "action_type": action_type,
            "target_task_id": extract_task_id(item.get("target_task_id", "")),
            "target_title": str(item.get("target_title", "")).strip(),
            "title": str(item.get("title", "")).strip(),
            "due_at": due_at,
            "deadline_text": str(item.get("deadline_text", "")).strip(),
            "estimated_minutes": extract_estimated_minutes(item.get("estimated_minutes", "")),
            "disable_reminder": normalize_optional_bool(item.get("disable_reminder")),
            "reason": str(item.get("reason", "")).strip(),
        })
    return actions


def extract_due_phrase(text: Any) -> str:
    cleaned = str(text or "").strip()
    delay_match = re.search(r"(半小时后|等会[儿]?|待会[儿]?|一会[儿]?|过会[儿]?|稍后|晚点|回头|\d+(?:个)?(?:分钟|分|小时|时|天)后|[零一二两三四五六七八九十百半]+(?:个)?(?:分钟|分|小时|时|天)后)", cleaned)
    if delay_match:
        return delay_match.group(1)
    patterns = [
        r"((?:今天|今日|今晚|今早|今晨|明天|明日|明晚|明早|明晨|后天|周末|这周末|本周末|下周末|(?:(?:本周|这周|下周)?周[一二三四五六日天]))(?:凌晨|早上|上午|中午|下午|傍晚|晚上)?(?:\d{1,2}(?:[点时:]\d{1,2})?|[零一二两三四五六七八九十]{1,3}点(?:[零一二三四五六七八九十]{1,3}分?)?)?)",
        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?(?:\s*\d{1,2}(?:[点时:]\d{1,2})?)?)",
        r"(\d{1,2}[-/月]\d{1,2}日?(?:\s*\d{1,2}(?:[点时:]\d{1,2})?)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return match.group(1)
    return ""


def extract_estimated_minutes(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value or "").strip().lower()
    if not text:
        return None
    if "半小时" in text:
        return 30
    hour_match = re.search(r"(\d+)\s*(?:小时|h|hr|hrs|hour)", text)
    if hour_match:
        return int(hour_match.group(1)) * 60
    minute_match = re.search(r"(?:预计|耗时|用时)?\s*(\d+)\s*(?:分钟|min|mins|minute|minutes)", text)
    if minute_match:
        minutes = int(minute_match.group(1))
        return minutes if minutes > 0 else None
    return None


def _extract_target_title(text: str, task_id: str) -> str:
    cleaned = str(text or "").strip()
    if task_id:
        cleaned = cleaned.replace(task_id, "")
    quoted = re.search(r"[“\"'《](.+?)[”\"'》]", cleaned)
    if quoted:
        return quoted.group(1).strip()
    cleaned = re.sub(r"(完成|取消|更新|修改|改到|延期|顺延|任务)", "", cleaned)
    return cleaned.strip(" ，。！？“”\"'《》")


def _extract_new_title(text: str) -> str:
    quoted = re.search(r"(?:标题改成|改成|改为|更新为)[“\"'《](.+?)[”\"'》]", text)
    if quoted:
        return quoted.group(1).strip()
    return ""


def _strip_metadata(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"(截止|截至)?\s*(今天|今日|今晚|今早|今晨|明天|明日|明晚|明早|明晨|后天|周末|这周末|本周末|下周末|(?:(?:本周|这周|下周)?周[一二三四五六日天]))(?:凌晨|早上|上午|中午|下午|傍晚|晚上)?(?:\d{1,2}(?:[点时:]\d{1,2})?|[零一二两三四五六七八九十]{1,3}点(?:[零一二三四五六七八九十]{1,3}分?)?)?", "", cleaned)
    cleaned = re.sub(r"(半小时后|等会[儿]?|待会[儿]?|一会[儿]?|过会[儿]?|稍后|晚点|回头|\d+(?:个)?(?:分钟|分|小时|时|天)后|[零一二两三四五六七八九十百半]+(?:个)?(?:分钟|分|小时|时|天)后)", "", cleaned)
    cleaned = re.sub(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?(?:\s*\d{1,2}(?:[点时:]\d{1,2})?)?", "", cleaned)
    cleaned = re.sub(r"\d{1,2}[-/月]\d{1,2}日?(?:\s*\d{1,2}(?:[点时:]\d{1,2})?)?", "", cleaned)
    cleaned = re.sub(r"(预计|耗时|用时)?\s*\d+\s*(?:分钟|min|mins|minute|minutes|小时|h|hr|hrs|hour)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:请|麻烦|帮我|帮忙|可以|能不能|可不可以)?\s*(?:创建|新建|新增|帮我记一个|帮我记下|记一个|记下|记得|提醒我|提醒一个|提醒|安排一个|安排|计划提醒|待办|todo|todolist|任务)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(创建|新建|新增|帮我记一个|帮我记下|记一个|记下|记得|提醒我|提醒一个|提醒|待办|todo|todolist|任务)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(可以吗|好吗|行吗|谢谢啦|谢谢|麻烦了)[，,。.！!？?]?$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" ，。！？“”\"'《》")
