from __future__ import annotations

import argparse


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the campus AI assistant."""
    parser = argparse.ArgumentParser(description="校园网消息 AI 助手")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--loop", action="store_true", help="循环轮询")
    parser.add_argument("--preview-only", action="store_true", help="仅生成本地预览，不发送邮件")
    parser.add_argument("--email-test", action="store_true", help="使用当前 SMTP 配置发送一封测试邮件")
    parser.add_argument(
        "--email-type",
        choices=["heartbeat", "morning_digest", "evening_digest"],
        default="heartbeat",
        help="测试邮件类型，默认发送 heartbeat 风格邮件",
    )
    parser.add_argument("--storage", default="", help="覆盖 storage.path")
    parser.add_argument("--reprocess-all", action="store_true", help="忽略去重，重新分析本次抓到的所有消息")
    return parser.parse_args()


def main() -> int:
    prepare_console_io()
    args = parse_args()

    if args.email_test:
        from .app import run_email_test
        return run_email_test(args.config, notification_type=args.email_type, storage_override=args.storage)
    elif args.loop:
        from .app import run_loop
        return run_loop(args.config, preview_only=args.preview_only, storage_override=args.storage, reprocess_all=args.reprocess_all)
    from .app import run_once
    return run_once(args.config, preview_only=args.preview_only, storage_override=args.storage, reprocess_all=args.reprocess_all)


def prepare_console_io() -> None:
    import sys
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
