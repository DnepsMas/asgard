from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)
LEGACY_KEY_MAP = {
    "apikey": "OPENAI_API_KEY",
    "baseurl": "OPENAI_BASE_URL",
    "model": "AI_MODEL",
    "bupt_user": "MY_BUPT_USERNAME",
    "user_password": "MY_BUPT_PASSWORD",
}


class Config:
    """Typed wrapper around the raw config dict."""

    def __init__(self, raw: dict[str, Any], base_dir: Path) -> None:
        self._raw = raw
        self._base_dir = base_dir

    @classmethod
    def load(cls, config_path: str | Path = "config.yaml") -> Config:
        base_dir = Path(config_path).resolve().parent
        _seed_environment(base_dir)

        path = Path(config_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")

        with path.open("r", encoding="utf-8") as file:
            raw_config = yaml.safe_load(file) or {}

        substituted = _substitute_env_vars(raw_config)
        config = _merge_dicts(_default_config(), substituted)
        config = _normalize_config(config, base_dir)
        return cls(config, base_dir)

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    # --- Section accessors ---

    @property
    def assistant(self) -> dict[str, Any]:
        return self._raw.get("assistant", {})

    @property
    def llm(self) -> dict[str, Any]:
        return self._raw.get("llm", {})

    @property
    def auth(self) -> dict[str, Any]:
        return self._raw.get("auth", {})

    @property
    def cookies(self) -> dict[str, Any]:
        return self._raw.get("cookies", {})

    @property
    def runtime(self) -> dict[str, Any]:
        return self._raw.get("runtime", {})

    @property
    def storage(self) -> dict[str, Any]:
        return self._raw.get("storage", {})

    @property
    def portals(self) -> list[dict[str, Any]]:
        return self._raw.get("portals", [])

    @property
    def ucloud(self) -> dict[str, Any]:
        return self._raw.get("ucloud", {})

    @property
    def tasks(self) -> dict[str, Any]:
        return self._raw.get("tasks", {})

    @property
    def schedule(self) -> dict[str, Any]:
        return self._raw.get("schedule", {})

    @property
    def scheduler(self) -> dict[str, Any]:
        return self._raw.get("scheduler", {})

    @property
    def output(self) -> dict[str, Any]:
        return self._raw.get("output", {})

    @property
    def email(self) -> dict[str, Any]:
        return self._raw.get("email", {})

    @property
    def inbound_email(self) -> dict[str, Any]:
        return self._raw.get("inbound_email", {})

    def request_headers(self) -> dict[str, str]:
        return self._raw.get("request_headers", {})


def _seed_environment(base_dir: Path) -> None:
    dotenv_values = _read_key_value_file(base_dir / ".env")
    for key, value in dotenv_values.items():
        os.environ.setdefault(key, value)

    legacy_values = _read_key_value_file(base_dir / "config")
    for legacy_key, env_key in LEGACY_KEY_MAP.items():
        value = legacy_values.get(legacy_key, "")
        if value:
            os.environ.setdefault(env_key, value)

    if legacy_values.get("openai") == "":
        os.environ.setdefault("AI_PROVIDER", "openai_compatible")

    if os.getenv("MODEL_NAME"):
        os.environ["AI_MODEL"] = os.environ["MODEL_NAME"]
    if os.getenv("OPENAI_MODEL"):
        os.environ["AI_MODEL"] = os.environ["OPENAI_MODEL"]


def _read_key_value_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    try:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key:
                result[key] = value
    except OSError:
        pass
    return result


def _substitute_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        def _replace(match: re.Match[str]) -> str:
            env_key = match.group(1)
            return os.environ.get(env_key, "")
        return ENV_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


def _default_config() -> dict[str, Any]:
    return {
        "assistant": {"name": "阿斯加德", "user_profile": "", "extra_instruction": ""},
        "auth": {"enabled": False, "type": "cas"},
        "runtime": {
            "request_timeout": 15,
            "request_retries": 2,
            "retry_backoff_seconds": 1.0,
            "polling_interval": 1800,
            "page_delay_seconds": 0.2,
            "max_items_per_portal": 30,
            "max_detail_chars": 5000,
            "trust_env_proxy": False,
            "user_agent": DEFAULT_USER_AGENT,
        },
        "portals": [],
        "storage": {"path": "storage.json"},
        "output": {
            "report_path": "output/notices.md",
            "json_report_path": "output/notices.json",
            "heartbeat_report_path": "output/heartbeat.md",
            "heartbeat_json_report_path": "output/heartbeat.json",
            "morning_digest_report_path": "output/morning_digest.md",
            "morning_digest_json_report_path": "output/morning_digest.json",
            "evening_digest_report_path": "output/evening_digest.md",
            "evening_digest_json_report_path": "output/evening_digest.json",
            "task_receipt_report_path": "output/task_receipt.md",
            "task_receipt_json_report_path": "output/task_receipt.json",
            "log_path": "output/asgard.log",
        },
        "scheduler": {
            "enabled": True,
            "heartbeat_interval_hours": 2,
            "active_start": "08:00",
            "active_end": "22:00",
            "morning_digest_time": "08:00",
        },
        "tasks": {"path": "tasks.json"},
        "email": {"enabled": False},
        "inbound_email": {"enabled": False, "state_path": "mailbox_state.json"},
    }


def _normalize_config(config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    _ensure_int_fields(config, ["runtime"], ["request_timeout", "request_retries", "polling_interval"])
    _relativize_paths(config, base_dir, ["storage"], ["path"])
    _relativize_paths(config, base_dir, ["output"], [
        "log_path", "report_path", "json_report_path",
        "heartbeat_report_path", "heartbeat_json_report_path",
        "morning_digest_report_path", "morning_digest_json_report_path",
        "evening_digest_report_path", "evening_digest_json_report_path",
        "task_receipt_report_path", "task_receipt_json_report_path",
    ])
    _relativize_paths(config, base_dir, ["tasks"], ["path"])
    _relativize_paths(config, base_dir, ["inbound_email"], ["state_path"])

    if "request_headers" not in config:
        config["request_headers"] = {}
    if "backup_api_key" not in config.get("llm", {}):
        config.setdefault("llm", {})["backup_api_key"] = ""
    if "backup_base_url" not in config.get("llm", {}):
        config.setdefault("llm", {})["backup_base_url"] = ""

    auth_providers = _detect_auth_providers(config)
    for provider in auth_providers:
        _normalize_portal_auth(config, provider, base_dir)

    return config


def _detect_auth_providers(config: dict[str, Any]) -> set[str]:
    providers: set[str] = set()
    for portal in config.get("portals", []):
        url = str(portal.get("url", ""))
        source = str(portal.get("source", ""))
        if "my.bupt.edu.cn" in url or "北邮" in source:
            providers.add("bupt")
        if "ucloud" in url.lower() or "ucloud.bupt" in url:
            providers.add("bupt")
    return providers


def _normalize_portal_auth(config: dict[str, Any], provider: str, base_dir: Path) -> None:
    if provider != "bupt":
        return
    auth = config.get("auth", {})
    if not auth.get("login_url"):
        auth["login_url"] = "https://auth.bupt.edu.cn/authserver/login"


def _relativize_paths(config: dict[str, Any], base_dir: Path, keys: list[str], fields: list[str]) -> None:
    section = config
    for key in keys:
        section = section.get(key, {})
    for field in fields:
        value = section.get(field, "")
        if isinstance(value, str) and value and not Path(value).is_absolute():
            section[field] = str((base_dir / value).resolve())


def _ensure_int_fields(config: dict[str, Any], keys: list[str], fields: list[str]) -> None:
    for key in keys:
        section = config.get(key, {})
        for field in fields:
            value = section.get(field)
            if value is not None:
                section[field] = int(value)


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
