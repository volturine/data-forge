import asyncio
import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from string import hexdigits
from typing import Any, cast

from core.config import settings
from core.database import namespace_connection
from core.namespace import list_namespaces
from core.smtp import send_smtp_message
from sqlalchemy import inspect, update
from sqlmodel import Session, select

from backend_core.auth_config import settings as auth_settings
from backend_core.auth_exceptions import (
    DefaultUserDeletionError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    OAuthError,
    ProviderUnlinkError,
    TokenExpiredError,
    TokenInvalidError,
)
from modules.auth.models import (
    AuthProvider,
    AuthProviderName,
    User,
    UserSession,
    UserStatus,
    VerificationToken,
    VerificationTokenType,
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


_PASSWORD_PROVIDER = AuthProviderName.PASSWORD
_PBKDF2_ALG = "sha256"
_PBKDF2_ITERATIONS = 200_000
_EMAIL_VERIFY = VerificationTokenType.EMAIL_VERIFY
_PASSWORD_RESET = VerificationTokenType.PASSWORD_RESET
_RESEND_COOLDOWN_MINUTES = 5
_DEFAULT_USER_ID = uuid.uuid5(uuid.NAMESPACE_URL, "data-forge-default-user").hex
_DEFAULT_USER_MARKER = "env_default_user"

logger = logging.getLogger(__name__)


def _clear_owned_resources(session: Session, user_id: str) -> None:
    from contracts.analysis.models import Analysis
    from contracts.datasource.models import DataSource
    from contracts.udf_models import Udf

    tables = set(inspect(session.get_bind()).get_table_names())
    ownership_models: dict[str, type[DataSource | Analysis | Udf]] = {
        "datasources": DataSource,
        "analyses": Analysis,
        "udfs": Udf,
    }
    for table_name, model in ownership_models.items():
        if table_name not in tables:
            continue
        owner_id_column = cast(Any, model.owner_id)
        session.exec(update(model).where(owner_id_column == user_id).values(owner_id=None))


def _clear_owned_resources_in_namespaces(user_id: str) -> None:
    namespaces = list_namespaces()
    if settings.default_namespace not in namespaces:
        namespaces = [*namespaces, settings.default_namespace]
    for namespace in namespaces:
        with (
            namespace_connection(namespace) as connection,
            Session(connection) as namespace_session,
        ):
            _clear_owned_resources(namespace_session, user_id)
            namespace_session.commit()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(_PBKDF2_ALG, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_{_PBKDF2_ALG}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    parts = hashed.split("$")
    if len(parts) != 4:
        return False
    scheme, rounds_raw, salt_hex, digest_hex = parts
    if scheme != f"pbkdf2_{_PBKDF2_ALG}":
        return False
    if not rounds_raw.isdigit():
        return False
    if len(salt_hex) % 2 != 0 or len(digest_hex) % 2 != 0:
        return False
    if any(ch not in hexdigits for ch in salt_hex):
        return False
    if any(ch not in hexdigits for ch in digest_hex):
        return False
    rounds = int(rounds_raw)
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac(_PBKDF2_ALG, password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not any(char.isupper() for char in password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(char.islower() for char in password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(char.isdigit() for char in password):
        raise ValueError("Password must contain at least one digit")


def _send_smtp_message(host: str, port: int, smtp_user: str, password: str, msg: EmailMessage) -> None:
    send_smtp_message(host, port, smtp_user, password, msg)


def _normalize_default_user_email(email: str) -> str:
    normalized = email.strip().lower()
    if normalized:
        return normalized
    return "default@example.com"


def _normalize_default_user_name(name: str, email: str) -> str:
    normalized = name.strip()
    if normalized:
        return normalized
    return email.split("@", maxsplit=1)[0]


def _get_password_provider(session: Session, user_id: str) -> AuthProvider | None:
    stmt = select(AuthProvider).where(AuthProvider.user_id == user_id, AuthProvider.provider == _PASSWORD_PROVIDER)
    return session.exec(stmt).first()


def _build_default_provider_metadata(password: str) -> dict[str, str]:
    return {
        "managed_by": _DEFAULT_USER_MARKER,
        "password_hash": hash_password(password),
    }


def get_default_user_id() -> str:
    return _DEFAULT_USER_ID


def get_default_user(session: Session) -> User | None:
    return get_user_by_id(session, _DEFAULT_USER_ID)


def ensure_default_user(session: Session) -> User:
    desired_email = _normalize_default_user_email(auth_settings.default_user_email)
    desired_name = _normalize_default_user_name(auth_settings.default_user_name, desired_email)
    desired_password = auth_settings.default_user_password
    now = _utcnow()
    user = get_default_user(session)
    changed = False

    if not user:
        email_owner = get_user_by_email(session, desired_email)
        if email_owner:
            raise EmailAlreadyExistsError()
        user = User(
            id=_DEFAULT_USER_ID,
            email=desired_email,
            display_name=desired_name,
            status=UserStatus.ACTIVE,
            email_verified=True,
            has_password=True,
            preferences={},
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(
            AuthProvider(
                id=uuid.uuid4().hex,
                user_id=user.id,
                provider=_PASSWORD_PROVIDER,
                provider_subject=user.email,
                provider_metadata=_build_default_provider_metadata(desired_password),
                created_at=now,
            ),
        )
        session.commit()
        return user

    if user.display_name != desired_name:
        user.display_name = desired_name
        changed = True
    if user.status != UserStatus.ACTIVE:
        user.status = UserStatus.ACTIVE
        changed = True
    if user.email_verified is not True:
        user.email_verified = True
        changed = True
    if user.has_password is not True:
        user.has_password = True
        changed = True

    email_owner = get_user_by_email(session, desired_email)
    email_available = not email_owner or email_owner.id == user.id
    if email_available and user.email != desired_email:
        user.email = desired_email
        changed = True
    if not email_available and user.email != desired_email:
        logger.warning(
            "Skipping default user email update to %s because another account already uses it",
            desired_email,
        )

    provider = _get_password_provider(session, user.id)
    password_changed = False
    if not provider:
        provider = AuthProvider(
            id=uuid.uuid4().hex,
            user_id=user.id,
            provider=_PASSWORD_PROVIDER,
            provider_subject=user.email,
            provider_metadata=_build_default_provider_metadata(desired_password),
            created_at=now,
        )
        session.add(provider)
        changed = True
        password_changed = True
    if provider:
        metadata = dict(provider.provider_metadata) if isinstance(provider.provider_metadata, dict) else {}
        hashed = metadata.get("password_hash")
        marker_changed = metadata.get("managed_by") != _DEFAULT_USER_MARKER
        subject_changed = provider.provider_subject != user.email
        if not isinstance(hashed, str) or not verify_password(desired_password, hashed):
            metadata["password_hash"] = hash_password(desired_password)
            password_changed = True
        if marker_changed:
            metadata["managed_by"] = _DEFAULT_USER_MARKER
        if subject_changed:
            provider.provider_subject = user.email
        provider.provider_metadata = metadata
        session.add(provider)
        if password_changed or marker_changed or subject_changed:
            changed = True

    if not changed:
        return user

    user.updated_at = now
    session.add(user)
    session.commit()
    if password_changed:
        revoke_all_sessions(session, user.id)
    session.refresh(user)
    return user


def create_user(
    session: Session,
    email: str,
    password: str,
    display_name: str,
    *,
    email_verified: bool = False,
) -> User:
    normalized_email = email.strip().lower()
    if get_user_by_email(session, normalized_email):
        raise EmailAlreadyExistsError()
    validate_password(password)
    now = _utcnow()
    user = User(
        id=uuid.uuid4().hex,
        email=normalized_email,
        display_name=display_name,
        status=UserStatus.ACTIVE,
        email_verified=email_verified,
        has_password=True,
        preferences={},
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()
    provider = AuthProvider(
        id=uuid.uuid4().hex,
        user_id=user.id,
        provider=_PASSWORD_PROVIDER,
        provider_subject=normalized_email,
        provider_metadata={"password_hash": hash_password(password)},
        created_at=now,
    )
    session.add(provider)
    session.commit()
    session.refresh(user)
    return user


def get_user_by_email(session: Session, email: str) -> User | None:
    normalized_email = email.strip().lower()
    stmt = select(User).where(User.email == normalized_email)
    return session.exec(stmt).first()


def get_user_by_id(session: Session, user_id: str) -> User | None:
    return session.get(User, user_id)


def get_user_providers(session: Session, user_id: str) -> list[AuthProviderName]:
    stmt = select(AuthProvider).where(AuthProvider.user_id == user_id)
    providers = session.exec(stmt).all()
    return [AuthProviderName(provider.provider) for provider in providers]


def delete_user_account(session: Session, user_id: str) -> None:
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    if user.id == _DEFAULT_USER_ID:
        raise DefaultUserDeletionError()

    _clear_owned_resources(session, user_id)
    _clear_owned_resources_in_namespaces(user_id)

    session.delete(user)
    session.commit()


def update_profile(
    session: Session,
    user_id: str,
    display_name: str | None,
    avatar_url: str | None,
    preferences: dict[str, object] | None,
) -> User:
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    if display_name is not None:
        user.display_name = display_name
    if avatar_url is not None:
        user.avatar_url = avatar_url
    if preferences is not None:
        user.preferences = preferences
    user.updated_at = _utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def change_password(session: Session, user_id: str, current_password: str, new_password: str) -> None:
    validate_password(new_password)
    stmt = select(AuthProvider).where(AuthProvider.user_id == user_id, AuthProvider.provider == _PASSWORD_PROVIDER)
    provider = session.exec(stmt).first()
    if not provider:
        raise InvalidCredentialsError()
    metadata = provider.provider_metadata or {}
    hashed = metadata.get("password_hash")
    if not isinstance(hashed, str):
        raise InvalidCredentialsError()
    if not verify_password(current_password, hashed):
        raise InvalidCredentialsError()
    provider.provider_metadata = {"password_hash": hash_password(new_password)}
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    user.has_password = True
    user.updated_at = _utcnow()
    session.add(provider)
    session.add(user)
    session.commit()


def create_session(session: Session, user_id: str, device_info: str | None, ip_address: str | None) -> UserSession:
    now = _utcnow()
    expires_at = now + timedelta(days=auth_settings.session_max_age_days)
    user_session = UserSession(
        id=uuid.uuid4().hex,
        user_id=user_id,
        device_info=device_info,
        ip_address=ip_address,
        created_at=now,
        expires_at=expires_at,
        revoked=False,
    )
    session.add(user_session)
    session.commit()
    session.refresh(user_session)
    return user_session


def validate_session(session: Session, session_id: str) -> User | None:
    user_session = session.get(UserSession, session_id)
    if not user_session:
        return None
    now = _utcnow()
    if user_session.revoked:
        return None
    if _naive_utc(user_session.expires_at) <= now:
        user_session.revoked = True
        session.add(user_session)
        session.commit()
        return None
    user = get_user_by_id(session, user_session.user_id)
    if not user:
        return None
    if user.status == UserStatus.DISABLED:
        return None
    user.last_login_at = now
    user.updated_at = now
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def revoke_session(session: Session, session_id: str) -> None:
    user_session = session.get(UserSession, session_id)
    if not user_session:
        return
    if user_session.revoked:
        return
    user_session.revoked = True
    session.add(user_session)
    session.commit()


def revoke_all_sessions(session: Session, user_id: str) -> None:
    stmt = select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked == False)  # type: ignore[arg-type]  # noqa: E712
    sessions = session.exec(stmt).all()
    if not sessions:
        return
    for item in sessions:
        item.revoked = True
        session.add(item)
    session.commit()


def link_provider(
    session: Session,
    user_id: str,
    provider: AuthProviderName,
    provider_subject: str,
    metadata: dict[str, object] | None,
) -> AuthProvider:
    existing = session.exec(
        select(AuthProvider).where(
            AuthProvider.provider == provider,
            AuthProvider.provider_subject == provider_subject,
        ),
    ).first()
    if existing:
        if existing.user_id != user_id:
            raise OAuthError("OAuth identity is already linked to another account")
        return existing
    now = _utcnow()
    linked = AuthProvider(
        id=uuid.uuid4().hex,
        user_id=user_id,
        provider=provider,
        provider_subject=provider_subject,
        provider_metadata=metadata,
        created_at=now,
    )
    session.add(linked)
    session.commit()
    session.refresh(linked)
    return linked


def find_or_create_oauth_user(
    session: Session,
    provider: AuthProviderName,
    provider_subject: str,
    email: str,
    display_name: str,
    avatar_url: str | None,
) -> User:
    provider_name = AuthProviderName.require(provider)
    normalized_email = email.strip().lower()
    existing = session.exec(
        select(AuthProvider).where(
            AuthProvider.provider == provider_name,
            AuthProvider.provider_subject == provider_subject,
        ),
    ).first()
    if existing:
        user = get_user_by_id(session, existing.user_id)
        if not user:
            raise OAuthError("OAuth identity points to a missing user")
        return user
    matched_email = get_user_by_email(session, normalized_email)
    if matched_email:
        link_provider(
            session=session,
            user_id=matched_email.id,
            provider=provider_name,
            provider_subject=provider_subject,
            metadata={"email": normalized_email, "avatar_url": avatar_url},
        )
        if not matched_email.avatar_url and avatar_url:
            matched_email.avatar_url = avatar_url
        if not matched_email.display_name and display_name:
            matched_email.display_name = display_name
        matched_email.updated_at = _utcnow()
        session.add(matched_email)
        session.commit()
        session.refresh(matched_email)
        return matched_email
    now = _utcnow()
    user = User(
        id=uuid.uuid4().hex,
        email=normalized_email,
        display_name=display_name or normalized_email.split("@")[0],
        avatar_url=avatar_url,
        status=UserStatus.ACTIVE,
        email_verified=True,
        has_password=False,
        preferences={},
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()
    provider_row = AuthProvider(
        id=uuid.uuid4().hex,
        user_id=user.id,
        provider=provider_name,
        provider_subject=provider_subject,
        provider_metadata={"email": normalized_email, "avatar_url": avatar_url},
        created_at=now,
    )
    session.add(provider_row)
    session.commit()
    session.refresh(user)
    return user


def unlink_provider(session: Session, user_id: str, provider: AuthProviderName) -> None:
    provider_name = AuthProviderName.require(provider)
    providers_stmt = select(AuthProvider).where(AuthProvider.user_id == user_id)
    providers = session.exec(providers_stmt).all()
    if len(providers) <= 1:
        raise ProviderUnlinkError()
    provider_row = next((row for row in providers if row.provider == provider_name), None)
    if not provider_row:
        return
    if provider_row.provider == _PASSWORD_PROVIDER:
        raise ProviderUnlinkError("Password login cannot be unlinked")
    user = get_user_by_id(session, user_id)
    if not user:
        raise ProviderUnlinkError("Cannot unlink provider for a missing account")
    session.delete(provider_row)
    has_password_provider = any(row.provider == _PASSWORD_PROVIDER and row.id != provider_row.id for row in providers)
    user.has_password = has_password_provider
    user.updated_at = _utcnow()
    session.add(user)
    session.commit()


def create_verification_token(
    session: Session,
    user_id: str,
    token_type: VerificationTokenType,
    ttl_hours: int = 24,
) -> str:
    token_type_value = VerificationTokenType.require(token_type)
    now = _utcnow()
    raw = secrets.token_urlsafe(32)
    token = VerificationToken(
        id=uuid.uuid4().hex,
        user_id=user_id,
        token=raw,
        token_type=token_type_value,
        created_at=now,
        expires_at=now + timedelta(hours=ttl_hours),
        used=False,
    )
    session.add(token)
    session.commit()
    return raw


def validate_verification_token(session: Session, token: str, token_type: VerificationTokenType) -> str:
    token_type_value = VerificationTokenType.require(token_type)
    stmt = select(VerificationToken).where(
        VerificationToken.token == token,
        VerificationToken.token_type == token_type_value,
    )
    row = session.exec(stmt).first()
    if not row:
        raise TokenInvalidError()
    if row.used:
        raise TokenInvalidError()
    now = _utcnow()
    if _naive_utc(row.expires_at) <= now:
        raise TokenExpiredError()
    row.used = True
    session.add(row)
    session.commit()
    return row.user_id


async def send_verification_email(user_email: str, token: str) -> bool:
    try:
        from backend_core.settings_store import get_resolved_smtp

        smtp = get_resolved_smtp()
    except Exception:
        logger.error("Failed to resolve SMTP config for verification email", exc_info=True)
        raise
    host = str(smtp.get("host", ""))
    port = int(str(smtp.get("port", 587)))
    smtp_user = str(smtp.get("user", ""))
    password = str(smtp.get("password", ""))

    if not host or not smtp_user:
        logger.debug("SMTP is not configured for verification email")
        return False

    verify_url = f"{auth_settings.auth_frontend_url}/verify?token={token}"
    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = user_email
    msg["Subject"] = "Verify your email"
    msg.set_content(f"Please verify your email by opening this link: {verify_url}")

    try:
        await asyncio.to_thread(_send_smtp_message, host, port, smtp_user, password, msg)
    except Exception:
        logger.error("Failed to send verification email", exc_info=True)
        raise
    return True


async def resend_verification(session: Session, user_id: str) -> bool:
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    if user.email_verified:
        return False

    stmt = select(VerificationToken).where(
        VerificationToken.user_id == user_id,
        VerificationToken.token_type == _EMAIL_VERIFY,
    )
    rows = session.exec(stmt).all()
    last = max(rows, key=lambda row: row.created_at) if rows else None
    if last:
        now = _utcnow()
        created_at = _naive_utc(last.created_at)
        if created_at + timedelta(minutes=_RESEND_COOLDOWN_MINUTES) > now:
            raise ValueError("Verification email was sent recently. Please wait before requesting again")

    token = create_verification_token(session, user_id=user_id, token_type=_EMAIL_VERIFY)
    return await send_verification_email(user.email, token)


def create_password_reset_token(session: Session, email: str) -> str | None:
    user = get_user_by_email(session, email)
    if not user:
        return None
    return create_verification_token(session, user_id=user.id, token_type=_PASSWORD_RESET, ttl_hours=1)


async def send_password_reset_email(user_email: str, token: str) -> bool:
    try:
        from backend_core.settings_store import get_resolved_smtp

        smtp = get_resolved_smtp()
    except Exception:
        logger.error("Failed to resolve SMTP config for password reset email", exc_info=True)
        raise
    host = str(smtp.get("host", ""))
    port = int(str(smtp.get("port", 587)))
    smtp_user = str(smtp.get("user", ""))
    password = str(smtp.get("password", ""))
    if not host or not smtp_user:
        logger.debug("SMTP is not configured for password reset email")
        return False
    reset_url = f"{auth_settings.auth_frontend_url}/reset-password?token={token}"
    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = user_email
    msg["Subject"] = "Reset your password"
    msg.set_content(f"Use this link to reset your password: {reset_url}")
    try:
        await asyncio.to_thread(_send_smtp_message, host, port, smtp_user, password, msg)
    except Exception:
        logger.error("Failed to send password reset email", exc_info=True)
        raise
    return True


def reset_password(session: Session, token: str, new_password: str) -> None:
    validate_password(new_password)
    stmt = select(VerificationToken).where(
        VerificationToken.token == token,
        VerificationToken.token_type == _PASSWORD_RESET,
    )
    row = session.exec(stmt).first()
    if not row:
        raise TokenInvalidError()
    if row.used:
        raise TokenInvalidError()
    now = _utcnow()
    if _naive_utc(row.expires_at) <= now:
        raise TokenExpiredError()
    user = get_user_by_id(session, row.user_id)
    if not user:
        raise TokenInvalidError()
    provider = session.exec(
        select(AuthProvider).where(AuthProvider.user_id == user.id, AuthProvider.provider == _PASSWORD_PROVIDER),
    ).first()
    if provider:
        provider.provider_metadata = {"password_hash": hash_password(new_password)}
        session.add(provider)
    if not provider:
        session.add(
            AuthProvider(
                id=uuid.uuid4().hex,
                user_id=user.id,
                provider=_PASSWORD_PROVIDER,
                provider_subject=user.email,
                provider_metadata={"password_hash": hash_password(new_password)},
                created_at=now,
            ),
        )
    user.has_password = True
    user.updated_at = now
    row.used = True
    session.add(user)
    session.add(row)
    revoke_all_sessions(session, user.id)
    session.commit()
