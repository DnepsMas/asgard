from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from ._helpers import (
    ALERTS_ARCHIVE_KEY,
    DEFAULT_NOTIFICATION_STATE,
    DIGEST_ARCHIVE_KEY,
    STORAGE_VERSION,
    normalize_bucket,
    normalize_deadline,
    parse_iso_datetime,
    parse_published_date,
)


logger = logging.getLogger(__name__)


class NoticeStorage:
    def __init__(self, path: str | Path, digest_portals: list[str] | set[str] | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = digest_portals or {"校园新闻"}
        self.digest_portals = {str(p).strip() for p in raw if str(p).strip()}
        if not self.digest_portals:
            self.digest_portals = {"校园新闻"}
        self.records = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_storage()
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("读取存储文件失败，将以内存空状态继续: %s", exc)
            return self._empty_storage()

        if isinstance(data, list):
            return self._migrate_legacy_list(data)
        if not isinstance(data, dict):
            return self._empty_storage()
        if ALERTS_ARCHIVE_KEY in data or DIGEST_ARCHIVE_KEY in data:
            return self._normalize_v3_storage(data)
        if "archive" in data:
            return self._migrate_v2_archive(data.get("archive", {}))
        if "sent" in data:
            return self._migrate_legacy_sent(data.get("sent", {}))
        return self._empty_storage()

    @staticmethod
    def _empty_storage() -> dict[str, Any]:
        return {"version": STORAGE_VERSION, ALERTS_ARCHIVE_KEY: {}, DIGEST_ARCHIVE_KEY: {}}

    def _migrate_legacy_list(self, data: list[Any]) -> dict[str, Any]:
        migrated = self._empty_storage()
        now = datetime.now().isoformat(timespec="seconds")
        for item in data:
            if not isinstance(item, dict):
                continue
            notice_id = self.build_notice_id(item.get("url", ""), item.get("title", ""))
            record = self._normalize_archive_record(notice_id, {
                "notice_id": notice_id, "title": item.get("title", ""), "url": item.get("url", ""),
                "source": item.get("source", ""), "published_at": item.get("published_at", ""),
                "portal_name": item.get("portal_name", ""), "list_summary": item.get("list_summary", ""),
                "ai_result": item.get("ai_result", {}), "first_seen_at": now, "archived_at": now,
                "last_seen_at": now, "notification": {
                    "immediate_email_sent_at": item.get("sent_at", now),
                    "immediate_email_attempted_at": "", "morning_digest_sent_date": "",
                    "last_deadline_reminder_date": "",
                },
            })
            self._store_record(migrated, record)
        return migrated

    def _migrate_legacy_sent(self, sent_data: Any) -> dict[str, Any]:
        migrated = self._empty_storage()
        now = datetime.now().isoformat(timespec="seconds")
        if not isinstance(sent_data, dict):
            return migrated
        for notice_id, item in sent_data.items():
            if not isinstance(item, dict):
                continue
            sent_at = str(item.get("sent_at", "")).strip() or now
            record = self._normalize_archive_record(notice_id, {
                "notice_id": notice_id, "title": item.get("title", ""), "url": item.get("url", ""),
                "source": item.get("source", ""), "published_at": item.get("published_at", ""),
                "portal_name": item.get("portal_name", ""), "list_summary": item.get("list_summary", ""),
                "ai_result": item.get("ai_result", {}), "first_seen_at": sent_at, "archived_at": sent_at,
                "last_seen_at": sent_at, "notification": {
                    "immediate_email_sent_at": sent_at, "immediate_email_attempted_at": "",
                    "morning_digest_sent_date": "", "last_deadline_reminder_date": "",
                },
            })
            self._store_record(migrated, record)
        return migrated

    def _migrate_v2_archive(self, archive: Any) -> dict[str, Any]:
        migrated = self._empty_storage()
        if not isinstance(archive, dict):
            return migrated
        for notice_id, record in archive.items():
            normalized_record = self._normalize_archive_record(notice_id, record)
            self._store_record(migrated, normalized_record)
        return migrated

    def _normalize_v3_storage(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = self._empty_storage()
        for archive_key in (ALERTS_ARCHIVE_KEY, DIGEST_ARCHIVE_KEY):
            archive = data.get(archive_key, {})
            if not isinstance(archive, dict):
                continue
            for notice_id, record in archive.items():
                normalized_record = self._normalize_archive_record(notice_id, record)
                self._store_record(normalized, normalized_record)
        return normalized

    def _normalize_archive_record(self, notice_id: str, record: Any) -> dict[str, Any]:
        if not isinstance(record, dict):
            record = {}
        notification = record.get("notification", {})
        if not isinstance(notification, dict):
            notification = {}
        ai_result = record.get("ai_result", {})
        if not isinstance(ai_result, dict):
            ai_result = {}
        metadata = record.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        archived_at = str(record.get("archived_at", "")).strip()
        first_seen_at = str(record.get("first_seen_at", "")).strip() or archived_at
        last_seen_at = str(record.get("last_seen_at", "")).strip() or first_seen_at or archived_at
        deadline_text = str(ai_result.get("deadline", "")).strip()
        deadline_at = str(record.get("deadline_at", "")).strip()
        if deadline_text and not deadline_at:
            deadline_at = normalize_deadline(deadline_text, record.get("published_at", ""))

        return {
            "notice_id": notice_id, "title": str(record.get("title", "")).strip(),
            "url": str(record.get("url", "")).strip(), "source": str(record.get("source", "")).strip(),
            "published_at": str(record.get("published_at", "")).strip(),
            "portal_name": str(record.get("portal_name", "")).strip(),
            "list_summary": str(record.get("list_summary", "")).strip(), "ai_result": ai_result,
            "metadata": metadata, "first_seen_at": first_seen_at,
            "archived_at": archived_at or first_seen_at,
            "last_seen_at": last_seen_at or first_seen_at or archived_at, "deadline_at": deadline_at,
            "notification": {
                "immediate_email_sent_at": str(notification.get("immediate_email_sent_at", "")).strip(),
                "immediate_email_attempted_at": str(notification.get("immediate_email_attempted_at", "")).strip(),
                "morning_digest_sent_date": str(notification.get("morning_digest_sent_date", "")).strip(),
                "evening_digest_sent_date": str(notification.get("evening_digest_sent_date", "")).strip(),
                "last_deadline_reminder_date": str(notification.get("last_deadline_reminder_date", "")).strip(),
            },
        }

    @staticmethod
    def build_notice_id(url: str, title: str) -> str:
        normalized_url = " ".join((url or "").split()).strip().lower()
        normalized_title = " ".join((title or "").split()).strip()
        return hashlib.sha256(f"{normalized_url}\n{normalized_title}".encode("utf-8")).hexdigest()

    def has_notice(self, notice_id: str) -> bool:
        record, _ = self._find_record_entry(notice_id)
        return record is not None

    def is_sent(self, notice_id: str) -> bool:
        record, _ = self._find_record_entry(notice_id)
        if not record:
            return False
        notification = record.get("notification", {})
        return bool(notification.get("immediate_email_sent_at")) or bool(notification.get("morning_digest_sent_date"))

    def archive_notices(self, notices: list[dict[str, Any]]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        for notice in notices:
            notice_id = str(notice.get("notice_id", "")).strip()
            if not notice_id:
                continue
            existing, _ = self._find_record_entry(notice_id)
            ai_result = notice.get("ai_result", {})
            if not isinstance(ai_result, dict):
                ai_result = {}
            notification = (existing or {}).get("notification", {}).copy()
            if not notification:
                notification = DEFAULT_NOTIFICATION_STATE.copy()
            archived_at = (existing or {}).get("archived_at", "") or now
            first_seen_at = (existing or {}).get("first_seen_at", "") or now
            published_at = str(notice.get("published_at", "")).strip()
            deadline_at = normalize_deadline(str(ai_result.get("deadline", "")).strip(), published_at)
            record = self._normalize_archive_record(notice_id, {
                "notice_id": notice_id, "title": notice.get("title", ""), "url": notice.get("url", ""),
                "source": notice.get("source", ""), "published_at": published_at,
                "portal_name": notice.get("portal_name", ""), "list_summary": notice.get("list_summary", ""),
                "ai_result": ai_result, "metadata": notice.get("metadata", {}),
                "first_seen_at": first_seen_at, "archived_at": archived_at, "last_seen_at": now,
                "deadline_at": deadline_at, "notification": notification,
            })
            self._remove_from_archives(notice_id)
            self._store_record(self.records, record)

    def get_records_by_ids(self, notice_ids: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for notice_id in notice_ids:
            record, _ = self._find_record_entry(notice_id)
            if record:
                results.append(self._record_to_notice(record))
        return results

    def mark_source_records_active(self, source_kind: str, active_notice_ids: set[str]) -> bool:
        changed = False
        active_ids = {str(item).strip() for item in active_notice_ids if str(item).strip()}
        for record in self._iter_records():
            metadata = record.get("metadata", {})
            if metadata.get("source_kind") != source_kind:
                continue
            should_be_active = record.get("notice_id", "") in active_ids
            if bool(metadata.get("is_active", True)) != should_be_active:
                metadata["is_active"] = should_be_active
                changed = True
        return changed

    def list_immediate_candidates_by_ids(self, notice_ids: list[str], levels: list[str], exclude_portals: list[str] | None = None) -> list[dict[str, Any]]:
        normalized_levels = {level.strip().lower() for level in levels if level}
        excluded = {p.strip() for p in (exclude_portals or []) if p}
        candidates: list[dict[str, Any]] = []
        for notice_id in notice_ids:
            record = self.records[ALERTS_ARCHIVE_KEY].get(notice_id)
            if not record or not self._matches_immediate_filters(record, normalized_levels, excluded):
                continue
            candidates.append(self._record_to_notice(record))
        candidates.sort(key=lambda item: item.get("published_at", ""), reverse=True)
        return candidates

    def list_pending_immediate(self, levels: list[str]) -> list[dict[str, Any]]:
        return self.list_pending_immediate_filtered(levels, exclude_portals=[])

    def list_pending_immediate_filtered(self, levels: list[str], exclude_portals: list[str] | None = None) -> list[dict[str, Any]]:
        normalized_levels = {level.strip().lower() for level in levels if level}
        excluded = {p.strip() for p in (exclude_portals or []) if p}
        pending: list[dict[str, Any]] = []
        for record in self._iter_records(bucket="alerts"):
            if not self._matches_immediate_filters(record, normalized_levels, excluded):
                continue
            pending.append(self._record_to_notice(record))
        pending.sort(key=lambda item: item.get("published_at", ""), reverse=True)
        return pending

    def list_retry_immediate_filtered(self, levels: list[str], exclude_portals: list[str] | None = None) -> list[dict[str, Any]]:
        normalized_levels = {level.strip().lower() for level in levels if level}
        excluded = {p.strip() for p in (exclude_portals or []) if p}
        retries: list[dict[str, Any]] = []
        for record in self._iter_records(bucket="alerts"):
            if not self._matches_immediate_filters(record, normalized_levels, excluded):
                continue
            if record.get("notification", {}).get("immediate_email_attempted_at"):
                retries.append(self._record_to_notice(record))
        retries.sort(key=lambda item: item.get("published_at", ""), reverse=True)
        return retries

    def list_due_deadline_reminders(self, levels: list[str], horizon_days: int, exclude_notice_ids: set[str] | None = None, today: date | None = None, current_time: datetime | None = None) -> list[dict[str, Any]]:
        now_dt = current_time or datetime.now()
        now_date = today or now_dt.date()
        upper_bound = now_date + timedelta(days=max(horizon_days, 0))
        upper_bound_dt = datetime.combine(upper_bound, time.max)
        normalized_levels = {level.strip().lower() for level in levels if level}
        exclude_ids = exclude_notice_ids or set()
        reminders: list[dict[str, Any]] = []
        for record in self._iter_records(bucket="alerts"):
            if record["notice_id"] in exclude_ids:
                continue
            importance = str(record.get("ai_result", {}).get("importance", "")).strip().lower()
            if importance not in normalized_levels:
                continue
            if not self._record_is_active(record):
                continue
            deadline_at = parse_iso_datetime(record.get("deadline_at", ""))
            if deadline_at is None or deadline_at < now_dt or deadline_at > upper_bound_dt:
                continue
            if record.get("notification", {}).get("last_deadline_reminder_date") == now_date.isoformat():
                continue
            reminders.append(self._record_to_notice(record))
        reminders.sort(key=lambda item: item.get("deadline_at", ""))
        return reminders

    def list_digest_records_for_day(self, report_date: date, levels: list[str], digest_date: date, include_portals: list[str] | None = None, exclude_portals: list[str] | None = None, bucket: str | None = None) -> list[dict[str, Any]]:
        normalized_levels = {level.strip().lower() for level in levels if level}
        included = {p.strip() for p in (include_portals or []) if p}
        excluded = {p.strip() for p in (exclude_portals or []) if p}
        digest_date_text = digest_date.isoformat()
        records: list[dict[str, Any]] = []
        for record in self._iter_records(bucket=bucket):
            ai_result = record.get("ai_result", {})
            importance = str(ai_result.get("importance", "")).strip().lower()
            if importance not in normalized_levels:
                continue
            if not self._record_is_active(record):
                continue
            portal_name = record.get("portal_name", "")
            if included and portal_name not in included:
                continue
            if excluded and portal_name in excluded:
                continue
            published_date = parse_published_date(record.get("published_at", ""))
            if published_date != report_date:
                continue
            if record.get("notification", {}).get("morning_digest_sent_date") == digest_date_text:
                continue
            records.append(self._record_to_notice(record))
        records.sort(key=lambda item: (item.get("published_at", ""), item.get("title", "")), reverse=True)
        return records

    def list_active_source_records(self, levels: list[str], source_kind: str, sent_date_field: str = "", today: date | None = None, bucket: str | None = None) -> list[dict[str, Any]]:
        normalized_levels = {level.strip().lower() for level in levels if level}
        today_text = (today or datetime.now().date()).isoformat()
        records: list[dict[str, Any]] = []
        for record in self._iter_records(bucket=bucket):
            importance = str(record.get("ai_result", {}).get("importance", "")).strip().lower()
            if normalized_levels and importance not in normalized_levels:
                continue
            if record.get("metadata", {}).get("source_kind") != source_kind:
                continue
            if not self._record_is_active(record):
                continue
            if sent_date_field and record.get("notification", {}).get(sent_date_field) == today_text:
                continue
            records.append(self._record_to_notice(record))
        records.sort(key=lambda item: self._active_source_sort_key(item))
        return records

    def _mark_notification_field(self, notice_ids: list[str], field: str, value: str) -> None:
        for notice_id in notice_ids:
            record, _ = self._find_record_entry(notice_id)
            if record:
                record["notification"][field] = value

    def mark_immediate_sent(self, notice_ids: list[str], sent_at: datetime | None = None) -> None:
        timestamp = (sent_at or datetime.now()).isoformat(timespec="seconds")
        for notice_id in notice_ids:
            record, _ = self._find_record_entry(notice_id)
            if not record:
                continue
            record["notification"]["immediate_email_sent_at"] = timestamp
            record["notification"]["immediate_email_attempted_at"] = ""

    def mark_immediate_attempted(self, notice_ids: list[str], attempted_at: datetime | None = None) -> None:
        timestamp = (attempted_at or datetime.now()).isoformat(timespec="seconds")
        self._mark_notification_field(notice_ids, "immediate_email_attempted_at", timestamp)

    def mark_morning_digest_sent(self, notice_ids: list[str], sent_date: date | None = None) -> None:
        digest_date = (sent_date or datetime.now().date()).isoformat()
        self._mark_notification_field(notice_ids, "morning_digest_sent_date", digest_date)

    def mark_evening_digest_sent(self, notice_ids: list[str], sent_date: date | None = None) -> None:
        digest_date = (sent_date or datetime.now().date()).isoformat()
        self._mark_notification_field(notice_ids, "evening_digest_sent_date", digest_date)

    def mark_deadline_reminded(self, notice_ids: list[str], sent_date: date | None = None) -> None:
        reminder_date = (sent_date or datetime.now().date()).isoformat()
        self._mark_notification_field(notice_ids, "last_deadline_reminder_date", reminder_date)

    def save(self) -> None:
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(self.records, file, ensure_ascii=False, indent=2)
        temp_path.replace(self.path)

    @staticmethod
    def _record_to_notice(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "notice_id": record.get("notice_id", ""), "title": record.get("title", ""),
            "url": record.get("url", ""), "source": record.get("source", ""),
            "published_at": record.get("published_at", ""), "portal_name": record.get("portal_name", ""),
            "list_summary": record.get("list_summary", ""), "ai_result": record.get("ai_result", {}),
            "metadata": record.get("metadata", {}), "deadline_at": record.get("deadline_at", ""),
            "notification": record.get("notification", {}),
        }

    def _find_record_entry(self, notice_id: str) -> tuple[dict[str, Any] | None, str | None]:
        for archive_key in (ALERTS_ARCHIVE_KEY, DIGEST_ARCHIVE_KEY):
            record = self.records[archive_key].get(notice_id)
            if record:
                return record, archive_key
        return None, None

    def _remove_from_archives(self, notice_id: str) -> None:
        for archive_key in (ALERTS_ARCHIVE_KEY, DIGEST_ARCHIVE_KEY):
            self.records[archive_key].pop(notice_id, None)

    def _store_record(self, container: dict[str, Any], record: dict[str, Any]) -> None:
        bucket_key = self._bucket_for_portal(record.get("portal_name", ""))
        container[bucket_key][record["notice_id"]] = record

    def _bucket_for_portal(self, portal_name: str) -> str:
        normalized = str(portal_name).strip()
        return DIGEST_ARCHIVE_KEY if normalized in self.digest_portals else ALERTS_ARCHIVE_KEY

    def _iter_records(self, bucket: str | None = None) -> list[dict[str, Any]]:
        bucket_key = normalize_bucket(bucket)
        if bucket_key is not None:
            return list(self.records[bucket_key].values())
        records: list[dict[str, Any]] = []
        for archive_key in (ALERTS_ARCHIVE_KEY, DIGEST_ARCHIVE_KEY):
            records.extend(self.records[archive_key].values())
        return records

    @staticmethod
    def _matches_immediate_filters(record: dict[str, Any], normalized_levels: set[str], excluded_portals: set[str]) -> bool:
        importance = str(record.get("ai_result", {}).get("importance", "")).strip().lower()
        notification = record.get("notification", {})
        if importance not in normalized_levels or record.get("portal_name", "") in excluded_portals:
            return False
        if not NoticeStorage._record_is_active(record):
            return False
        return not notification.get("immediate_email_sent_at") and not notification.get("morning_digest_sent_date")

    @staticmethod
    def _record_is_active(record: dict[str, Any]) -> bool:
        metadata = record.get("metadata", {})
        if not isinstance(metadata, dict):
            return True
        return metadata.get("is_active", True) is not False

    @staticmethod
    def _active_source_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        deadline_at = parse_iso_datetime(item.get("deadline_at", ""))
        return (deadline_at or datetime.max, item.get("source", ""), item.get("title", ""))
