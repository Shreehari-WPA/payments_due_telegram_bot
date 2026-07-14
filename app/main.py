import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from app.config import get_settings
from app.database import init_db
from app.services import (
    VALID_CATEGORIES,
    add_manager,
    consume_confirmation,
    create_pending_confirmation,
    get_active_template,
    get_group_by_code,
    get_group_counts,
    get_groups,
    infer_category_from_group_code,
    is_authorized_manager,
    list_managers,
    normalize_category,
    remove_manager,
    send_broadcast,
    set_group_active,
    today_status,
    update_template,
    upsert_group,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
settings = get_settings()


async def ensure_manager(update: Update) -> bool:
    user = update.effective_user
    if not is_authorized_manager(user.id if user else None):
        if update.effective_message:
            await update.effective_message.reply_text('You are not authorized to use this command.')
        return False
    return True


def command_payload(update: Update) -> str:
    text = update.effective_message.text or ''
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ''


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        'Payment Reminder Broadcast Bot is running.\n\n'
        'Use /my_id to get your Telegram user ID.\n'
        'Managers can use /help to see commands.'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return
    await update.message.reply_text(
        'Manager Commands:\n\n'
        '/preview_reminder\n'
        '/send_reminder_all\n'
        '/send_reminder_b2b\n'
        '/send_reminder_b2c\n'
        '/send_reminder_powerplay\n'
        '/send_reminder_viking\n'
        '/send_custom <message>                        (all groups)\n'
        '/send_custom <category> <message>             (one category)\n'
        '/send_custom <group_code> <message>            (one group)\n'
        '/send_custom <code1,code2,...> <message>  (specific groups)\n'
        '/confirm_send <code>\n'
        '/cancel_send <code>\n'
        '/status_today\n'
        '/groups\n'
        '/pause_group <group_code>\n'
        '/resume_group <group_code>\n'
        '/set_template <message>\n\n'
        'Group setup command:\n'
        '/register <group_code> <category>\n\n'
        'Manager setup commands:\n'
        '/add_manager <telegram_user_id> [name]\n'
        '/remove_manager <telegram_user_id>\n'
        '/managers\n\n'
        'Categories: B2B, B2C, Powerplay, Viking'
    )


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f'Your Telegram user ID is:\n{user.id}\n\n'
        'Add this ID to MANAGER_TELEGRAM_IDS in .env if you should control broadcasts.'
    )


async def register_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return

    chat = update.effective_chat
    if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await update.message.reply_text('Use /register inside the Telegram group you want to register.')
        return

    if not context.args:
        await update.message.reply_text(
            'Use:\n/register <group_code> <category>\n\n'
            'Example:\n/register B2B_001 B2B'
        )
        return

    group_code = context.args[0].strip().upper()
    category = context.args[1].strip() if len(context.args) >= 2 else infer_category_from_group_code(group_code)
    if not category:
        await update.message.reply_text('Category missing. Use B2B, B2C, Powerplay, or Viking.')
        return

    try:
        group = upsert_group(
            group_code=group_code,
            category=category,
            group_name=chat.title,
            chat_id=chat.id,
        )
    except Exception as exc:
        logger.exception('Failed to register group')
        await update.message.reply_text(f'Failed to register group: {exc}')
        return

    await update.message.reply_text(
        'Group registered successfully.\n\n'
        f'Group Code: {group.group_code}\n'
        f'Category: {group.category}\n'
        f'Group Name: {group.group_name}\n'
        f'Telegram Chat ID: {group.telegram_chat_id}\n'
        f'Active: {group.active}'
    )


async def preview_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return

    message = get_active_template()
    counts = get_group_counts()
    counts_text = '\n'.join([f'{k}: {v}' for k, v in sorted(counts.items())]) or 'No active groups yet.'

    await update.message.reply_text(
        'Reminder Preview:\n\n'
        f'{message}\n\n'
        'Active Group Counts:\n'
        f'{counts_text}'
    )


def format_target_label(category: str | None, group_code: str | None) -> str:
    if group_code:
        codes = [c for c in group_code.split(',') if c]
        if len(codes) > 1:
            return f'{len(codes)} groups: {", ".join(codes)}'
        return f'Group {codes[0]}'
    return category or 'ALL categories'


async def ask_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    category: str | None,
    message_text: str | None = None,
    group_code: str | None = None,
) -> None:
    if not await ensure_manager(update):
        return

    user = update.effective_user
    message = message_text if message_text is not None else get_active_template()
    code, target_count = create_pending_confirmation(user.id, category, message, group_code=group_code)
    target_label = format_target_label(category, group_code)

    if target_count == 0:
        await update.message.reply_text(f'No active groups found for target: {target_label}')
        return

    await update.message.reply_text(
        'Reminder Preview:\n\n'
        f'{message}\n\n'
        f'Target: {target_label}\n'
        f'Active groups: {target_count}\n\n'
        f'Confirm sending with:\n/confirm_send {code}\n\n'
        f'Cancel with:\n/cancel_send {code}\n\n'
        'This confirmation expires in 10 minutes.'
    )


async def send_reminder_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ask_confirmation(update, context, None)


async def send_reminder_b2b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ask_confirmation(update, context, 'B2B')


async def send_reminder_b2c(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ask_confirmation(update, context, 'B2C')


async def send_reminder_powerplay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ask_confirmation(update, context, 'Powerplay')


async def send_reminder_viking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ask_confirmation(update, context, 'Viking')


async def send_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return

    raw_text = update.message.text or ''
    split = raw_text.split(maxsplit=1)
    remainder = split[1].strip() if len(split) > 1 else ''

    if not remainder:
        await update.message.reply_text(
            'Use:\n'
            '/send_custom <message>                        (sends to ALL active groups)\n'
            '/send_custom <category> <message>             (sends to one category)\n'
            '/send_custom <group_code> <message>            (sends to one group)\n'
            '/send_custom <code1,code2,...> <message>  (sends to specific groups)\n\n'
            'Examples:\n'
            '/send_custom Reminder: please clear your dues.\n'
            '/send_custom B2B Reminder for B2B groups only.\n'
            '/send_custom B2B_001 Reminder for this group only.\n'
            '/send_custom B2B_001,B2C_002 Reminder for these two groups only.\n\n'
            'Categories: B2B, B2C, Powerplay, Viking'
        )
        return

    first_token, _, rest = remainder.partition(' ')
    category: str | None = None
    group_code: str | None = None
    message_text: str

    if first_token.strip().lower() == 'all':
        message_text = rest.strip()
    elif normalize_category(first_token) in VALID_CATEGORIES.values():
        category = normalize_category(first_token)
        message_text = rest.strip()
    elif ',' in first_token:
        codes = list(dict.fromkeys(c.strip().upper() for c in first_token.split(',') if c.strip()))
        invalid_codes = [c for c in codes if get_group_by_code(c) is None]
        if invalid_codes:
            await update.message.reply_text(
                'Unknown group code(s): ' + ', '.join(invalid_codes) + '\n\nCheck /groups for valid codes.'
            )
            return
        group_code = ','.join(codes)
        message_text = rest.strip()
    elif get_group_by_code(first_token) is not None:
        group_code = first_token.strip().upper()
        message_text = rest.strip()
    else:
        # First word doesn't match a known target, so treat the whole text as the
        # message and default to sending it to all active groups.
        message_text = remainder

    if not message_text:
        await update.message.reply_text('Message text is required after the target.')
        return

    await ask_confirmation(update, context, category, message_text=message_text, group_code=group_code)


async def _send_and_report(
    application: Application,
    chat_id: int,
    category: str | None,
    message_text: str,
    sent_by: str,
    group_code: str | None = None,
) -> None:
    try:
        result = await send_broadcast(
            bot=application.bot,
            category=category,
            message_text=message_text,
            sent_by=sent_by,
            send_type='manual',
            group_code=group_code,
        )
        summary = (
            'Broadcast completed.\n\n'
            f'Batch ID: {result.batch_id}\n'
            f'Total: {result.total}\n'
            f'Sent: {result.sent}\n'
            f'Failed: {result.failed}'
        )
        if result.failures:
            failure_preview = '\n'.join(result.failures[:10])
            summary += f'\n\nFailures:\n{failure_preview}'
            if len(result.failures) > 10:
                summary += f'\n...and {len(result.failures) - 10} more.'
        await application.bot.send_message(chat_id=chat_id, text=summary)
    except Exception as exc:
        logger.exception('Manual broadcast failed')
        await application.bot.send_message(chat_id=chat_id, text=f'Broadcast failed: {exc}')


async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return

    if not context.args:
        await update.message.reply_text('Use: /confirm_send <code>')
        return

    user = update.effective_user
    code = context.args[0].strip()
    pending = consume_confirmation(user.id, code)
    if pending is None:
        await update.message.reply_text('Invalid, expired, or already-used confirmation code.')
        return

    target_label = format_target_label(pending.target_category, pending.target_group_code)
    await update.message.reply_text(f'Sending reminder to {target_label}. I will send you a summary after completion.')

    context.application.create_task(
        _send_and_report(
            application=context.application,
            chat_id=update.effective_chat.id,
            category=pending.target_category,
            message_text=pending.message_text,
            sent_by=str(user.id),
            group_code=pending.target_group_code,
        )
    )


async def cancel_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return
    # A new confirmation automatically invalidates old ones; this command is here for UX clarity.
    await update.message.reply_text('Send cancelled. Any unconfirmed pending send will expire automatically.')


async def status_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return
    status = today_status()
    counts = get_group_counts()

    status_text = '\n'.join([f'{k}: {v}' for k, v in sorted(status.items())]) or 'No sends logged today.'
    counts_text = '\n'.join([f'{k}: {v}' for k, v in sorted(counts.items())]) or 'No active groups.'

    await update.message.reply_text(
        'Today Send Status:\n'
        f'{status_text}\n\n'
        'Active Group Counts:\n'
        f'{counts_text}'
    )


async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return

    category = normalize_category(context.args[0]) if context.args else None
    groups = get_groups(category=category, active_only=False)
    if not groups:
        await update.message.reply_text('No groups registered yet.')
        return

    lines = ['Registered groups:\n']
    for group in groups[:80]:
        status = 'active' if group.active else 'paused'
        lines.append(f'{group.group_code} | {group.category} | {status} | {group.group_name}')

    if len(groups) > 80:
        lines.append(f'...and {len(groups) - 80} more.')

    await update.message.reply_text('\n'.join(lines))


async def pause_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return
    if not context.args:
        await update.message.reply_text('Use: /pause_group <group_code>')
        return
    code = context.args[0].strip().upper()
    ok = set_group_active(code, False)
    await update.message.reply_text(f'{code} paused.' if ok else f'Group not found: {code}')


async def resume_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return
    if not context.args:
        await update.message.reply_text('Use: /resume_group <group_code>')
        return
    code = context.args[0].strip().upper()
    ok = set_group_active(code, True)
    await update.message.reply_text(f'{code} resumed.' if ok else f'Group not found: {code}')


async def add_manager_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return

    if not context.args:
        await update.message.reply_text(
            'Use:\n/add_manager <telegram_user_id> [name]\n\n'
            'Ask the person to send /my_id to this bot to get their ID.'
        )
        return

    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('Telegram user ID must be numeric. Ask them to run /my_id.')
        return

    name = ' '.join(context.args[1:]).strip() or None
    admin = add_manager(new_id, name)
    await update.message.reply_text(
        f'Added manager: {admin.telegram_user_id}' + (f' ({admin.name})' if admin.name else '')
    )


async def remove_manager_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return

    if not context.args:
        await update.message.reply_text('Use: /remove_manager <telegram_user_id>')
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('Telegram user ID must be numeric.')
        return

    try:
        removed = remove_manager(target_id)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    await update.message.reply_text(
        f'Removed manager: {target_id}' if removed else 'That user is not currently an active manager.'
    )


async def list_managers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return

    managers = list_managers()
    if not managers:
        await update.message.reply_text('No active managers.')
        return

    lines = [f'{m.telegram_user_id}' + (f' - {m.name}' if m.name else '') for m in managers]
    await update.message.reply_text('Active managers:\n' + '\n'.join(lines))


async def set_template_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_manager(update):
        return

    payload = command_payload(update)
    if not payload:
        await update.message.reply_text(
            'Use:\n/set_template <message>\n\n'
            'Example:\n/set_template {greeting}, This is a gentle reminder regarding the pending payment settlement. Thank you.\n\n'
            'Tip: include {greeting} anywhere in the message and it will be replaced at send time — '
            '"Good morning" for the scheduled daily send, or a time-of-day greeting '
            '(Good morning/afternoon/evening) for anything you trigger manually.'
        )
        return

    try:
        update_template(payload)
    except Exception as exc:
        await update.message.reply_text(f'Failed to update template: {exc}')
        return

    await update.message.reply_text('Reminder template updated. Use /preview_reminder to check it.')


async def scheduled_daily_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    message = get_active_template()
    logger.info('Starting scheduled daily reminder broadcast')
    result = await send_broadcast(
        bot=context.bot,
        category=None,
        message_text=message,
        sent_by='scheduler',
        send_type='scheduled',
    )
    logger.info('Scheduled broadcast complete: %s', result)


def parse_daily_time(value: str) -> time:
    try:
        hour_str, minute_str = value.strip().split(':', maxsplit=1)
        return time(
            hour=int(hour_str),
            minute=int(minute_str),
            tzinfo=ZoneInfo(settings.timezone),
        )
    except Exception as exc:
        raise RuntimeError('DAILY_SEND_TIME must be in HH:MM format, e.g. 10:00') from exc


def build_application() -> Application:
    init_db()

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('my_id', my_id))
    application.add_handler(CommandHandler('register', register_group))

    application.add_handler(CommandHandler('preview_reminder', preview_reminder))
    application.add_handler(CommandHandler('send_reminder_all', send_reminder_all))
    application.add_handler(CommandHandler('send_reminder_b2b', send_reminder_b2b))
    application.add_handler(CommandHandler('send_reminder_b2c', send_reminder_b2c))
    application.add_handler(CommandHandler('send_reminder_powerplay', send_reminder_powerplay))
    application.add_handler(CommandHandler('send_reminder_viking', send_reminder_viking))
    application.add_handler(CommandHandler('send_custom', send_custom))
    application.add_handler(CommandHandler('confirm_send', confirm_send))
    application.add_handler(CommandHandler('cancel_send', cancel_send))
    application.add_handler(CommandHandler('status_today', status_today_command))
    application.add_handler(CommandHandler('groups', groups_command))
    application.add_handler(CommandHandler('pause_group', pause_group))
    application.add_handler(CommandHandler('resume_group', resume_group))
    application.add_handler(CommandHandler('set_template', set_template_command))
    application.add_handler(CommandHandler('add_manager', add_manager_command))
    application.add_handler(CommandHandler('remove_manager', remove_manager_command))
    application.add_handler(CommandHandler('managers', list_managers_command))

    scheduled_time = parse_daily_time(settings.daily_send_time)
    application.job_queue.run_daily(
        scheduled_daily_reminder,
        time=scheduled_time,
        name='daily_payment_reminder',
    )

    logger.info('Daily scheduled reminder configured at %s %s', settings.daily_send_time, settings.timezone)
    return application


def main() -> None:
    application = build_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
