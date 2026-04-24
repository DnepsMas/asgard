from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


@dataclass(frozen=True)
class OpenAITarget:
    name: str
    api_key: str
    base_url: str


class OpenAIChatGateway:
    def __init__(
        self,
        llm_config: dict[str, Any],
        *,
        logger: logging.Logger | None = None,
        client_label: str = "OpenAI",
    ) -> None:
        self.llm_config = llm_config
        self.logger = logger or logging.getLogger(__name__)
        self.client_label = client_label
        self._clients: dict[str, Any] = {}
        self.targets = self._build_targets(llm_config)

    @property
    def available(self) -> bool:
        return OpenAI is not None and bool(self.targets)

    def create_chat_completion(self, **kwargs: Any) -> Any:
        if OpenAI is None:
            raise RuntimeError("当前 Python 环境未安装 openai 包。")
        if not self.targets:
            raise RuntimeError("OpenAI 客户端未配置。")

        last_exc: Exception | None = None
        for index, target in enumerate(self.targets):
            client = self._get_client(target)
            try:
                if index > 0:
                    self.logger.warning("%s：正在使用备用 OpenAI 接口。", self.client_label)
                return client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_exc = exc
                if index == 0 and len(self.targets) > 1 and self._should_failover(exc):
                    self.logger.warning(
                        "%s：主 OpenAI 接口请求失败，切换到备用接口。原因: %s",
                        self.client_label,
                        exc,
                    )
                    continue
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("OpenAI 请求失败。")

    def _get_client(self, target: OpenAITarget) -> Any:
        cache_key = f"{target.name}:{target.api_key}:{target.base_url}"
        client = self._clients.get(cache_key)
        if client is not None:
            return client

        kwargs: dict[str, Any] = {
            "api_key": target.api_key,
            "timeout": self.llm_config.get("timeout_seconds", 60),
        }
        if target.base_url:
            kwargs["base_url"] = target.base_url
        client = OpenAI(**kwargs)
        self._clients[cache_key] = client
        return client

    @staticmethod
    def _build_targets(llm_config: dict[str, Any]) -> list[OpenAITarget]:
        primary_key = str(llm_config.get("api_key", "")).strip()
        primary_base = str(llm_config.get("base_url", "")).strip()
        backup_key = str(llm_config.get("backup_api_key", "")).strip()
        backup_base = str(llm_config.get("backup_base_url", "")).strip() or primary_base

        targets: list[OpenAITarget] = []
        if primary_key:
            targets.append(OpenAITarget(name="primary", api_key=primary_key, base_url=primary_base))
        if backup_key:
            targets.append(OpenAITarget(name="backup", api_key=backup_key, base_url=backup_base))
        return targets

    @staticmethod
    def _should_failover(exc: Exception) -> bool:
        class_name = exc.__class__.__name__.lower()
        if any(
            token in class_name
            for token in (
                "timeout",
                "connection",
                "ratelimit",
                "authentication",
                "internalserver",
                "apierror",
            )
        ):
            return True

        message = str(exc).lower()
        failover_markers = (
            "401", "429", "500", "502", "503", "504",
            "timed out", "timeout",
            "connection aborted", "connection reset", "connection refused",
            "temporary unavailable",
            "invalid api key", "insufficient_quota",
            "rate limit", "server error",
        )
        if any(marker in message for marker in failover_markers):
            return True

        http_code = getattr(exc, "status_code", None)
        if isinstance(http_code, int) and http_code in {401, 429, 500, 502, 503, 504}:
            return True

        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and status_code in {401, 429, 500, 502, 503, 504}:
            return True

        return bool(re.search(r"\b(401|429|500|502|503|504)\b", message))
