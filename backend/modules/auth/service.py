import hashlib
import hmac
import logging
import os
import secrets
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from string import hexdigits

from sqlmodel import Session, select

from core.config import settings
from core.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    OAuthError,
    ProviderUnlinkError,
    TokenExpiredError,
    TokenInvalidError,
)
from modules.auth.models import AuthProvider, User, UserSession, VerificationToken

_PASSWORD_PROVIDER = 'password'
_PBKDF2_ALG = 'sha256'
_PBKDF2_ITERATIONS = 200_000
_EMAIL_VERIFY = 'email_verify'
_PASSWORD_RESET = 'password_reset'
_RESEND_COOLDOWN_MINUTES = 5

logger = logging.getLogger(__name__)


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
    if len(password) >= 8:
        return
    raise ValueError('Password must be at least 8 characters long')


def create_user(session: Session, email: str, password: str, display_name: str) -> User:
    normalized_email = email.strip().lower()
    if get_user_by_email(session, normalized_email):
        raise EmailAlreadyExistsError()
    validate_password(password)
    now = datetime.now(UTC)
    user = User(
        id=uuid.uuid4().hex,
        email=normalized_email,
        display_name=display_name,
        status='active',
        email_verified=False,
        has_password=True,
        preferences={},
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    provider = AuthProvider(
        id=uuid.uuid4().hex,
        user_id=user.id,
        provider=_PASSWORD_PROVIDER,
        provider_subject=normalized_email,
        provider_metadata={'password_hash': hash_password(password)},
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


def get_user_providers(session: Session, user_id: str) -> list[str]:
    stmt = select(AuthProvider).where(AuthProvider.user_id == user_id)
    providers = session.exec(stmt).all()
    return [provider.provider for provider in providers]


def update_profile(
    session: Session,
    user_id: str,
    display_name: str | None,
    avatar_url: str | None,
    preferences: dict | None,
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
    user.updated_at = datetime.now(UTC)
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
    hashed = metadata.get('password_hash')
    if not isinstance(hashed, str):
        raise InvalidCredentialsError()
    if not verify_password(current_password, hashed):
        raise InvalidCredentialsError()
    provider.provider_metadata = {'password_hash': hash_password(new_password)}
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    user.has_password = True
    user.updated_at = datetime.now(UTC)
    session.add(provider)
    session.add(user)
    session.commit()


def create_session(session: Session, user_id: str, device_info: str | None, ip_address: str | None) -> UserSession:
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.session_max_age_days)
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
    now = datetime.now(UTC)
    if user_session.revoked:
        return None
    if user_session.expires_at <= now:
        user_session.revoked = True
        session.add(user_session)
        session.commit()
        return None
    user = get_user_by_id(session, user_session.user_id)
    if not user:
        return None
    if user.status == 'disabled':
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
    provider: str,
    provider_subject: str,
    metadata: dict | None,
) -> AuthProvider:
    existing = session.exec(
        select(AuthProvider).where(
            AuthProvider.provider == provider,
            AuthProvider.provider_subject == provider_subject,
        )
    ).first()
    if existing:
        if existing.user_id != user_id:
            raise OAuthError('OAuth identity is already linked to another account')
        return existing
    now = datetime.now(UTC)
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
    provider: str,
    provider_subject: str,
    email: str,
    display_name: str,
    avatar_url: str | None,
) -> User:
    normalized_email = email.strip().lower()
    existing = session.exec(
        select(AuthProvider).where(
            AuthProvider.provider == provider,
            AuthProvider.provider_subject == provider_subject,
        )
    ).first()
    if existing:
        user = get_user_by_id(session, existing.user_id)
        if not user:
            raise OAuthError('OAuth identity points to a missing user')
        return user
    matched_email = get_user_by_email(session, normalized_email)
    if matched_email:
        link_provider(
            session=session,
            user_id=matched_email.id,
            provider=provider,
            provider_subject=provider_subject,
            metadata={'email': normalized_email, 'avatar_url': avatar_url},
        )
        if not matched_email.avatar_url and avatar_url:
            matched_email.avatar_url = avatar_url
        if not matched_email.display_name and display_name:
            matched_email.display_name = display_name
        matched_email.updated_at = datetime.now(UTC)
        session.add(matched_email)
        session.commit()
        session.refresh(matched_email)
        return matched_email
    now = datetime.now(UTC)
    user = User(
        id=uuid.uuid4().hex,
        email=normalized_email,
        display_name=display_name or normalized_email.split('@')[0],
        avatar_url=avatar_url,
        status='active',
        email_verified=True,
        has_password=False,
        preferences={},
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    provider_row = AuthProvider(
        id=uuid.uuid4().hex,
        user_id=user.id,
        provider=provider,
        provider_subject=provider_subject,
        provider_metadata={'email': normalized_email, 'avatar_url': avatar_url},
        created_at=now,
    )
    session.add(provider_row)
    session.commit()
    session.refresh(user)
    return user


def unlink_provider(session: Session, user_id: str, provider: str) -> None:
    providers_stmt = select(AuthProvider).where(AuthProvider.user_id == user_id)
    providers = session.exec(providers_stmt).all()
    if len(providers) <= 1:
        raise ProviderUnlinkError()
    provider_row = next((row for row in providers if row.provider == provider), None)
    if not provider_row:
        return
    if provider_row.provider == _PASSWORD_PROVIDER:
        raise ProviderUnlinkError('Password login cannot be unlinked')
    session.delete(provider_row)
    user = get_user_by_id(session, user_id)
    if not user:
        session.commit()
        return
    has_password_provider = any(row.provider == _PASSWORD_PROVIDER and row.id != provider_row.id for row in providers)
    user.has_password = has_password_provider
    user.updated_at = datetime.now(UTC)
    session.add(user)
    session.commit()


def create_verification_token(session: Session, user_id: str, token_type: str, ttl_hours: int = 24) -> str:
    now = datetime.now(UTC)
    raw = secrets.token_urlsafe(32)
    token = VerificationToken(
        id=uuid.uuid4().hex,
        user_id=user_id,
        token=raw,
        token_type=token_type,
        created_at=now,
        expires_at=now + timedelta(hours=ttl_hours),
        used=False,
    )
    session.add(token)
    session.commit()
    return raw


def validate_verification_token(session: Session, token: str, token_type: str) -> str:
    stmt = select(VerificationToken).where(
        VerificationToken.token == token,
        VerificationToken.token_type == token_type,
    )
    row = session.exec(stmt).first()
    if not row:
        raise TokenInvalidError()
    if row.used:
        raise TokenInvalidError()
    now = datetime.now(UTC)
    if row.expires_at <= now:
        raise TokenExpiredError()
    row.used = True
    session.add(row)
    session.commit()
    return row.user_id


def send_verification_email(user_email: str, token: str) -> None:
    try:
        from modules.settings.service import get_resolved_smtp

        smtp = get_resolved_smtp()
    except Exception:
        logger.warning('Skipping verification email send because SMTP config is unavailable', exc_info=True)
        return
    host = str(smtp.get('host', ''))
    port = int(str(smtp.get('port', 587)))
    smtp_user = str(smtp.get('user', ''))
    password = str(smtp.get('password', ''))

    if not host or not smtp_user:
        logger.info('Skipping verification email send because SMTP is not configured')
        return

    verify_url = f'{settings.auth_frontend_url}/verify?token={token}'
    msg = EmailMessage()
    msg['From'] = smtp_user
    msg['To'] = user_email
    msg['Subject'] = 'Verify your email'
    msg.set_content(f'Please verify your email by opening this link: {verify_url}')

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            if password:
                server.login(smtp_user, password)
            server.send_message(msg)
    except Exception:
        logger.warning('Failed to send verification email', exc_info=True)


def resend_verification(session: Session, user_id: str) -> None:
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    if user.email_verified:
        return

    stmt = select(VerificationToken).where(
        VerificationToken.user_id == user_id,
        VerificationToken.token_type == _EMAIL_VERIFY,
    )
    rows = session.exec(stmt).all()
    last = max(rows, key=lambda row: row.created_at) if rows else None
    if last:
        now = datetime.now(UTC)
        if last.created_at + timedelta(minutes=_RESEND_COOLDOWN_MINUTES) > now:
            raise ValueError('Verification email was sent recently. Please wait before requesting again')

    token = create_verification_token(session, user_id=user_id, token_type=_EMAIL_VERIFY)
    send_verification_email(user.email, token)


def create_password_reset_token(session: Session, email: str) -> str | None:
    user = get_user_by_email(session, email)
    if not user:
        return None
    return create_verification_token(session, user_id=user.id, token_type=_PASSWORD_RESET, ttl_hours=1)


def send_password_reset_email(user_email: str, token: str) -> None:
    try:
        from modules.settings.service import get_resolved_smtp

        smtp = get_resolved_smtp()
    except Exception:
        logger.warning('Skipping password reset email because SMTP config is unavailable', exc_info=True)
        return
    host = str(smtp.get('host', ''))
    port = int(str(smtp.get('port', 587)))
    smtp_user = str(smtp.get('user', ''))
    password = str(smtp.get('password', ''))
    if not host or not smtp_user:
        logger.warning('Skipping password reset email because SMTP is not configured')
        return
    reset_url = f'{settings.auth_frontend_url}/reset-password?token={token}'
    msg = EmailMessage()
    msg['From'] = smtp_user
    msg['To'] = user_email
    msg['Subject'] = 'Reset your password'
    msg.set_content(f'Use this link to reset your password: {reset_url}')
    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            if password:
                server.login(smtp_user, password)
            server.send_message(msg)
    except Exception:
        logger.warning('Failed to send password reset email', exc_info=True)


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
    now = datetime.now(UTC)
    if row.expires_at <= now:
        raise TokenExpiredError()
    user = get_user_by_id(session, row.user_id)
    if not user:
        raise TokenInvalidError()
    provider = session.exec(
        select(AuthProvider).where(AuthProvider.user_id == user.id, AuthProvider.provider == _PASSWORD_PROVIDER)
    ).first()
    if provider:
        provider.provider_metadata = {'password_hash': hash_password(new_password)}
        session.add(provider)
    if not provider:
        session.add(
            AuthProvider(
                id=uuid.uuid4().hex,
                user_id=user.id,
                provider=_PASSWORD_PROVIDER,
                provider_subject=user.email,
                provider_metadata={'password_hash': hash_password(new_password)},
                created_at=now,
            )
        )
    user.has_password = True
    user.updated_at = now
    row.used = True
    session.add(user)
    session.add(row)
    revoke_all_sessions(session, user.id)
    session.commit()
