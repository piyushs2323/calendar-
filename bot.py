import asyncio
import logging
from datetime import date, datetime

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


def is_admin(update: Update) -> bool:
    if not config.ADMIN_CHAT_ID:
        return True
    return str(update.effective_chat.id) == str(config.ADMIN_CHAT_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send a voice note: buyer name, email, date given.\n"
        "I'll log it and remind you when it's due for renewal.\n\n"
        "/list - active accounts\n"
        "/add Name | email | YYYY-MM-DD [| days] - manual add\n"
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
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
        return
    text = update.message.text.partition(" ")[2]
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        await update.message.reply_text("Format: /add Name | email | YYYY-MM-DD [| plan_days]")
        return
    name, email, date_str = parts[0], parts[1], parts[2]
    plan_days = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else config.DEFAULT_PLAN_DAYS
    try:
        date_given = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text("Date must be YYYY-MM-DD.")
        return
    acc = db.add_account(name, email, date_given, plan_days)
    await update.message.reply_text(f"Logged #{acc.id}, due {acc.expiry_date}")


async def list_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
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
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.job_queue.run_daily(
        check_expiries,
        time=datetime.strptime(f"{config.EXPIRY_CHECK_HOUR}:00", "%H:%M").time(),
    )

    log.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
