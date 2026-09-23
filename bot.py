import asyncio
import logging
import re
from datetime import date, datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import config
import database as db
from extractor import transcribe_and_extract

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("buyer-bot")


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _safe_date(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_add_text(text, today=None, default_days=30, default_today=True):
    """Parse '/add' body. Returns (name, emails, date_given, plan_days).
    Name: words left over. Emails: any number. Date: today/yesterday/tomorrow,
    YYYY-MM-DD, DD/MM/YYYY, DD/MM, '23 sep', 'sep 23' (default: today).
    Plan days: '30d' / '30 days' / a lone number (default: default_days)."""
    today = today or date.today()
    emails = EMAIL_RE.findall(text)
    rest = EMAIL_RE.sub(" ", text)
    found = None

    def take(m, d):
        nonlocal found
        if d and found is None:
            found = d
            return " "
        return m.group(0)

    # order matters: most specific first
    rest = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",
                  lambda m: take(m, _safe_date(int(m[1]), int(m[2]), int(m[3]))), rest)
    rest = re.sub(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b",
                  lambda m: take(m, _safe_date(int(m[3]), int(m[2]), int(m[1]))), rest)
    rest = re.sub(r"\b(\d{1,2})[/](\d{1,2})\b",
                  lambda m: take(m, _safe_date(today.year, int(m[2]), int(m[1]))), rest)
    mon = "|".join(MONTHS)
    rest = re.sub(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({mon})[a-z]*\b",
                  lambda m: take(m, _safe_date(today.year, MONTHS[m[2].lower()], int(m[1]))),
                  rest, flags=re.I)
    rest = re.sub(rf"\b({mon})[a-z]*\s+(\d{{1,2}})(?:st|nd|rd|th)?\b",
                  lambda m: take(m, _safe_date(today.year, MONTHS[m[1].lower()], int(m[2]))),
                  rest, flags=re.I)
    words = {"today": 0, "yesterday": -1, "tomorrow": 1}
    rest = re.sub(r"\b(today|yesterday|tomorrow)\b",
                  lambda m: take(m, today + timedelta(days=words[m[1].lower()])),
                  rest, flags=re.I)

    plan_days = None
    m = re.search(r"\b(\d{1,3})\s*(?:d|days?)\b", rest, flags=re.I) or re.search(r"\b(\d{1,3})\b", rest)
    if m:
        plan_days = int(m.group(1))
        rest = rest[:m.start()] + " " + rest[m.end():]

    name = " ".join(re.sub(r"[|,;]", " ", rest).split())
    return name, emails, (found or (today if default_today else None)), plan_days or default_days


def is_admin(update: Update) -> bool:
    if not config.ADMIN_CHAT_ID:
        return True
    return str(update.effective_chat.id) == str(config.ADMIN_CHAT_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send a voice note: buyer name, email, date given.\n"
        "I'll log it and remind you when it's due for renewal.\n\n"
        "/list - active accounts\n"
        "/remove ummi - delete accounts (by name, email or #id)\n"
        "/add Name (newline) emails... (newline) today - manual add, many emails at once\n"
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(
            f"Not authorized. Your chat ID is {update.effective_chat.id}. "
            f"Set ADMIN_CHAT_ID to this number in Railway."
        )
        return
    voice = update.message.voice or update.message.audio
    if not voice:
        return
    tg_file = await voice.get_file()
    path = f"/tmp/{voice.file_unique_id}.ogg"
    await tg_file.download_to_drive(path)

    await update.message.reply_text("Listening...")
    try:
        transcript, fields = await asyncio.to_thread(transcribe_and_extract, path)
    except Exception as e:
        log.exception("extraction failed")
        await update.message.reply_text(f"Couldn't process that voice note: {e}")
        return

    missing = [k for k in ("buyer_name", "email", "date_given") if not fields.get(k)]
    if missing:
        await update.message.reply_text(
            f"Heard: \"{transcript}\"\n"
            f"Missing: {', '.join(missing)}. Send it again with those details, "
            f"or use /add Name | email | YYYY-MM-DD"
        )
        return

    try:
        date_given = datetime.strptime(fields["date_given"], "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text(f"Couldn't parse date '{fields['date_given']}'. Use /add to enter manually.")
        return

    plan_days = fields.get("plan_days") or config.DEFAULT_PLAN_DAYS
    acc = db.add_account(fields["buyer_name"], fields["email"], date_given, plan_days)

    await update.message.reply_text(
        f"Logged #{acc.id}\n"
        f"Buyer: {acc.buyer_name}\n"
        f"Email: {acc.email}\n"
        f"Given: {acc.date_given}\n"
        f"Renewal due: {acc.expiry_date}"
    )


async def add_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(
            f"Not authorized. Your chat ID is {update.effective_chat.id}. "
            f"Set ADMIN_CHAT_ID to this number in Railway."
        )
        return
    parts = update.message.text.split(None, 1)
    text = parts[1] if len(parts) > 1 else ""
    name, emails, date_given, plan_days = parse_add_text(text, default_days=config.DEFAULT_PLAN_DAYS)
    if not name or not emails:
        await update.message.reply_text(
            "Usage:\n"
            "/add ummi\n"
            "a@gmail.com\n"
            "b@gmail.com\n"
            "today\n\n"
            "Name, then one or more emails, then a date (today / yesterday / 23 sep / 2026-09-23). "
            "Date defaults to today. Optional plan length: 30d (default 30 days)."
        )
        return
    lines = []
    for email in emails:
        acc = db.add_account(name, email, date_given, plan_days)
        lines.append(f"#{acc.id} {email}")
    await update.message.reply_text(
        f"Logged {len(emails)} for {name}\n"
        f"Given: {date_given}  |  Plan: {plan_days}d  |  Due: {date_given + timedelta(days=plan_days)}\n\n"
        + "\n".join(lines)
    )


async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(
            f"Not authorized. Your chat ID is {update.effective_chat.id}. "
            f"Set ADMIN_CHAT_ID to this number in Railway."
        )
        return
    parts = update.message.text.split(None, 1)
    text = parts[1] if len(parts) > 1 else ""
    ids = [int(x) for x in re.findall(r"#(\d+)", text)]
    text = re.sub(r"#\d+", " ", text)
    name, emails, date_given, _ = parse_add_text(text, default_today=False)
    if not (name or emails or ids):
        await update.message.reply_text(
            "Usage:\n"
            "/remove ummi  - all accounts of ummi\n"
            "/remove ummi today  - only ummi's accounts given today (or 23 sep, 2026-09-23)\n"
            "/remove a@gmail.com b@gmail.com  - specific emails\n"
            "/remove #5 #6  - by entry number"
        )
        return
    accs = db.find_accounts(name=name or None, emails=emails or None, ids=ids or None, date_given=date_given)
    if not accs:
        await update.message.reply_text("No matching accounts found.")
        return
    token = str(update.message.message_id)
    context.bot_data.setdefault("pending_rm", {})[token] = [a.id for a in accs]
    shown = [f"#{a.id} {a.buyer_name} <{a.email}> given {a.date_given}" for a in accs[:40]]
    extra = f"\n...and {len(accs) - 40} more" if len(accs) > 40 else ""
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🗑 Delete {len(accs)}", callback_data=f"rmok:{token}"),
        InlineKeyboardButton("Cancel", callback_data=f"rmno:{token}"),
    ]])
    await update.message.reply_text(
        f"Remove these {len(accs)} account(s)? This can't be undone.\n\n" + "\n".join(shown) + extra,
        reply_markup=kb,
    )


async def handle_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update):
        return
    action, token = query.data.split(":", 1)
    ids = context.bot_data.get("pending_rm", {}).pop(token, None)
    if action == "rmno":
        await query.edit_message_text("Cancelled. Nothing was deleted.")
        return
    if not ids:
        await query.edit_message_text("This request expired. Send /remove again.")
        return
    n = db.delete_accounts(ids)
    await query.edit_message_text(f"Deleted {n} account(s).")


async def list_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(
            f"Not authorized. Your chat ID is {update.effective_chat.id}. "
            f"Set ADMIN_CHAT_ID to this number in Railway."
        )
        return
    accs = db.list_active()
    if not accs:
        await update.message.reply_text("No active accounts.")
        return
    lines = []
    for a in accs:
        d = a.days_left()
        flag = " ⚠️ DUE" if d <= 0 else f" ({d}d left)"
        lines.append(f"#{a.id} {a.buyer_name} <{a.email}> due {a.expiry_date}{flag}")
    await update.message.reply_text("\n".join(lines))


def renewal_keyboard(account_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Renewed", callback_data=f"renew:{account_id}"),
        InlineKeyboardButton("🚫 Revoke", callback_data=f"revoke:{account_id}"),
    ]])


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, acc_id = query.data.split(":")
    acc_id = int(acc_id)
    acc = db.get_account(acc_id)
    if not acc:
        await query.edit_message_text("Account not found (deleted?).")
        return

    if action == "renew":
        acc = db.renew_account(acc_id)
        await query.edit_message_text(
            f"#{acc.id} {acc.buyer_name} renewed. Next due: {acc.expiry_date}"
        )
    elif action == "revoke":
        db.set_status(acc_id, "revoked")
        await query.edit_message_text(
            f"#{acc.id} {acc.buyer_name} <{acc.email}> marked REVOKED.\n"
            f"Go pull the access on your panel for this email."
        )


async def check_expiries(context: ContextTypes.DEFAULT_TYPE):
    due = db.list_due()
    if not due or not config.ADMIN_CHAT_ID:
        return
    for acc in due:
        db.set_status(acc.id, "pending_action")
        text = (
            f"⏰ Renewal due\n"
            f"#{acc.id} {acc.buyer_name}\n"
            f"Email: {acc.email}\n"
            f"Was due: {acc.expiry_date}\n\n"
            f"Tap once you know the outcome:"
        )
        await context.bot.send_message(
            chat_id=config.ADMIN_CHAT_ID, text=text, reply_markup=renewal_keyboard(acc.id)
        )


def main():
    db.init_db()
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("list", list_active))
    app.add_handler(CommandHandler("add", add_manual))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("delete", remove_cmd))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(CallbackQueryHandler(handle_remove_callback, pattern=r"^rm(ok|no):"))
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.job_queue.run_daily(
        check_expiries,
        time=datetime.strptime(f"{config.EXPIRY_CHECK_HOUR}:00", "%H:%M").time(),
    )

    log.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
