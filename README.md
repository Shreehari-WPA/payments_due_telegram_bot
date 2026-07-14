# Telegram Payment Reminder Broadcast Bot

Sends payment reminders to registered Telegram groups — either automatically every day at a
fixed time, or on-demand by a manager, with a confirmation step before anything goes out.

This bot does **not** process payments or integrate with any payment gateway. It only sends
templated or custom text reminders to Telegram groups.

## Features

- Register Telegram groups with a category and a group code
- Daily automatic reminder to all active groups at a fixed time
- Manual broadcast trigger from a manager's phone, gated by a confirmation step
- Category-wise sending: B2B, B2C, Powerplay, Viking
- One-off **custom** messages targeted at all groups, one category, or a single group
- Pause/resume individual groups
- Managers can be added/removed live, at runtime, by any existing manager (no redeploy needed)
- Full send log / audit trail (`/status_today`)
- SQLite by default, PostgreSQL supported

## Requirements

- Python 3.11+ (developed and tested on 3.14)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Docker + Docker Compose (optional, for containerized deployment)

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env with your own bot token / manager ID
python -m app.main
```

If `.env` is missing entirely, the bot still starts — `app/config.py` has hardcoded fallback
values for every setting (including a default token) so it never crashes on missing config.
Always prefer setting your own values in `.env` (or real environment variables) for anything
other than quick local testing; they override the hardcoded defaults automatically.

## Configuration

All settings are environment variables, loaded via `.env` (see `.env.example`) or real OS
environment variables. Environment variables always win over the hardcoded defaults in
`app/config.py`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes (has fallback) | baked-in default | Bot token from BotFather |
| `MANAGER_TELEGRAM_IDS` | Yes (has fallback) | baked-in default | Comma-separated Telegram user IDs seeded as managers on first run |
| `DATABASE_URL` | No | `sqlite:///reminder_bot.db` | SQLAlchemy DB URL. Use `postgresql+psycopg2://user:password@host:5432/dbname` for Postgres |
| `TIMEZONE` | No | `Asia/Dubai` | IANA timezone used for the daily send time |
| `DAILY_SEND_TIME` | No | `10:00` | `HH:MM` local time the automatic daily reminder fires |
| `SEND_DELAY_SECONDS` | No | `1.2` | Delay between individual group sends (rate-limit safety) |
| `DEFAULT_REMINDER_MESSAGE` | No | see `.env.example` | Seeded as the active template on first run only |

`MANAGER_TELEGRAM_IDS` only seeds managers on the **first** run (when the `bot_admins` table is
empty for that user). After that, manage who has access with `/add_manager` / `/remove_manager`
(see command reference below) instead of editing `.env` and restarting.

## Find your Telegram user ID

Open a private chat with the bot and send:

```text
/my_id
```

An existing manager then grants you access with `/add_manager <your_id> <your name>`.

## Register a group

Add the bot to the target Telegram group, then send inside that group:

```text
/register B2B_001 B2B
```

The category can be omitted if the code's prefix already implies it (`B2B*` → B2B, `B2C*` → B2C,
`PP*`/`POWERPLAY*` → Powerplay, `VK*`/`VIKING*` → Viking):

```text
/register B2C_001 B2C
/register PP_001 Powerplay
/register VK_001 Viking
```

## Command reference

All manager commands are used in a **private chat** with the bot (not inside a group), except
`/register`, which must be run **inside** the group being registered.

| Command | Who | Description |
|---|---|---|
| `/start` | anyone | Intro message |
| `/my_id` | anyone | Shows your Telegram user ID |
| `/help` | manager | Lists manager commands |
| `/register <group_code> <category>` | manager, in-group | Registers the current group |
| `/preview_reminder` | manager | Shows the current template + active group counts |
| `/send_reminder_all` | manager | Asks to confirm sending the template to all active groups |
| `/send_reminder_b2b` | manager | ...to B2B groups only |
| `/send_reminder_b2c` | manager | ...to B2C groups only |
| `/send_reminder_powerplay` | manager | ...to Powerplay groups only |
| `/send_reminder_viking` | manager | ...to Viking groups only |
| `/send_custom <message>` | manager | One-off custom message to **all** active groups |
| `/send_custom <category> <message>` | manager | One-off custom message to one **category** |
| `/send_custom <group_code> <message>` | manager | One-off custom message to a single **group** |
| `/send_custom <code1,code2,...> <message>` | manager | One-off custom message to a specific **list of groups** |
| `/confirm_send <code>` | manager | Confirms and fires a pending broadcast |
| `/cancel_send <code>` | manager | Cancels a pending broadcast |
| `/status_today` | manager | Today's send counts by status + active group counts |
| `/groups [category]` | manager | Lists registered groups (up to 80) |
| `/pause_group <group_code>` | manager | Deactivates a group (stops receiving broadcasts) |
| `/resume_group <group_code>` | manager | Reactivates a paused group |
| `/set_template <message>` | manager | Updates the saved daily reminder template |
| `/add_manager <telegram_user_id> [name]` | manager | Grants another user manager access |
| `/remove_manager <telegram_user_id>` | manager | Revokes manager access (refuses to remove the last manager) |
| `/managers` | manager | Lists currently active managers |

### `/send_custom` targeting rules

The first word after the command is checked in this order:

1. `all` → every active group
2. a known category (`B2B`, `B2C`, `Powerplay`, `Viking`) → that category only
3. contains a comma → treated as a list of group codes; if **any** code in the list doesn't
   exist, the whole command is rejected and the bot tells you which code(s) are invalid
4. an existing group code → that single group only
5. none of the above → the whole text is treated as the message, sent to **all** active groups

```text
/send_custom Reminder: please clear your dues.
/send_custom B2B Reminder for B2B groups only.
/send_custom B2B_001 Reminder for this group only.
/send_custom B2B_001,B2C_002 Reminder for these two groups only.
```

If your message must literally start with a word that happens to match a category name or a
registered group code, prefix it with `all` to avoid ambiguity.

### Edit the daily reminder template

```text
/set_template Good morning,

This is a gentle reminder regarding the pending payment settlement.

Kindly arrange the payment at your earliest convenience.

Thank you.
```

### Pause/resume a group

```text
/pause_group B2B_001
/resume_group B2B_001
```

## Testing

### Option A — test against a live/shared bot

Use this when someone just needs to confirm behavior on the bot you already have running.

1. Share the bot's Telegram username/link with them.
2. They DM the bot `/my_id` and send you the number.
3. You run `/add_manager <their_id> <their name>`.
4. If they need a group to test with, create a **throwaway** Telegram group, add the bot to it,
   and register it: `/register TEST_001 B2B` — don't use a real customer group for testing.

### Option B — run an independent copy (recommended for anyone testing broadcast behavior)

Safer: no risk to real groups, the real daily schedule, or the real send log.

1. Give them git access to this repo.
2. They create their **own** disposable bot via @BotFather (`/newbot`, a few seconds).
3. They copy `.env.example` to `.env` and set their own `TELEGRAM_BOT_TOKEN` and
   `MANAGER_TELEGRAM_IDS` (their own `/my_id` value).
4. `pip install -r requirements.txt && python -m app.main` (or `docker compose up --build`).

### Manual end-to-end smoke test

Run this after any change to the confirm/send pipeline:

1. `/register TEST_001 B2B` inside a throwaway test group.
2. `/send_reminder_b2b` (or `/send_custom B2B <message>` for a custom one) in a private chat
   with the bot.
3. Confirm the preview shows the right message and an active group count of at least 1.
4. Run `/confirm_send <code>` from the reply.
5. Confirm the test group actually receives the message.
6. Run `/status_today` and confirm the send shows up as `sent`.

## Docker

Build and run with Docker Compose (recommended — includes automatic restart on crash/reboot and
a persistent volume for the SQLite database):

```bash
cp .env.example .env   # edit with your real token/manager IDs first
docker compose up --build -d
docker compose logs -f
```

To stop:

```bash
docker compose down
```

The SQLite database lives in a named volume (`bot_data`) mounted at `/app/data` inside the
container, so it survives `docker compose down`/`up` and container recreation. To reset it
completely, remove the volume: `docker compose down -v`.

### Plain Docker (without Compose)

```bash
docker build -t payments-due-bot .
docker run -d --name payments-due-bot \
  --restart unless-stopped \
  --env-file .env \
  -v payments_due_bot_data:/app/data \
  payments-due-bot
```

## PostgreSQL

Change `DATABASE_URL` in `.env`:

```env
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/reminder_bot
```

Tables are created automatically on startup (`Base.metadata.create_all` — additive only, no
migration tooling). If you change model fields later on an existing database, you'll need to
alter the schema by hand.

## Production notes

- Always run the bot under something that restarts it automatically — Docker Compose with
  `restart: unless-stopped` (included above) or a `systemd` unit if running bare-metal. Running
  it in a plain foreground terminal means it stops the moment that session closes.
- There is no automated test suite. Changes to the broadcast/confirm flow should go through the
  manual smoke test above before being relied on for real sends.
- `app/config.py` ships with hardcoded fallback values (including a default bot token) so the
  app never crashes on missing configuration. Always override them with your own `.env` /
  environment variables for any deployment other than quick local testing.
