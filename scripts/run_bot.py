"""M4 runner: start the Telegram swipe bot (long-polling).

    .venv/bin/python -m scripts.run_bot

Then open Telegram, find your bot, and send /start. Ctrl-C to stop.
"""
from __future__ import annotations

from src.bot import build_app


def main() -> None:
    app = build_app()
    print("Bot starting (long-polling). Open Telegram and send /start. Ctrl-C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
