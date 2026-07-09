import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select, update
from telegram import Bot
from telegram.error import TelegramError

from app.config import get_settings
from app.database import db_session
from app.models import BotAdmin, PendingConfirmation, ReminderTemplate, SendLog, TelegramGroup

settings = get_settings()

VALID_CATEGORIES = {
    'b2b': 'B2B',
    'b2c': 'B2C',
    'powerplay': 'Powerplay',
    'viking': 'Viking',
}


@dataclass
class BroadcastResult:
    total: int
    sent: int
    failed: int
    skipped: int
    batch_id: str
    failures: list[str]


def normalize_category(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip().lower()
    return VALID_CATEGORIES.get(key, value.strip())


def infer_category_from_group_code(group_code: str) -> str | None:
    code = group_code.upper()
    if code.startswith('B2B'):
        return 'B2B'
    if code.startswith('B2C'):
        return 'B2C'
    if code.startswith('PP') or code.startswith('POWERPLAY'):
        return 'Powerplay'
    if code.startswith('VK') or code.startswith('VIKING'):
        return 'Viking'
    return None


def is_authorized_manager(user_id: int | None) -> bool:
    if user_id is None:
        return False
    with db_session() as session:
        admin = session.execute(
            select(BotAdmin).where(
                BotAdmin.telegram_user_id == user_id,
                BotAdmin.active.is_(True),
            )
        ).scalar_one_or_none()
        return admin is not None


def get_active_template() -> str:
    with db_session() as session:
        template = session.execute(
            select(ReminderTemplate).where(
                ReminderTemplate.template_key == 'morning_payment_reminder',
                ReminderTemplate.active.is_(True),
            )
        ).scalar_one_or_none()
        if template is None:
            raise RuntimeError('No active reminder template found.')
        return template.message_text


def update_template(message_text: str) -> None:
    message_text = message_text.strip()
    if not message_text:
        raise ValueError('Template message cannot be empty.')
    with db_session() as session:
        template = session.execute(
            select(ReminderTemplate).where(ReminderTemplate.template_key == 'morning_payment_reminder')
        ).scalar_one_or_none()
        if template is None:
            session.add(ReminderTemplate(
                template_key='morning_payment_reminder',
                message_text=message_text,
                active=True,
            ))
        else:
            template.message_text = message_text
            template.active = True


def upsert_group(group_code: str, category: str, group_name: str | None, chat_id: int) -> TelegramGroup:
    group_code = group_code.strip().upper()
    category = normalize_category(category) or infer_category_from_group_code(group_code)
    if not category:
        raise ValueError('Category is required. Use B2B, B2C, Powerplay, or Viking.')

    with db_session() as session:
        existing_by_code = session.execute(
            select(TelegramGroup).where(TelegramGroup.group_code == group_code)
        ).scalar_one_or_none()

        existing_by_chat = session.execute(
            select(TelegramGroup).where(TelegramGroup.telegram_chat_id == chat_id)
        ).scalar_one_or_none()

        group = existing_by_code or existing_by_chat
        if group is None:
            group = TelegramGroup(
                group_code=group_code,
                category=category,
                group_name=group_name,
                telegram_chat_id=chat_id,
                active=True,
            )
            session.add(group)
            session.flush()
        else:
            group.group_code = group_code
            group.category = category
            group.group_name = group_name
            group.telegram_chat_id = chat_id
            group.active = True

        session.expunge(group)
        return group


def set_group_active(group_code: str, active: bool) -> bool:
    with db_session() as session:
        group = session.execute(
            select(TelegramGroup).where(TelegramGroup.group_code == group_code.strip().upper())
        ).scalar_one_or_none()
        if group is None:
            return False
        group.active = active
        return True


def get_group_counts() -> dict[str, int]:
    with db_session() as session:
        rows = session.execute(
            select(TelegramGroup.category, func.count(TelegramGroup.id))
            .where(TelegramGroup.active.is_(True))
            .group_by(TelegramGroup.category)
        ).all()
        counts = {category: count for category, count in rows}
        counts['ALL'] = sum(counts.values())
        return counts


def get_groups(
    category: str | None = None,
    group_code: str | None = None,
    active_only: bool = True,
) -> list[TelegramGroup]:
    category = normalize_category(category)
    with db_session() as session:
        query = select(TelegramGroup)
        if active_only:
            query = query.where(TelegramGroup.active.is_(True))
        if category:
            query = query.where(func.lower(TelegramGroup.category) == category.lower())
        if group_code:
            query = query.where(TelegramGroup.group_code == group_code.strip().upper())
        query = query.order_by(TelegramGroup.category, TelegramGroup.group_code)
        groups = list(session.execute(query).scalars().all())
        for group in groups:
            session.expunge(group)
        return groups


def get_group_by_code(group_code: str) -> TelegramGroup | None:
    with db_session() as session:
        group = session.execute(
            select(TelegramGroup).where(TelegramGroup.group_code == group_code.strip().upper())
        ).scalar_one_or_none()
        if group is not None:
            session.expunge(group)
        return group


def create_pending_confirmation(
    user_id: int,
    category: str | None,
    message_text: str,
    group_code: str | None = None,
) -> tuple[str, int]:
    code = str(secrets.randbelow(9000) + 1000)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)
    normalized_group_code = group_code.strip().upper() if group_code else None
    with db_session() as session:
        # Clear old unused confirmations for this user.
        session.execute(
            update(PendingConfirmation)
            .where(PendingConfirmation.telegram_user_id == user_id, PendingConfirmation.used.is_(False))
            .values(used=True)
        )
        pending = PendingConfirmation(
            telegram_user_id=user_id,
            confirmation_code=code,
            target_category=normalize_category(category),
            target_group_code=normalized_group_code,
            message_text=message_text,
            expires_at=expires_at,
            used=False,
        )
        session.add(pending)
    count = len(get_groups(category=category, group_code=normalized_group_code, active_only=True))
    return code, count


def consume_confirmation(user_id: int, code: str) -> PendingConfirmation | None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with db_session() as session:
        pending = session.execute(
            select(PendingConfirmation).where(
                PendingConfirmation.telegram_user_id == user_id,
                PendingConfirmation.confirmation_code == code.strip(),
                PendingConfirmation.used.is_(False),
                PendingConfirmation.expires_at >= now,
            )
        ).scalar_one_or_none()
        if pending is None:
            return None
        pending.used = True
        session.flush()
        session.expunge(pending)
        return pending


def save_log(
    *,
    batch_id: str,
    send_type: str,
    category: str | None,
    group_code: str | None,
    telegram_chat_id: int | None,
    message_text: str,
    sent_by: str,
    status: str,
    error: str | None = None,
    telegram_message_id: int | None = None,
) -> None:
    with db_session() as session:
        session.add(SendLog(
            send_batch_id=batch_id,
            send_type=send_type,
            category=category,
            group_code=group_code,
            telegram_chat_id=telegram_chat_id,
            message_text=message_text,
            sent_by=sent_by,
            status=status,
            error=error,
            telegram_message_id=telegram_message_id,
        ))


async def send_broadcast(
    *,
    bot: Bot,
    category: str | None,
    message_text: str,
    sent_by: str,
    send_type: str,
    group_code: str | None = None,
) -> BroadcastResult:
    groups = get_groups(category=category, group_code=group_code, active_only=True)
    batch_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
    sent = 0
    failed = 0
    skipped = 0
    failures: list[str] = []

    if not groups:
        return BroadcastResult(total=0, sent=0, failed=0, skipped=0, batch_id=batch_id, failures=[])

    for group in groups:
        try:
            result = await bot.send_message(
                chat_id=group.telegram_chat_id,
                text=message_text,
                disable_web_page_preview=True,
            )
            sent += 1
            save_log(
                batch_id=batch_id,
                send_type=send_type,
                category=group.category,
                group_code=group.group_code,
                telegram_chat_id=group.telegram_chat_id,
                message_text=message_text,
                sent_by=sent_by,
                status='sent',
                telegram_message_id=result.message_id,
            )
        except TelegramError as exc:
            failed += 1
            error = str(exc)
            failures.append(f"{group.group_code}: {error}")
            save_log(
                batch_id=batch_id,
                send_type=send_type,
                category=group.category,
                group_code=group.group_code,
                telegram_chat_id=group.telegram_chat_id,
                message_text=message_text,
                sent_by=sent_by,
                status='failed',
                error=error,
            )
        except Exception as exc:
            failed += 1
            error = str(exc)
            failures.append(f"{group.group_code}: {error}")
            save_log(
                batch_id=batch_id,
                send_type=send_type,
                category=group.category,
                group_code=group.group_code,
                telegram_chat_id=group.telegram_chat_id,
                message_text=message_text,
                sent_by=sent_by,
                status='failed',
                error=error,
            )

        await asyncio.sleep(settings.send_delay_seconds)

    return BroadcastResult(
        total=len(groups),
        sent=sent,
        failed=failed,
        skipped=skipped,
        batch_id=batch_id,
        failures=failures,
    )


def today_status() -> dict[str, int]:
    today = datetime.utcnow().date()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time())
    with db_session() as session:
        rows = session.execute(
            select(SendLog.status, func.count(SendLog.id))
            .where(SendLog.sent_at >= start, SendLog.sent_at <= end)
            .group_by(SendLog.status)
        ).all()
        return {status: count for status, count in rows}
