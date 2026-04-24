from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ._config import Config
from ._logging import emit_console_summary, setup_logging, show_startup_banner
from .analysis.parser import NoticeAIParser
from .mailbox.agent import TaskAgent
from .mailbox.ingress import MailIngress
from .mailbox.parser import TaskCommandParser
from .notification._models import DeliveryResult, DeliveryPayload
from .notification.mail_notifier import MailNotifier
from .scheduler.engine import Scheduler, next_scheduled_run, resolve_delivery_mode
from .scraping.campus import CampusScraper
from .storage.notices import NoticeStorage
from .storage.tasks import TaskStore


logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    collected_count: int
    analyzed_notices: list[dict[str, Any]]
    new_notice_ids: list[str]
    storage_dirty: bool = False


@dataclass
class TaskMailboxResult:
    processed_count: int = 0
    receipt_sent_count: int = 0
    changed_task_ids: list[str] = field(default_factory=list)


def build_services(
    config: dict[str, Any],
) -> tuple[NoticeStorage, CampusScraper, NoticeAIParser, MailNotifier, TaskStore, TaskCommandParser, MailIngress]:
    storage = NoticeStorage(
        config["storage"]["path"],
        digest_portals=config["scheduler"].get("digest_only_portals", ["校园新闻"]),
    )
    scraper = CampusScraper(config)
    parser = NoticeAIParser(config)
    notifier = MailNotifier(config)
    task_store = TaskStore(config["tasks"]["path"])
    task_parser = TaskCommandParser(config)
    mail_ingress = MailIngress(config)
    return storage, scraper, parser, notifier, task_store, task_parser, mail_ingress


def _try_scrape_ucloud(config: dict[str, Any], existing_notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from .scraping.ucloud import UcloudHomeworkScraper
        ucloud = UcloudHomeworkScraper(config)
        if ucloud.enabled():
            logger.info("开始抓取 UCloud 待完成作业")
            ucloud_notices = ucloud.collect_notices()
            logger.info("UCloud 作业抓取完成，共 %s 条候选作业", len(ucloud_notices))
            return existing_notices + ucloud_notices
    except ImportError:
        logger.debug("UCloud 作业抓取模块不可用，跳过")
    return existing_notices


def _try_build_study_plan(delivery_payload: DeliveryPayload, config: dict[str, Any]) -> DeliveryPayload:
    try:
        from .planner.study import build_morning_study_plan
        plan = build_morning_study_plan(delivery_payload)
        if plan:
            delivery_payload.study_plan = plan
    except ImportError:
        logger.debug("学习计划模块不可用，跳过")
    return delivery_payload


def _try_dispatch(
    config: dict[str, Any],
    delivery_payload: DeliveryPayload,
    preview_only: bool,
) -> DeliveryResult:
    try:
        from .notification.dispatcher import NotificationDispatcher
        dispatcher = NotificationDispatcher(config)
        return dispatcher.dispatch(delivery_payload, preview_only=preview_only)
    except ImportError as exc:
        logger.error("通知分发模块不可用: %s", exc)
        return DeliveryResult(success=False, message="通知分发模块不可用", preview_paths=[])


def process_current_notices(
    storage: NoticeStorage,
    scraper: CampusScraper,
    parser: NoticeAIParser,
    config: dict[str, Any],
    reprocess_all: bool = False,
) -> ProcessingResult:
    logger.info("开始抓取校园网消息")
    try:
        raw_notices = scraper.collect_notices()
    except Exception as exc:
        logger.warning("抓取校园网消息失败: %s", exc)
        raw_notices = []
    raw_notices = _try_scrape_ucloud(config, raw_notices)
    logger.info("抓取完成，共 %s 条候选消息", len(raw_notices))

    from .scraping._models import Notice

    notices_to_analyze: list[Notice] = []
    new_notice_ids: list[str] = []
    ucloud_active_ids: set[str] = set()
    for notice in raw_notices:
        notice.notice_id = storage.build_notice_id(notice.url, notice.title)
        if notice.metadata.get("source_kind") == "ucloud_homework":
            ucloud_active_ids.add(notice.notice_id)
        is_existing = storage.has_notice(notice.notice_id)
        if not is_existing:
            new_notice_ids.append(notice.notice_id)
        should_refresh = notice.metadata.get("source_kind") == "ucloud_homework"
        if reprocess_all or not is_existing or should_refresh:
            notices_to_analyze.append(notice)

    storage_dirty = False
    if ucloud_active_ids:
        storage_dirty = storage.mark_source_records_active("ucloud_homework", ucloud_active_ids)

    if not notices_to_analyze:
        logger.info("本轮没有需要分析的新消息")
        return ProcessingResult(
            collected_count=len(raw_notices),
            analyzed_notices=[],
            new_notice_ids=new_notice_ids,
            storage_dirty=storage_dirty,
        )

    ai_candidates = [n for n in notices_to_analyze if not n.ai_result]
    title_results: dict[str, dict[str, Any]] = {}
    if ai_candidates:
        logger.info("发现 %s 条消息需要分析，开始第一阶段：标题初筛", len(ai_candidates))
        title_results = parser.triage_titles(ai_candidates)

    body_candidates: list[Notice] = []
    for notice in notices_to_analyze:
        if notice.ai_result:
            continue
        result = title_results.get(notice.notice_id)
        if result is None:
            result = parser.analyze_notice(notice)
        notice.ai_result = result
        if result.get("importance") != "ignore":
            body_candidates.append(notice)

    if body_candidates:
        logger.info("标题初筛完成，%s 条消息进入第二阶段：正文精炼", len(body_candidates))
        for notice in body_candidates:
            scraper.enrich_notice_content(notice)
        body_results = parser.refine_notice_bodies(body_candidates, title_results)
        for notice in body_candidates:
            if notice.notice_id in body_results:
                notice.ai_result = body_results[notice.notice_id]

    analyzed = [n.to_dict() for n in notices_to_analyze]
    return ProcessingResult(
        collected_count=len(raw_notices),
        analyzed_notices=analyzed,
        new_notice_ids=new_notice_ids,
        storage_dirty=storage_dirty,
    )


def process_mailbox(
    config: dict[str, Any],
    mail_ingress: MailIngress,
    notifier: MailNotifier,
    task_store: TaskStore,
    preview_only: bool = False,
) -> TaskMailboxResult:
    if not config.get("inbound_email", {}).get("enabled", False) or preview_only:
        return TaskMailboxResult()
    try:
        agent = TaskAgent(config, task_store=task_store, notifier=notifier)
        result = agent.poll_and_process(mail_ingress)
        return TaskMailboxResult(
            processed_count=len(result.executed_actions) if hasattr(result, "executed_actions") else 0,
            receipt_sent_count=1 if result.email_sent else 0,
            changed_task_ids=result.changed_task_ids if hasattr(result, "changed_task_ids") else [],
        )
    except Exception as exc:
        logger.error("处理邮箱任务失败: %s", exc)
        return TaskMailboxResult()


def run_cycle(
    config: dict[str, Any],
    storage: NoticeStorage,
    scraper: CampusScraper,
    parser: NoticeAIParser,
    notifier: MailNotifier,
    mail_ingress: MailIngress | None,
    task_store: TaskStore,
    delivery_mode: str,
    preview_only: bool = False,
    reprocess_all: bool = False,
) -> int:
    mode_labels = {"morning_digest": "早报", "evening_digest": "晚报"}
    mode_label = mode_labels.get(delivery_mode, "heartbeat")
    emit_console_summary(f"{mode_label} | 开始{'检查新消息' if delivery_mode == 'heartbeat' else '汇总'}")

    process_result = process_current_notices(
        storage=storage, scraper=scraper, parser=parser,
        config=config, reprocess_all=reprocess_all,
    )

    if process_result.analyzed_notices:
        storage.archive_notices(process_result.analyzed_notices)
    if process_result.analyzed_notices or process_result.storage_dirty:
        storage.save()

    tasks = task_store.list_open_tasks(reference=datetime.now())
    urgent_tasks = task_store.list_urgent_tasks(window_hours=4)
    open_tasks = task_store.list_open_tasks(reference=datetime.now(), include_overdue=True)

    payload = DeliveryPayload(
        notification_type=delivery_mode,
        notices=process_result.analyzed_notices,
        notice_summaries=storage.get_todays_summaries() if hasattr(storage, "get_todays_summaries") else [],
        deadline_reminders=sorted(
            [n for n in process_result.analyzed_notices if n.get("ai_result", {}).get("deadline")],
            key=lambda x: str(x.get("ai_result", {}).get("deadline", "")),
        ),
        open_tasks=open_tasks,
        urgent_tasks=urgent_tasks,
    )

    if not preview_only:
        mailbox_result = process_mailbox(
            config=config, mail_ingress=mail_ingress,
            notifier=notifier, task_store=task_store,
            preview_only=preview_only,
        )
        if mailbox_result.processed_count:
            logger.info("邮箱任务处理完成: %s 个", mailbox_result.processed_count)

    payload = _try_build_study_plan(payload, config)
    delivery_result = _try_dispatch(config, payload, preview_only)

    if delivery_result.email_sent and delivery_result.outbound_threads and mail_ingress is not None:
        mail_ingress.register_outbound_threads(delivery_result.outbound_threads)

    if delivery_result.success:
        emit_console_summary(f"{mode_label} | 发送成功")
    else:
        logger.warning("发送失败: %s", delivery_result.message)
    return 0 if delivery_result.success else 1


def run_once(
    config_path: str,
    preview_only: bool = False,
    storage_override: str = "",
    reprocess_all: bool = False,
) -> int:
    config = _prepare_config(config_path, storage_override)
    setup_logging(config["output"]["log_path"])
    show_startup_banner()
    storage, scraper, parser, notifier, task_store, task_parser, mail_ingress = build_services(config)
    return run_cycle(
        config=config, storage=storage, scraper=scraper, parser=parser,
        notifier=notifier, mail_ingress=mail_ingress, task_store=task_store,
        delivery_mode="heartbeat", preview_only=preview_only, reprocess_all=reprocess_all,
    )


def run_email_test(
    config_path: str,
    notification_type: str,
    storage_override: str = "",
) -> int:
    config = _prepare_config(config_path, storage_override)
    setup_logging(config["output"]["log_path"])
    show_startup_banner()
    result = _try_dispatch(config, DeliveryPayload(notification_type=notification_type, notices=[], study_plan=["这是一封测试邮件，来自阿斯加德系统。"]), preview_only=False)
    emit_console_summary(f"测试邮件发送{'成功' if result.success else '失败'}: {result.message}")
    return 0 if result.success else 1


def run_loop(
    config_path: str,
    preview_only: bool = False,
    storage_override: str = "",
    reprocess_all: bool = False,
) -> int:
    config = _prepare_config(config_path, storage_override)
    setup_logging(config["output"]["log_path"])
    show_startup_banner()

    scheduler_cfg = config["scheduler"]
    if not scheduler_cfg.get("enabled", True):
        return _run_compat_loop(config_path, preview_only, storage_override, reprocess_all)

    scheduler = Scheduler(
        config_factory=lambda: _prepare_config(config_path, storage_override),
        cycle_fn=lambda cfg, mode: run_cycle(
            config=cfg,
            storage=build_services(cfg)[0],
            scraper=build_services(cfg)[1],
            parser=build_services(cfg)[2],
            notifier=build_services(cfg)[3],
            mail_ingress=build_services(cfg)[6],
            task_store=build_services(cfg)[4],
            delivery_mode=mode,
            preview_only=preview_only,
            reprocess_all=reprocess_all,
        ),
        mailbox_fn=lambda cfg: process_mailbox(
            config=cfg,
            mail_ingress=build_services(cfg)[6],
            notifier=build_services(cfg)[3],
            task_store=build_services(cfg)[4],
            preview_only=preview_only,
        ),
    )
    return scheduler.run(preview_only=preview_only)


def _run_compat_loop(
    config_path: str,
    preview_only: bool,
    storage_override: str,
    reprocess_all: bool,
) -> int:
    import time
    config = _prepare_config(config_path, storage_override)
    poll_interval = max(int(config["runtime"]["polling_interval"]), 1)
    while True:
        try:
            current_config = _prepare_config(config_path, storage_override)
            services = build_services(current_config)
            mail_ingress = services[6]
            if current_config.get("inbound_email", {}).get("enabled", False) and not preview_only:
                process_mailbox(current_config, mail_ingress, services[3], services[4], preview_only)
            run_cycle(
                config=current_config, storage=services[0], scraper=services[1],
                parser=services[2], notifier=services[3], mail_ingress=mail_ingress,
                task_store=services[4], delivery_mode="heartbeat",
                preview_only=preview_only, reprocess_all=reprocess_all,
            )
            time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("收到中断信号，已退出。")
            emit_console_summary("阿斯加德已停止")
            return 0
        except Exception as exc:
            logger.error("循环运行失败: %s", exc)
            time.sleep(poll_interval)


def _prepare_config(config_path: str, storage_override: str = "") -> dict[str, Any]:
    from pathlib import Path
    config = Config.load(config_path)
    if storage_override:
        config._raw["storage"]["path"] = str(Path(storage_override).resolve())
    return config._raw
