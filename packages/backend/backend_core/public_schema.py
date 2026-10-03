from backend_core.database import run_settings_connection_locked
from backend_core.persistence.telegram.models import TelegramDetectionRequest, TelegramPollOffset
from modules.auth.models import AuthProvider, User, UserSession, VerificationToken
from modules.chat.models import ChatEvent, ChatMessage, ChatSession, ChatTurn


def ensure_backend_public_tables() -> None:
    table_names = {
        User.__tablename__,
        AuthProvider.__tablename__,
        UserSession.__tablename__,
        VerificationToken.__tablename__,
        ChatSession.__tablename__,
        ChatTurn.__tablename__,
        ChatMessage.__tablename__,
        ChatEvent.__tablename__,
        TelegramPollOffset.__tablename__,
        TelegramDetectionRequest.__tablename__,
    }
    tables = [table for table in User.metadata.sorted_tables if table.name in table_names]
    if not tables:
        return
    run_settings_connection_locked(lambda connection: User.metadata.create_all(connection, tables=tables))
