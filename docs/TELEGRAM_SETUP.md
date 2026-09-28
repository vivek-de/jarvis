# Telegram setup for JARVIS

JARVIS can talk to you over Telegram: you chat with your bot, and the scheduler pushes
reminders to you. It's optional — leave `TELEGRAM_TOKEN` blank and Telegram stays off.

**Security:** the bot answers only ONE chat — the `TELEGRAM_CHAT_ID` you configure.
Every other chat is silently ignored. The bot is read-only over trading and never places
orders.

## 1. Create a bot with @BotFather
1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot`, then follow the prompts (give it a name and a username ending in `bot`).
3. BotFather replies with a **token** like `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
   That's your `TELEGRAM_TOKEN`.

## 2. Get your chat ID
1. Send any message to your new bot (tap Start / say "hi") so it has something to read.
2. Open in a browser (replace `<TOKEN>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Find `"chat":{"id":123456789,...}` in the JSON. That number is your `TELEGRAM_CHAT_ID`.
   (For a group, the id is negative — that's fine.)

## 3. Set the environment variables
In `~/Desktop/jarvis/.env`:
```
TELEGRAM_TOKEN=123456789:AAE...
TELEGRAM_CHAT_ID=123456789
```
Then restart JARVIS:
```bash
lsof -ti:8100 | xargs kill -9 2>/dev/null; bash scripts/start.sh
```
Startup logs will show `"telegram": "on"`.

## 4. Test it
- In Telegram, send `/start` → you should get a welcome message.
- Send any question → JARVIS replies (routed through the agent).
- `/reminders` → pending reminders; `/tasks` → your scheduled tasks.
- Schedule something due soon (`remind me in 1 minute to test telegram`) and confirm the
  push arrives.

## Notes
- One message per 3 seconds per user is enforced (extra messages are dropped).
- If Telegram is unreachable, the scheduler still runs — pushes just fail silently and are
  logged; reminders remain available via `/reminders` and `GET /reminders/pending`.
- `JARVIS_TELEGRAM_TOKEN` / `JARVIS_TELEGRAM_CHAT_ID` also work if you prefer the prefixed
  form used by the rest of the config.
