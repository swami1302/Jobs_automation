"""M4: Telegram swipe bot.

Shows your best-matching pending jobs one card at a time with inline buttons:
    ✅ Apply   ❌ Skip   🔖 Save
Tapping a button updates the job's status in the DB (Neon) and sends the next
card — Tinder-style, but with buttons (chat apps can't do real swipes).

Commands:
    /start  greet + show the first card
    /next   show the next card
    /stats  show counts by status

Config (.env):
    TELEGRAM_BOT_TOKEN   required
    MIN_MATCH_SCORE      only show jobs scoring >= this (default 50)
    TELEGRAM_USER_ID     optional — if set, only that Telegram user may use the bot
"""
from __future__ import annotations

import asyncio
import html
import logging

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
)

from . import config, contacts, mailer, messages, models, store
from .profile import Profile, load_profile

log = logging.getLogger("bot")

MIN_SCORE = int(config.get("MIN_MATCH_SCORE", "50"))
_ALLOWED = config.get("TELEGRAM_USER_ID")


def _who(update: Update) -> str:
    u = update.effective_user
    return f"{u.id}/@{u.username}" if u else "?"


# Shown in Telegram's "/" menu + the Menu button (set on startup, no BotFather).
COMMANDS = [
    BotCommand("start", "Show your top job match"),
    BotCommand("next", "Skip to the next job"),
    BotCommand("saved", "Review jobs you bookmarked (🔖)"),
    BotCommand("stats", "Counts by status (applied/skipped/…)"),
    BotCommand("help", "What this bot does"),
]

_OUTREACH: dict[int, dict] = {}  # job_id -> {to, subject, body, linkedin}
_PROFILE: Profile | None = None


def _profile() -> Profile:
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = load_profile()
    return _PROFILE

_ACTIONS = {"apply": models.APPLIED, "skip": models.SKIPPED, "save": models.SAVED}
_DONE = {
    models.APPLIED: "✅ Applied",
    models.SKIPPED: "❌ Skipped",
    models.SAVED: "🔖 Saved",
}


def _authorized(update: Update) -> bool:
    if not _ALLOWED:
        return True
    user = update.effective_user
    return bool(user and str(user.id) == str(_ALLOWED))


def _card_text(job: dict) -> str:
    e = html.escape
    parts = [
        f"💼 <b>{e(job['title'] or 'Untitled')}</b>",
        f"🏢 {e(job['company'] or '?')}   📍 {e(job['location'] or '?')}",
        f"🎯 Match: <b>{job['match_score']}%</b>"
        + (f"   🗓 {e(job['posted'])}" if job.get("posted") else ""),
    ]
    if job.get("comment"):
        parts.append(f"📝 {e(job['comment'])}")
    if job.get("apply_link"):
        parts.append(f'\n🔗 <a href="{e(job["apply_link"])}">Open job ↗</a>')
    return "\n".join(parts)


def _keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Apply", callback_data=f"apply:{job_id}"),
        InlineKeyboardButton("❌ Skip", callback_data=f"skip:{job_id}"),
        InlineKeyboardButton("🔖 Save", callback_data=f"save:{job_id}"),
    ]])


def _saved_keyboard(job_id: int) -> InlineKeyboardMarkup:
    """Buttons for a bookmarked job. The `s_` prefix tells on_button this came
    from the /saved review, so it won't inject a fresh pending card afterwards."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Apply", callback_data=f"s_apply:{job_id}"),
        InlineKeyboardButton("❌ Skip", callback_data=f"s_skip:{job_id}"),
    ]])


async def _send_next(chat, context: ContextTypes.DEFAULT_TYPE) -> None:
    jobs = store.top_matches(status=models.PENDING, min_score=MIN_SCORE, limit=1)
    if not jobs:
        log.info("no more pending jobs >= %s%%", MIN_SCORE)
        await chat.send_message(
            "🎉 That's all the matches for now!\n"
            "Run the scraper again later for fresh jobs, or lower MIN_MATCH_SCORE."
        )
        return
    job = jobs[0]
    log.info("→ card: #%s %r @ %s (%s%%)",
             job["id"], job["title"], job["company"], job["match_score"])
    await chat.send_message(
        _card_text(job),
        parse_mode=ParseMode.HTML,
        reply_markup=_keyboard(job["id"]),
        disable_web_page_preview=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.info("/start from %s", _who(update))
    if not _authorized(update):
        log.warning("unauthorized /start from %s", _who(update))
        await update.message.reply_text("Not authorized.")
        return
    # help the user lock the bot to their account
    uid = update.effective_user.id if update.effective_user else "?"
    counts = store.counts()
    pending = counts.get(models.PENDING, 0)
    await update.message.reply_text(
        f"👋 Job-swipe bot ready (your Telegram id: <code>{uid}</code>).\n"
        f"{pending} pending jobs, showing matches ≥ {MIN_SCORE}%.\n"
        "Tap ✅ Apply / ❌ Skip / 🔖 Save on each card.",
        parse_mode=ParseMode.HTML,
    )
    await _send_next(update.effective_chat, context)


async def next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await _send_next(update.effective_chat, context)


async def saved_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List bookmarked jobs as cards so you can Apply/Skip them later."""
    if not _authorized(update):
        return
    jobs = store.top_matches(status=models.SAVED, min_score=0, limit=15)
    log.info("/saved from %s — %d saved job(s)", _who(update), len(jobs))
    if not jobs:
        await update.message.reply_text(
            "🔖 No saved jobs yet. Tap 🔖 Save on a card to bookmark it for later."
        )
        return
    await update.message.reply_text(f"🔖 Your saved jobs ({len(jobs)}):")
    for job in jobs:
        await update.effective_chat.send_message(
            _card_text(job),
            parse_mode=ParseMode.HTML,
            reply_markup=_saved_keyboard(job["id"]),
            disable_web_page_preview=True,
        )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    c = store.counts()
    await update.message.reply_text(
        "📊 Status counts:\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(c.items()))
        + f"\n(showing matches ≥ {MIN_SCORE}%)"
    )


async def _draft_outreach(chat, job_id: int) -> None:
    """On Apply: find a contact, draft cold email + LinkedIn note, show them."""
    job = store.get_job(job_id)
    if not job:
        return
    log.info("drafting outreach for #%s %r @ %s", job_id, job["title"], job["company"])
    note = await chat.send_message("✍️ Finding a contact and drafting your outreach…")
    try:
        contact = await asyncio.to_thread(contacts.enrich, job)
        log.info("  contact: %s", contact or "none found")
        draft = await asyncio.to_thread(messages.draft, _profile(), job, contact)
        log.info("  drafted email + linkedin note OK")
    except Exception as e:  # noqa: BLE001
        log.exception("  outreach failed for #%s", job_id)
        await note.edit_text(f"Couldn't draft outreach: {str(e)[:140]}")
        return

    email = (contact or {}).get("email", "")
    name = (contact or {}).get("name", "")
    if email:
        store.set_contact(job_id, email, name)
    _OUTREACH[job_id] = {"to": email, **draft}

    e = html.escape
    li = contacts.linkedin_people_search(job.get("company", ""))
    lines = []
    if email:
        src = (contact or {}).get("source", "")
        lines.append(f"👤 {e(name or 'Contact')} · ✉️ <code>{e(email)}</code> ({src})")
    else:
        lines.append("👤 No email found — use the apply link + LinkedIn search below.")
    lines.append(f"\n📧 <b>COLD EMAIL</b>\nSubject: <code>{e(draft['subject'])}</code>")
    lines.append(f"<pre>{e(draft['body'])}</pre>")
    lines.append(f"💬 <b>LINKEDIN MESSAGE</b>\n<pre>{e(draft['linkedin'])}</pre>")
    lines.append(f'🔎 <a href="{e(li)}">Find an HR / recruiter at {e(job.get("company") or "this company")} on LinkedIn ↗</a>')

    buttons = []
    if email and mailer.can_send():
        buttons.append([InlineKeyboardButton(
            "📧 Send email (with resume)", callback_data=f"send:{job_id}")])
    markup = InlineKeyboardMarkup(buttons) if buttons else None

    await note.delete()
    await chat.send_message(
        "\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=markup, disable_web_page_preview=True,
    )
    if email and not mailer.can_send():
        await chat.send_message(
            "ℹ️ Add GMAIL_ADDRESS + GMAIL_APP_PASSWORD to .env to enable one-tap "
            "send. For now, copy-paste the email above."
        )


async def _do_send(query, job_id: int) -> None:
    data = _OUTREACH.get(job_id)
    if not data:
        await query.message.reply_text("Draft expired — tap Apply again to redraft.")
        return
    to = data.get("to")
    if not to:
        await query.message.reply_text("No recipient email for this job.")
        return
    if not mailer.can_send():
        await query.message.reply_text(
            "Sending not configured. Add GMAIL_ADDRESS + GMAIL_APP_PASSWORD to .env."
        )
        return
    has_resume = mailer.has_resume()
    log.info("sending email for #%s to %s (resume=%s)", job_id, to, has_resume)
    try:
        # mailer resolves the attachment itself (local PDF or fetched RESUME_URL)
        await asyncio.to_thread(mailer.send_email, to, data["subject"], data["body"])
    except Exception as e:  # noqa: BLE001
        log.exception("  send failed for #%s", job_id)
        await query.message.reply_text(f"Send failed: {str(e)[:160]}")
        return
    log.info("  email sent to %s", to)
    await query.edit_message_reply_markup(reply_markup=None)
    attached = " with resume attached" if has_resume else ""
    await query.message.reply_text(f"✅ Email sent to {to}{attached}.")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(
        "🤖 <b>Job-swipe bot</b>\n"
        "I show your best-matching jobs one at a time. On each card:\n"
        "  ✅ Apply — mark applied + draft a cold email & LinkedIn message\n"
        "  ❌ Skip — not interested\n"
        "  🔖 Save — bookmark for later\n\n"
        "Commands:\n"
        "/start — show your top match\n"
        "/next — skip to the next job\n"
        "/saved — review jobs you bookmarked (Apply/Skip them)\n"
        "/stats — counts by status",
        parse_mode=ParseMode.HTML,
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _authorized(update):
        return
    action, jid = query.data.split(":")
    job_id = int(jid)
    log.info("button '%s' on #%s by %s", action, job_id, _who(update))

    if action == "send":
        await _do_send(query, job_id)
        return

    # `s_apply` / `s_skip` come from the /saved review — same effect, but don't
    # follow up with a fresh pending card (the user is reviewing bookmarks).
    from_saved = action.startswith("s_")
    real_action = action[2:] if from_saved else action

    status = _ACTIONS[real_action]
    store.set_status(job_id, status)
    await query.edit_message_text(
        text=query.message.text_html + f"\n\n<b>{_DONE[status]}</b>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    if real_action == "apply":
        await _draft_outreach(query.message.chat, job_id)
    if not from_saved:
        await _send_next(query.message.chat, context)


async def _post_init(app: Application) -> None:
    """Register the command menu in Telegram (the "/" list + Menu button)."""
    await app.bot.set_my_commands(COMMANDS)
    log.info("registered %d bot commands: %s",
             len(COMMANDS), ", ".join("/" + c.command for c in COMMANDS))


def build_app() -> Application:
    token = config.require("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("next", next_cmd))
    app.add_handler(CommandHandler("saved", saved_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    return app
