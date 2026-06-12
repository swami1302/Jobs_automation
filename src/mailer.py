"""M6 Gmail sender (SMTP + App Password) with attachment.

Activates only when GMAIL_ADDRESS and GMAIL_APP_PASSWORD are set in .env.
Uses Gmail's SSL SMTP — no Google Cloud / OAuth needed.
"""
from __future__ import annotations

import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

from . import config


def can_send() -> bool:
    return bool(config.get("GMAIL_ADDRESS") and config.get("GMAIL_APP_PASSWORD"))


def default_resume() -> Path | None:
    pdfs = sorted(config.RESUMES_DIR.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def send_email(
    to: str, subject: str, body: str, attachments: list[Path] | None = None
) -> None:
    """Send a plain-text email from the configured Gmail with optional attachments."""
    sender = config.require("GMAIL_ADDRESS")
    password = config.require("GMAIL_APP_PASSWORD")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    for path in attachments or []:
        path = Path(path)
        if not path.exists():
            continue
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
