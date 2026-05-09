"""
logger_setup.py
---------------
Central logging configuration for the entire pipeline.

Sets up TWO handlers:
  1. Console  → Rich colored output, human-readable, shows only INFO+
  2. File     → Plain text rotating log, keeps last 7 days, shows DEBUG+

Usage in every other module:
    from logger_setup import get_logger
    logger = get_logger(__name__)

Why centralise?
  Every module calling basicConfig() causes duplicate handlers and
  inconsistent formatting. One setup module, called once in main().
"""

import logging
import logging.handlers
from pathlib import Path
from datetime import datetime

from rich.logging import RichHandler
from rich.console import Console

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# One log file per day — easy to find yesterday's run
LOG_FILE = LOG_DIR / f"digest_{datetime.now().strftime('%Y-%m-%d')}.log"

_configured = False   # guard so setup_logging() is idempotent


def setup_logging(level: str = "INFO") -> None:
    """
    Call this ONCE at the start of main().
    Configures root logger with Rich console + rotating file handler.
    """
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)   # root captures everything; handlers filter

    # ── Handler 1: Rich console ───────────────────────────────────────────────
    # Rich gives us colors, level badges, timestamps, and module names
    console = Console(stderr=False)
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_level=True,
        show_path=False,               # don't show file:line — too noisy
        rich_tracebacks=True,
        markup=True,
        log_time_format="[%H:%M:%S]",
    )
    rich_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(rich_handler)

    # ── Handler 2: Rotating file log ─────────────────────────────────────────
    # Keeps last 7 daily files. Full DEBUG level for post-mortem analysis.
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=LOG_FILE,
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)

    # Silence noisy third-party loggers
    for noisy in ["urllib3", "requests", "feedparser", "charset_normalizer"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Shorthand used by every module: logger = get_logger(__name__)"""
    return logging.getLogger(name)
