from dataclasses import dataclass

from sqlmodel import Session

from backend_core.auth_exceptions import AccountDisabledError, InvalidCredentialsError
from backend_core.transactions import committed
from modules.auth import service
from modules.auth.models import AuthProviderName, User, UserSession, UserStatus, VerificationTokenType


@dataclass(frozen=True)
class AuthenticatedUser:
    user: User
    user_session: UserSession


@dataclass(frozen=True)
class RegisteredUser(AuthenticatedUser):
    verification_token: str | None


@committed
def register_user(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    email_verified: bool,
    device_info: str | None,
    ip_address: str | None,
) -> RegisteredUser:
    user = service.stage_create_user(
        session,
        email,
        password,
        display_name,
        email_verified=email_verified,
    )
    token = None
    if not email_verified:
        token = service.stage_create_verification_token(
            session,
            user_id=user.id,
            token_type=VerificationTokenType.EMAIL_VERIFY,
        )
    user_session = service.stage_create_session(
        session,
        user_id=user.id,
        device_info=device_info,
        ip_address=ip_address,
    )
    return RegisteredUser(user=user, user_session=user_session, verification_token=token)


@committed
def login_user(
    session: Session,
    *,
    email: str,
    password: str,
    device_info: str | None,
    ip_address: str | None,
) -> AuthenticatedUser:
    user = service.get_user_by_email(session, email)
    if user is None:
        raise InvalidCredentialsError()
    if user.status == UserStatus.DISABLED:
        raise AccountDisabledError()
    password_provider = service.get_password_provider(session, user.id)
    if password_provider is None:
        raise InvalidCredentialsError()
    metadata = password_provider.provider_metadata or {}
    hashed = metadata.get('password_hash')
    if not isinstance(hashed, str) or not service.verify_password(password, hashed):
        raise InvalidCredentialsError()
    user_session = service.stage_create_session(
        session,
        user_id=user.id,
        device_info=device_info,
        ip_address=ip_address,
    )
    return AuthenticatedUser(user=user, user_session=user_session)


@committed
def authenticate_oauth_user(
    session: Session,
    *,
    provider: AuthProviderName,
    provider_subject: str,
    email: str,
    display_name: str,
    avatar_url: str | None,
    device_info: str | None,
    ip_address: str | None,
) -> AuthenticatedUser:
    user = service.stage_find_or_create_oauth_user(
        session,
        provider=provider,
        provider_subject=provider_subject,
        email=email,
        display_name=display_name,
        avatar_url=avatar_url,
    )
    user_session = service.stage_create_session(
        session,
        user_id=user.id,
        device_info=device_info,
        ip_address=ip_address,
    )
    return AuthenticatedUser(user=user, user_session=user_session)


revoke_session = committed(service.stage_revoke_session)
delete_user_account = committed(service.stage_delete_user_account)
update_profile = committed(service.stage_update_profile, refresh=True)
change_password = committed(service.stage_change_password)
prepare_resend_verification = committed(service.stage_prepare_resend_verification)
create_password_reset_token = committed(service.stage_create_password_reset_token)
reset_password = committed(service.stage_reset_password)
unlink_provider = committed(service.stage_unlink_provider)


@committed
def revoke_all_user_sessions(session: Session, *, user_id: str, current_session_id: str | None) -> None:
    service.stage_revoke_all_sessions(session, user_id)
    if current_session_id is not None:
        service.stage_revoke_session(session, current_session_id)


@committed
def verify_email(session: Session, token: str) -> None:
    user_id = service.stage_validate_verification_token(
        session,
        token=token,
        token_type=VerificationTokenType.EMAIL_VERIFY,
    )
    user = service.get_user_by_id(session, user_id)
    if user is None:
        raise InvalidCredentialsError()
    user.email_verified = True
    session.add(user)
