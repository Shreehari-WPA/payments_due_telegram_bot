# Telegram Reminder Broadcast Bot

Phase 1 MVP for sending a common payment reminder to all registered Telegram groups.

## Features

- Register Telegram groups with category and group code
- Send daily reminder to all active groups at a fixed time
- Manual manager trigger from Telegram mobile
- Category-wise sending: B2B, B2C, Powerplay, Viking
- Confirmation step before manual broadcast
- Pause/resume groups
- Send logs
- SQLite by default, PostgreSQL supported

## Setup

1. Create a bot using Telegram BotFather and copy the token.
2. Copy `.env.example` to `.env`.
3. Add your bot token in `.env`.
4. Start the bot locally.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

## Find your Telegram user ID

Open a private chat with the bot and send:

```text
/my_id
```

Add that ID to `MANAGER_TELEGRAM_IDS` in `.env`.

## Register groups

Add the bot to a Telegram group, then send:

```text
/register B2B_001 B2B
```

Examples:

```text
/register B2C_001 B2C
/register PP_001 Powerplay
/register VK_001 Viking
```

## Manager commands

Use these in private chat with the bot:

```text
/preview_reminder
/send_reminder_all
/send_reminder_b2b
/send_reminder_b2c
/send_reminder_powerplay
/send_reminder_viking
/status_today
```

The bot will show a preview and ask for confirmation before sending.

## Edit reminder message

Private chat with bot:

```text
/set_template Good morning,

This is a gentle reminder regarding the pending payment settlement.

Kindly arrange the payment at your earliest convenience.

Thank you.
```

## Pause/resume a group

```text
/pause_group B2B_001
/resume_group B2B_001
```

## PostgreSQL

Change `DATABASE_URL` in `.env`:

```env
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/reminder_bot
```

Then run the bot. Tables are created automatically on startup.
