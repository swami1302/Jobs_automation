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

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
)

from . import config, models, store

MIN_SCORE = int(config.get("MIN_MATCH_SCORE", "50"))
_ALLOWED = config.get("TELEGRAM_USER_ID")

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


async def _send_next(chat, context: ContextTypes.DEFAULT_TYPE) -> None:
    jobs = store.top_matches(status=models.PENDING, min_score=MIN_SCORE, limit=1)
    if not jobs:
        await chat.send_message(
            "🎉 That's all the matches for now!\n"
            "Run the scraper again later for fresh jobs, or lower MIN_MATCH_SCORE."
        )
        return
    job = jobs[0]
    await chat.send_message(
        _card_text(job),
        parse_mode=ParseMode.HTML,
        reply_markup=_keyboard(job["id"]),
        disable_web_page_preview=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
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


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    c = store.counts()
    await update.message.reply_text(
        "📊 Status counts:\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(c.items()))
        + f"\n(showing matches ≥ {MIN_SCORE}%)"
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _authorized(update):
        return
    action, jid = query.data.split(":")
    job_id = int(jid)
    status = _ACTIONS[action]
    store.set_status(job_id, status)

    # freeze the decided card (drop buttons, mark the choice)
    await query.edit_message_text(
        text=query.message.text_html + f"\n\n<b>{_DONE[status]}</b>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    await _send_next(query.message.chat, context)


def build_app() -> Application:
    token = config.require("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("next", next_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    return app
