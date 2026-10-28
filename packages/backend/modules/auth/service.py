import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage
from string import hexdigits
from typing import Any, cast

from sqlalchemy import inspect, text, update
from sqlmodel import Session, select

from backend_core.api_execution_budget import run_api_blocking
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
from backend_core.database import namespace_connection, run_settings_db
from backend_core.namespaces_service import list_runtime_namespaces
from backend_core.smtp import send_smtp_message
from backend_core.sqlmodel_typing import col, sa
from backend_core.time import naive_utc, naive_utc_now as _utcnow
from backend_core.transactions import committed
from modules.auth.models import (
    AuthProvider,
    AuthProviderName,
    User,
    UserSession,
    UserStatus,
    VerificationToken,
    VerificationTokenType,
)

_PBKDF2_ALG = 'sha256'
_PBKDF2_ITERATIONS = 200_000
_RESEND_COOLDOWN_MINUTES = 5
_DEFAULT_USER_ID = uuid.uuid5(uuid.NAMESPACE_URL, 'data-forge-default-user').hex
_DEFAULT_USER_MARKER = 'env_default_user'
_DEFAULT_USER_LOCK_ID = 0x4446474555534552

logger = logging.getLogger(__name__)


def _acquire_default_user_lock(session: Session) -> bool:
    if session.get_bind().dialect.name != 'postgresql':
        return False
    session.execute(text('SELECT pg_advisory_xact_lock(:lock_id)'), {'lock_id': _DEFAULT_USER_LOCK_ID})
    return True


def _clear_owned_resources(session: Session, user_id: str) -> None:
    from backend_core.persistence.analysis.models import Analysis
    from backend_core.persistence.datasource.models import DataSource
    from backend_core.persistence.udfs.models import Udf

    tables = set(inspect(session.get_bind()).get_table_names())
    ownership_models: dict[str, type[DataSource | Analysis | Udf]] = {
        'datasources': DataSource,
        'analyses': Analysis,
        'udfs': Udf,
    }
    for table_name, model in ownership_models.items():
        if table_name not in tables:
            continue
        owner_id_column = cast(Any, model.owner_id)
        session.exec(update(model).where(owner_id_column == user_id).values(owner_id=None))


def _clear_owned_resources_in_namespaces(user_id: str) -> None:
    # The registry already includes the default namespace.
    namespaces = run_settings_db(list_runtime_namespaces)
    for namespace in namespaces:
        with (
            namespace_connection(namespace) as connection,
            Session(connection) as namespace_session,
        ):
            _clear_owned_resources(namespace_session, user_id)
            namespace_session.commit()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(_PBKDF2_ALG, password.encode('utf-8'), salt, _PBKDF2_ITERATIONS)
    return f'pbkdf2_{_PBKDF2_ALG}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}'


def verify_password(password: str, hashed: str) -> bool:
    parts = hashed.split('$')
    if len(parts) != 4:
        return False
    scheme, rounds_raw, salt_hex, digest_hex = parts
    if scheme != f'pbkdf2_{_PBKDF2_ALG}':
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
    actual = hashlib.pbkdf2_hmac(_PBKDF2_ALG, password.encode('utf-8'), salt, rounds)
    return hmac.compare_digest(actual, expected)


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError('Password must be at least 8 characters long')
    if not any(char.isupper() for char in password):
        raise ValueError('Password must contain at least one uppercase letter')
    if not any(char.islower() for char in password):
        raise ValueError('Password must contain at least one lowercase letter')
    if not any(char.isdigit() for char in password):
        raise ValueError('Password must contain at least one digit')


def get_password_provider(session: Session, user_id: str) -> AuthProvider | None:
    stmt = select(AuthProvider).where(sa(AuthProvider.user_id == user_id), sa(AuthProvider.provider == AuthProviderName.PASSWORD))
    return session.exec(stmt).first()


def provider_password_matches(provider: AuthProvider, password: str) -> bool:
    hashed = (provider.provider_metadata or {}).get('password_hash')
    return isinstance(hashed, str) and verify_password(password, hashed)


def _new_password_provider(user: User, provider_metadata: dict[str, object], created_at: datetime) -> AuthProvider:
    return AuthProvider(
        id=uuid.uuid4().hex,
        user_id=user.id,
        provider=AuthProviderName.PASSWORD,
        provider_subject=user.email,
        provider_metadata=provider_metadata,
        created_at=created_at,
    )


def _build_default_provider_metadata(password: str) -> dict[str, object]:
    return {
        'managed_by': _DEFAULT_USER_MARKER,
        'password_hash': hash_password(password),
    }


def get_default_user_id() -> str:
    return _DEFAULT_USER_ID


def stage_ensure_default_user(session: Session) -> User:
    _acquire_default_user_lock(session)
    desired_email = auth_settings.default_user_email.strip().lower() or 'default@example.com'
    desired_name = auth_settings.default_user_name.strip() or desired_email.split('@', maxsplit=1)[0]
    desired_password = auth_settings.default_user_password
    now = _utcnow()
    user = get_user_by_id(session, _DEFAULT_USER_ID)
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
        session.flush()
        session.add(_new_password_provider(user, _build_default_provider_metadata(desired_password), now))
        session.flush()
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
            'Skipping default user email update to %s because another account already uses it',
            desired_email,
        )

    provider = get_password_provider(session, user.id)
    password_changed = False
    if not provider:
        session.add(_new_password_provider(user, _build_default_provider_metadata(desired_password), now))
        changed = True
        password_changed = True
    else:
        metadata = dict(provider.provider_metadata or {})
        marker_changed = metadata.get('managed_by') != _DEFAULT_USER_MARKER
        subject_changed = provider.provider_subject != user.email
        if not provider_password_matches(provider, desired_password):
            metadata['password_hash'] = hash_password(desired_password)
            password_changed = True
        if marker_changed:
            metadata['managed_by'] = _DEFAULT_USER_MARKER
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
    session.flush()
    if password_changed:
        stage_revoke_all_sessions(session, user.id)
    return user


ensure_default_user = committed(stage_ensure_default_user, refresh=True)


def stage_create_user(
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
    session.add(_new_password_provider(user, {'password_hash': hash_password(password)}, now))
    session.flush()
    return user


def get_user_by_email(session: Session, email: str) -> User | None:
    normalized_email = email.strip().lower()
    stmt = select(User).where(sa(User.email == normalized_email))
    return session.exec(stmt).first()


def get_user_by_id(session: Session, user_id: str) -> User | None:
    return session.get(User, user_id)


def get_user_providers(session: Session, user_id: str) -> list[AuthProviderName]:
    stmt = select(AuthProvider).where(sa(AuthProvider.user_id == user_id))
    providers = session.exec(stmt).all()
    return [AuthProviderName(provider.provider) for provider in providers]


def stage_delete_user_account(session: Session, user_id: str) -> None:
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    if user.id == _DEFAULT_USER_ID:
        raise DefaultUserDeletionError()

    _clear_owned_resources(session, user_id)
    _clear_owned_resources_in_namespaces(user_id)

    session.delete(user)


def stage_update_profile(
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
    session.flush()
    return user


def stage_change_password(session: Session, user_id: str, current_password: str, new_password: str) -> None:
    validate_password(new_password)
    provider = get_password_provider(session, user_id)
    if not provider:
        raise InvalidCredentialsError()
    if not provider_password_matches(provider, current_password):
        raise InvalidCredentialsError()
    provider.provider_metadata = {'password_hash': hash_password(new_password)}
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    user.has_password = True
    user.updated_at = _utcnow()
    session.add(provider)
    session.add(user)


def stage_create_session(session: Session, user_id: str, device_info: str | None, ip_address: str | None) -> UserSession:
    now = _utcnow()
    expires_at = now + timedelta(days=auth_settings.session_max_age_days)
    user = get_user_by_id(session, user_id)
    if user is not None:
        # Session validation is on the hot path for every browser request and
        # must remain read-only. Record the login timestamp when the session is
        # created instead of taking the user's row lock on every /auth/me.
        user.last_login_at = now
        user.updated_at = now
        session.add(user)
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
    session.flush()
    return user_session


def validate_session(session: Session, session_id: str) -> User | None:
    row = session.exec(select(UserSession, User).join(User, sa(User.id == UserSession.user_id)).where(sa(UserSession.id == session_id))).first()
    if row is None:
        return None
    user_session, user = row
    now = _utcnow()
    if user_session.revoked:
        return None
    if naive_utc(user_session.expires_at) <= now:
        user_session.revoked = True
        session.add(user_session)
        # Expiry is the one exceptional write on this path. Valid session
        # validation must remain a read-only transaction because every browser
        # navigation performs it.
        session.commit()
        return None
    if user.status == UserStatus.DISABLED:
        return None
    return user


def stage_revoke_session(session: Session, session_id: str) -> None:
    user_session = session.get(UserSession, session_id)
    if not user_session or user_session.revoked:
        return
    user_session.revoked = True
    session.add(user_session)


def stage_revoke_all_sessions(session: Session, user_id: str) -> None:
    stmt = select(UserSession).where(sa(UserSession.user_id == user_id), col(UserSession.revoked).is_(False))
    for item in session.exec(stmt).all():
        item.revoked = True
        session.add(item)


def stage_link_provider(
    session: Session,
    user_id: str,
    provider: AuthProviderName,
    provider_subject: str,
    metadata: dict[str, object] | None,
) -> AuthProvider:
    existing = session.exec(
        select(AuthProvider).where(
            sa(AuthProvider.provider == provider),
            sa(AuthProvider.provider_subject == provider_subject),
        ),
    ).first()
    if existing:
        if existing.user_id != user_id:
            raise OAuthError('OAuth identity is already linked to another account')
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
    session.flush()
    return linked


def stage_find_or_create_oauth_user(
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
            sa(AuthProvider.provider == provider_name),
            sa(AuthProvider.provider_subject == provider_subject),
        ),
    ).first()
    if existing:
        user = get_user_by_id(session, existing.user_id)
        if not user:
            raise OAuthError('OAuth identity points to a missing user')
        return user
    matched_email = get_user_by_email(session, normalized_email)
    if matched_email:
        stage_link_provider(
            session=session,
            user_id=matched_email.id,
            provider=provider_name,
            provider_subject=provider_subject,
            metadata={'email': normalized_email, 'avatar_url': avatar_url},
        )
        if not matched_email.avatar_url and avatar_url:
            matched_email.avatar_url = avatar_url
        if not matched_email.display_name and display_name:
            matched_email.display_name = display_name
        matched_email.updated_at = _utcnow()
        session.add(matched_email)
        session.flush()
        return matched_email
    now = _utcnow()
    user = User(
        id=uuid.uuid4().hex,
        email=normalized_email,
        display_name=display_name or normalized_email.split('@')[0],
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
        provider_metadata={'email': normalized_email, 'avatar_url': avatar_url},
        created_at=now,
    )
    session.add(provider_row)
    session.flush()
    return user


def stage_unlink_provider(session: Session, user_id: str, provider: AuthProviderName) -> None:
    provider_name = AuthProviderName.require(provider)
    providers_stmt = select(AuthProvider).where(sa(AuthProvider.user_id == user_id))
    providers = session.exec(providers_stmt).all()
    if len(providers) <= 1:
        raise ProviderUnlinkError()
    provider_row = next((row for row in providers if row.provider == provider_name), None)
    if not provider_row:
        return
    if provider_row.provider == AuthProviderName.PASSWORD:
        raise ProviderUnlinkError('Password login cannot be unlinked')
    user = get_user_by_id(session, user_id)
    if not user:
        raise ProviderUnlinkError('Cannot unlink provider for a missing account')
    session.delete(provider_row)
    has_password_provider = any(row.provider == AuthProviderName.PASSWORD and row.id != provider_row.id for row in providers)
    user.has_password = has_password_provider
    user.updated_at = _utcnow()
    session.add(user)


def stage_create_verification_token(
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
    session.flush()
    return raw


def stage_validate_verification_token(session: Session, token: str, token_type: VerificationTokenType) -> str:
    token_type_value = VerificationTokenType.require(token_type)
    stmt = select(VerificationToken).where(
        sa(VerificationToken.token == token),
        sa(VerificationToken.token_type == token_type_value),
    )
    row = session.exec(stmt).first()
    if not row or row.used:
        raise TokenInvalidError()
    if naive_utc(row.expires_at) <= _utcnow():
        raise TokenExpiredError()
    row.used = True
    session.add(row)
    session.flush()
    return row.user_id


async def send_auth_email(user_email: str, subject: str, content: str) -> bool:
    """Send an account email; return False when SMTP is not configured."""
    from backend_core.settings_projection import get_resolved_smtp

    smtp = await run_api_blocking(get_resolved_smtp)
    if not smtp.host or not smtp.user:
        logger.debug('SMTP is not configured for %r email', subject)
        return False
    msg = EmailMessage()
    msg['From'] = smtp.user
    msg['To'] = user_email
    msg['Subject'] = subject
    msg.set_content(content)
    await run_api_blocking(send_smtp_message, smtp.host, smtp.port, smtp.user, smtp.password, msg)
    return True


def stage_prepare_resend_verification(session: Session, user_id: str) -> tuple[str, str] | None:
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    if user.email_verified:
        return None

    stmt = select(VerificationToken).where(
        sa(VerificationToken.user_id == user_id),
        sa(VerificationToken.token_type == VerificationTokenType.EMAIL_VERIFY),
    )
    rows = session.exec(stmt).all()
    last = max(rows, key=lambda row: row.created_at) if rows else None
    if last:
        now = _utcnow()
        created_at = naive_utc(last.created_at)
        if created_at + timedelta(minutes=_RESEND_COOLDOWN_MINUTES) > now:
            raise ValueError('Verification email was sent recently. Please wait before requesting again')

    token = stage_create_verification_token(session, user_id=user_id, token_type=VerificationTokenType.EMAIL_VERIFY)
    return user.email, token


def stage_create_password_reset_token(session: Session, email: str) -> str | None:
    user = get_user_by_email(session, email)
    if not user:
        return None
    return stage_create_verification_token(session, user_id=user.id, token_type=VerificationTokenType.PASSWORD_RESET, ttl_hours=1)


def stage_reset_password(session: Session, token: str, new_password: str) -> None:
    validate_password(new_password)
    user = get_user_by_id(session, stage_validate_verification_token(session, token=token, token_type=VerificationTokenType.PASSWORD_RESET))
    if not user:
        raise TokenInvalidError()
    now = _utcnow()
    provider = get_password_provider(session, user.id)
    if provider:
        provider.provider_metadata = {'password_hash': hash_password(new_password)}
        session.add(provider)
    else:
        session.add(_new_password_provider(user, {'password_hash': hash_password(new_password)}, now))
    user.has_password = True
    user.updated_at = now
    session.add(user)
    stage_revoke_all_sessions(session, user.id)
