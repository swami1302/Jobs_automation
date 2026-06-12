"""M4 runner: start the Telegram swipe bot (long-polling) with console logging.

    .venv/bin/python -m scripts.run_bot

Set LOG_LEVEL=DEBUG in .env for more verbose output (default INFO).
Then open Telegram, find your bot, and send /start. Ctrl-C to stop.
"""
from __future__ import annotations

import logging

from src import config
from src.bot import build_app


def _setup_logging() -> None:
    level = getattr(logging, (config.get("LOG_LEVEL", "INFO") or "INFO").upper(), logging.INFO)
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )
    # quiet the noisy libraries; keep our own logs clean
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def main() -> None:
    _setup_logging()
    log = logging.getLogger("bot")
    app = build_app()
    log.info("=== job-swipe bot starting (long-polling) ===")
    log.info("Backend: %s | open Telegram and send /start. Ctrl-C to stop.",
             __import__("src.store", fromlist=["backend"]).backend())
    app.run_polling()


if __name__ == "__main__":
    main()
