from contextlib import contextmanager
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base, BotAdmin, ReminderTemplate

settings = get_settings()

connect_args = {}
if settings.database_url.startswith('sqlite'):
    connect_args = {'check_same_thread': False}

engine = create_engine(settings.database_url, echo=False, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    seed_defaults()

@contextmanager
def db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          

def seed_defaults() -> None:
    with SessionLocal() as session:
        existing_template = session.execute(
            select(ReminderTemplate).where(ReminderTemplate.template_key == 'morning_payment_reminder')
        ).scalar_one_or_none()

        if existing_template is None:
            session.add(ReminderTemplate(
                template_key='morning_payment_reminder',
                message_text=settings.default_reminder_message,
                active=True,
            ))

        for user_id in settings.manager_telegram_ids:
            admin = session.execute(
                select(BotAdmin).where(BotAdmin.telegram_user_id == user_id)
            ).scalar_one_or_none()
            if admin is None:
                session.add(BotAdmin(
                    telegram_user_id=user_id,
                    name='env_manager',
                    role='manager',
                    active=True,
                ))

        session.commit()

