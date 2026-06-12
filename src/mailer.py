"""M6 email sender — two backends, picked automatically:

  * Brevo HTTP API (port 443)  — used when BREVO_API_KEY is set. Works on hosts
    that block SMTP ports (e.g. Render's free tier blocks 25/465/587).
  * Gmail SMTP (port 465)      — fallback for local use; needs GMAIL_ADDRESS +
    GMAIL_APP_PASSWORD.

The "From" address is SENDER_EMAIL or, if unset, GMAIL_ADDRESS. For Brevo this
address must be a *verified sender* in your Brevo account.

Resume attachment: the local PDF in data/resumes/ if present; otherwise the file
is fetched from RESUME_URL (so it still attaches on a deploy where the gitignored
PDF is absent). Google Drive share links are auto-converted to direct downloads.
"""
from __future__ import annotations

import base64
import mimetypes
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path

import httpx

from . import config

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


def _sender() -> str | None:
    return config.get("SENDER_EMAIL") or config.get("GMAIL_ADDRESS")


def can_send() -> bool:
    """True if either backend is configured."""
    if config.get("BREVO_API_KEY") and _sender():
        return True
    return bool(config.get("GMAIL_ADDRESS") and config.get("GMAIL_APP_PASSWORD"))


def default_resume() -> Path | None:
    pdfs = sorted(config.RESUMES_DIR.glob("*.pdf")) if config.RESUMES_DIR.exists() else []
    return pdfs[0] if pdfs else None


def has_resume() -> bool:
    """Will an attachment be available? (local PDF, or a fetchable RESUME_URL.)"""
    return bool(default_resume() or (config.get("RESUME_URL") or "").strip())


# ----------------------------------------------------------------- attachments


def _gdrive_direct(url: str) -> str:
    """Turn a Drive 'file/d/<id>/view' share link into a direct-download URL."""
    m = re.search(r"/file/d/([^/]+)", url)
    return f"https://drive.google.com/uc?export=download&id={m.group(1)}" if m else url


def _fetch_resume() -> tuple[str, bytes] | None:
    """Download the resume from RESUME_URL → (filename, bytes), or None."""
    url = (config.get("RESUME_URL") or "").strip()
    if not url:
        return None
    try:
        r = httpx.get(_gdrive_direct(url), timeout=30, follow_redirects=True)
    except Exception:
        return None
    if r.status_code == 200 and r.content[:4] == b"%PDF":
        return ("resume.pdf", r.content)
    return None


def _attachment_parts(attachments: list[Path] | None) -> list[tuple[str, bytes]]:
    """Resolve attachments to (filename, bytes). Falls back to RESUME_URL."""
    parts: list[tuple[str, bytes]] = []
    for path in attachments or []:
        path = Path(path)
        if path.exists():
            parts.append((path.name, path.read_bytes()))
    if not parts:
        fetched = _fetch_resume()
        if fetched:
            parts.append(fetched)
    return parts


# -------------------------------------------------------------------- backends


def _send_smtp(to: str, subject: str, body: str, parts: list[tuple[str, bytes]]) -> None:
    sender = config.require("GMAIL_ADDRESS")
    password = config.require("GMAIL_APP_PASSWORD")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    for name, data in parts:
        ctype, _ = mimetypes.guess_type(name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)


def _send_brevo(to: str, subject: str, body: str, parts: list[tuple[str, bytes]]) -> None:
    sender = _sender()
    if not sender:
        raise RuntimeError("No sender address — set SENDER_EMAIL or GMAIL_ADDRESS.")
    payload: dict = {
        "sender": {"email": sender},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body,
    }
    if parts:
        payload["attachment"] = [
            {"name": name, "content": base64.b64encode(data).decode()}
            for name, data in parts
        ]
    r = httpx.post(
        BREVO_ENDPOINT,
        headers={
            "api-key": config.require("BREVO_API_KEY"),
            "content-type": "application/json",
            "accept": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Brevo send failed [{r.status_code}]: {r.text[:200]}")


def send_email(
    to: str, subject: str, body: str, attachments: list[Path] | None = None
) -> None:
    """Send via Brevo HTTP if BREVO_API_KEY is set, else Gmail SMTP."""
    parts = _attachment_parts(attachments)
    if config.get("BREVO_API_KEY"):
        _send_brevo(to, subject, body, parts)
    else:
        _send_smtp(to, subject, body, parts)
