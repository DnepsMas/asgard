from __future__ import annotations

import logging
import sys
from collections import deque
from datetime import datetime
from typing import Any

# The [EYE] placeholder renders as "@" (red when ANSI color is available).
STARTUP_BANNER = r"""
                                  ___
                     __..---''''''   ``''---..__
               _..-''      _..---.._            ``-._
            .-'         .-'   [EYE] `-.              `.
          .'          .'    .-''''-.   `.              \
         /          .'     /  .--.  \    \              \
        ;         .'      |  /    \  |    ;              ;
        |        /        | |  __  | |    |              |
        |       ;         | | (__) | |    |             /
        ;       |          \ \____/ /    /           _.'
         \      ;           `-.__.-'   .'
          `.     \                    .'
            `-._  `-._           _..-'
                ``--.. ``-----''_.-'
                       `-.___.-'  \
                               \   \
                            ___/   /__
                           /___.--'___\


      ___    _____   ______   ___    ____   ____
     /   |  / ___/  / ____/  /   |  / __ \ / __ \
    / /| |  \__ \  / / __   / /| | / /_/ // / / /
   / ___ | ___/ / / /_/ /  / ___ |/ _, _// /_/ /
  /_/  |_|/____/  \____/  /_/  |_/_/ |_| \____/
"""


def prepare_console_io() -> None:
    """Ensure stdout/stderr use UTF-8 encoding."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _stream_supports_redraw(stream: Any) -> bool:
    """Check whether the terminal supports VT escape sequences."""
    if not bool(getattr(stream, "isatty", lambda: False)()):
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        virtual_terminal = 0x0004
        if mode.value & virtual_terminal:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | virtual_terminal))
    except Exception:
        return False


class ConsoleSummaryFilter(logging.Filter):
    """Only passes WARNING+ records or records with console_summary=True."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return bool(getattr(record, "console_summary", False))


class ConsoleSummaryFormatter(logging.Formatter):
    """Compact timestamped console output."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        message = record.getMessage()
        if record.levelno >= logging.WARNING:
            return f"{timestamp} | {record.levelname} | {message}"
        return f"{timestamp} | {message}"


class PinnedConsoleHandler(logging.Handler):
    """Logging handler that renders a pinned banner above scrollable log lines."""

    def __init__(self, banner: str, stream: Any, max_lines: int = 18):
        super().__init__(level=logging.INFO)
        self.banner_lines = banner.strip("\n").splitlines()
        self.stream = stream
        self.lines: deque[str] = deque(maxlen=max_lines)
        self.supports_redraw = _stream_supports_redraw(stream)
        self.banner_rendered = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            if not self.supports_redraw:
                if not self.banner_rendered:
                    self._render()
                self.stream.write(message + "\n")
                self.stream.flush()
                return
            for line in message.splitlines() or [""]:
                self.lines.append(line)
            self._render()
        except Exception:
            self.handleError(record)

    def render(self) -> None:
        """Public alias for _render, used by show_startup_banner."""
        self._render()

    def _render(self) -> None:
        divider = "-" * 62
        if self.supports_redraw:
            banner_lines = []
            for line in self.banner_lines:
                formatted = line.replace("[EYE]", "\033[91m@\033[96m")
                banner_lines.append(f"\033[96m{formatted}\033[0m" if line.strip() else line)
            divider_line = f"\033[90m{divider}\033[0m"
        else:
            banner_lines = [line.replace("[EYE]", "@") for line in self.banner_lines]
            divider_line = divider
        content = banner_lines + [divider_line, ""] + list(self.lines)
        if self.supports_redraw:
            self.stream.write("\033[2J\033[H")
        self.stream.write("\n".join(content) + "\n")
        self.stream.flush()
        self.banner_rendered = True


def setup_logging(log_path: str) -> None:
    """Configure file + pinned-console logging."""
    path = __import__("pathlib").Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
    )

    console_handler = PinnedConsoleHandler(STARTUP_BANNER, sys.stdout)
    console_handler.addFilter(ConsoleSummaryFilter())
    console_handler.setFormatter(ConsoleSummaryFormatter())

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def emit_console_summary(
    message: str, *args: Any, level: int = logging.INFO
) -> None:
    """Emit a message that bypasses ConsoleSummaryFilter for console display."""
    logging.getLogger(__package__ or __name__).log(
        level, message, *args, extra={"console_summary": True}
    )


def show_startup_banner() -> None:
    """Force-render the banner once logging is set up."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, PinnedConsoleHandler):
            handler.render()
            break
    emit_console_summary("阿斯加德已启动，完整日志写入 output/iris.log")
