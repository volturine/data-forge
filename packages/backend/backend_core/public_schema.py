from core.database import get_settings_engine

from modules.auth.models import AuthProvider, User, UserSession, VerificationToken
from modules.chat.models import ChatSession


def ensure_backend_public_tables() -> None:
    table_names = {
        User.__tablename__,
        AuthProvider.__tablename__,
        UserSession.__tablename__,
        VerificationToken.__tablename__,
        ChatSession.__tablename__,
    }
    tables = [table for table in User.metadata.sorted_tables if table.name in table_names]
    if not tables:
        return
    User.metadata.create_all(get_settings_engine(), tables=tables)
