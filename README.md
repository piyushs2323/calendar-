# Buyer Bot

Telegram bot: send a voice note ("gave this account to Rahul, email rahul@gmail.com, today"),
it transcribes it, pulls out name/email/date, and logs it with a renewal due date.
When an account is due, it messages you with Renewed / Revoke buttons.
Tap Renewed → due date auto-pushes to the next cycle. Tap Revoke → marked revoked, go pull access yourself.

## Get your keys
1. Telegram bot token: message @BotFather on Telegram → /newbot.
2. Your admin chat id: message @userinfobot on Telegram, it replies with your chat id.
3. OpenAI API key: platform.openai.com/api-keys (used for voice transcription + parsing).

## Run locally
```
pip install -r requirements.txt
cp .env.example .env   # fill in the three values above
python bot.py
```

## Deploy on Railway
1. Push this folder to a GitHub repo (or use `railway up` from this folder directly).
2. New Railway project → deploy from repo.
3. In Railway → Variables, add: TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID, OPENAI_API_KEY.
4. (Optional) Add a Railway Postgres plugin and set DATABASE_URL to its connection string —
   otherwise it uses SQLite on disk, which resets on redeploy. For anything you care about
   keeping, attach a Railway volume or use Postgres.
5. Deploy. Railway runs `python bot.py` per railway.json.

## Commands
- Send a voice note → auto-logs an account.
- `/add Name | email | YYYY-MM-DD | days` → manual add (days optional, defaults to 30).
- `/list` → all active accounts and days left.
- Daily at `EXPIRY_CHECK_HOUR` (server time, default 9am), it pings you for anything due.

## Notes / what you'll want to tweak
- Revoke button currently just marks the DB row `revoked` — wire `handle_callback`'s revoke
  branch into your instaddr12 panel's API if you want it to actually pull access automatically.
- Renewal always adds `plan_days` (default 30) to the *old* due date, not to today — so it
  stays on the same day-of-month cycle even if you renew late.
- If a voice note is missing a field (e.g. no date heard), the bot tells you what's missing
  instead of guessing — reply with `/add` for that one.
