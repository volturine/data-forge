import secrets
from collections.abc import Callable
from functools import partial
from typing import Concatenate
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from backend_core import http as http_client
from backend_core.api_execution_budget import run_api_blocking, run_bootstrap_settings_db
from backend_core.auth_config import settings as auth_settings
from backend_core.auth_exceptions import OAuthError
from backend_core.database import run_settings_db
from backend_core.error_handlers import handle_errors
from backend_core.proxy import client_ip, request_scheme
from modules.auth import commands, service as auth_service
from modules.auth.dependencies import get_current_user
from modules.auth.models import (
    AuthProviderName,
    User,
)
from modules.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    OAuthCallbackParams,
    RegisterRequest,
    ResetPasswordRequest,
    UpdateProfileRequest,
    UserPublic,
    VerifyEmailRequest,
)
from modules.auth.service import (
    ensure_default_user,
    get_user_providers,
    send_password_reset_email,
    validate_session,
)

router = APIRouter(prefix='/auth', tags=['auth'])


async def _run_auth_db[**P, T](function: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
    work = partial(run_settings_db, function, *args, **kwargs)
    return await run_api_blocking(work)


async def send_verification_email(user_email: str, token: str) -> bool:
    return await auth_service.send_verification_email(user_email, token)


_OAUTH_STATE_MAX_AGE_SECONDS = 600


def _set_session_cookie(response: Response, session_token: str, *, secure: bool) -> None:
    response.set_cookie(
        key='session_token',
        value=session_token,
        httponly=True,
        secure=secure,
        samesite='lax',
        max_age=30 * 24 * 3600,
        path='/',
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key='session_token', path='/')


def _oauth_state_cookie_key(provider: str) -> str:
    return f'oauth_state_{provider}'


def _set_oauth_state_cookie(response: Response, provider: str, state: str, *, secure: bool) -> None:
    response.set_cookie(
        key=_oauth_state_cookie_key(provider),
        value=state,
        httponly=True,
        secure=secure,
        samesite='lax',
        max_age=_OAUTH_STATE_MAX_AGE_SECONDS,
        path='/',
    )


def _validate_oauth_state(request: Request, response: Response, provider: str, state: str | None) -> None:
    key = _oauth_state_cookie_key(provider)
    cookie_state = request.cookies.get(key)
    response.delete_cookie(key=key, path='/')
    if not state:
        raise OAuthError('OAuth state missing')
    if not cookie_state:
        raise OAuthError('OAuth state cookie missing')
    if not secrets.compare_digest(state, cookie_state):
        raise OAuthError('OAuth state mismatch')


def _github_redirect_uri(request: Request) -> str:
    return str(request.url_for('github_oauth_callback').replace(scheme=request_scheme(request)))


def _github_frontend_callback_url(request: Request) -> str:
    return str(
        request.url_for('github_oauth_callback').replace(
            scheme=request_scheme(request),
            path='/callback',
        )
    )


def _build_user_public(session: Session, user: User) -> UserPublic:
    providers = get_user_providers(session, user.id)
    return UserPublic(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        status=user.status,
        email_verified=user.email_verified,
        has_password=user.has_password,
        preferences=user.preferences,
        providers=providers,
        created_at=user.created_at,
    )


def _request_device_info(request: Request) -> str | None:
    user_agent = request.headers.get('user-agent')
    if user_agent:
        return user_agent[:512]
    return None


def _request_ip_address(request: Request) -> str | None:
    return client_ip(request)


def _register_user(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    email_verified: bool,
    device_info: str | None,
    ip_address: str | None,
) -> tuple[UserPublic, str, str | None]:
    result = commands.register_user(
        session,
        email=email,
        password=password,
        display_name=display_name,
        email_verified=email_verified,
        device_info=device_info,
        ip_address=ip_address,
    )
    return _build_user_public(session, result.user), result.user_session.id, result.verification_token


def _login_user(
    session: Session,
    *,
    email: str,
    password: str,
    device_info: str | None,
    ip_address: str | None,
) -> tuple[UserPublic, str]:
    result = commands.login_user(
        session,
        email=email,
        password=password,
        device_info=device_info,
        ip_address=ip_address,
    )
    return _build_user_public(session, result.user), result.user_session.id


def _authenticate_oauth_user(
    session: Session,
    *,
    provider: AuthProviderName,
    provider_subject: str,
    email: str,
    display_name: str,
    avatar_url: str | None,
    device_info: str | None,
    ip_address: str | None,
) -> str:
    result = commands.authenticate_oauth_user(
        session,
        provider=provider,
        provider_subject=provider_subject,
        email=email,
        display_name=display_name,
        avatar_url=avatar_url,
        device_info=device_info,
        ip_address=ip_address,
    )
    return result.user_session.id


@router.post('/register', response_model=UserPublic)
@handle_errors(operation='register')
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
) -> UserPublic:
    needs_verification = auth_settings.verify_email_address
    user_public, session_token, verification_token = await _run_auth_db(
        _register_user,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        email_verified=not needs_verification,
        device_info=_request_device_info(request),
        ip_address=_request_ip_address(request),
    )
    if verification_token is not None:
        await send_verification_email(user_public.email, verification_token)
    _set_session_cookie(response, session_token, secure=request_scheme(request) == 'https')
    return user_public


@router.post('/login', response_model=UserPublic)
@handle_errors(operation='login')
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
) -> UserPublic:
    user, session_token = await run_api_blocking(
        run_settings_db,
        _login_user,
        email=body.email,
        password=body.password,
        device_info=_request_device_info(request),
        ip_address=_request_ip_address(request),
    )
    _set_session_cookie(response, session_token, secure=request_scheme(request) == 'https')
    return user


@router.post('/logout')
@handle_errors(operation='logout')
async def logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get('session_token') or request.headers.get('X-Session-Token')
    if token:
        await run_api_blocking(run_settings_db, commands.revoke_session, token)
    _clear_session_cookie(response)
    return {'success': True}


@router.delete('/account')
@handle_errors(operation='delete account')
async def delete_account_route(
    response: Response,
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    await run_api_blocking(run_settings_db, commands.delete_user_account, current_user.id)
    _clear_session_cookie(response)
    return {'success': True}


@router.post('/verify-email', response_model=MessageResponse)
@handle_errors(operation='verify email')
async def verify_email(body: VerifyEmailRequest) -> MessageResponse:
    await _run_auth_db(commands.verify_email, body.token)
    return MessageResponse(message='Email verified successfully')


@router.post('/resend-verification', response_model=MessageResponse)
@handle_errors(operation='resend verification')
async def resend_verification_route(
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    delivery = await _run_auth_db(commands.prepare_resend_verification, current_user.id)
    if delivery is not None:
        email, token = delivery
        await send_verification_email(email, token)
    return MessageResponse(message='Verification email sent')


@router.post('/forgot-password', response_model=MessageResponse)
@handle_errors(operation='forgot password')
async def forgot_password(body: ForgotPasswordRequest) -> MessageResponse:
    token = await _run_auth_db(commands.create_password_reset_token, body.email)
    if token:
        await send_password_reset_email(body.email.strip().lower(), token)
    return MessageResponse(message='If the email exists, a password reset link has been sent')


@router.post('/reset-password', response_model=MessageResponse)
@handle_errors(operation='reset password')
async def reset_password_route(body: ResetPasswordRequest) -> MessageResponse:
    await _run_auth_db(commands.reset_password, body.token, body.new_password)
    return MessageResponse(message='Password reset successful')


def _resolve_me(session: Session, token: str | None) -> UserPublic:
    """Resolve the current user inside a settings DB session."""
    if token:
        user = validate_session(session, token)
        if user:
            return _build_user_public(session, user)
    if not auth_settings.auth_required:
        user = ensure_default_user(session)
        return _build_user_public(session, user)
    raise HTTPException(status_code=401, detail='Not authenticated')


def _update_profile(session: Session, token: str | None, body: UpdateProfileRequest) -> UserPublic:
    """Authenticate and update the profile on the dedicated auth DB executor."""
    if token:
        current_user = validate_session(session, token)
        if current_user is None:
            raise HTTPException(status_code=401, detail='Not authenticated')
    elif not auth_settings.auth_required:
        current_user = ensure_default_user(session)
    else:
        raise HTTPException(status_code=401, detail='Not authenticated')

    updated = commands.update_profile(
        session,
        user_id=current_user.id,
        display_name=body.display_name,
        avatar_url=body.avatar_url,
        preferences=body.preferences,
    )
    return _build_user_public(session, updated)


@router.get('/me', response_model=UserPublic)
@handle_errors(operation='get current user')
async def me(request: Request) -> UserPublic:
    token = request.cookies.get('session_token') or request.headers.get('X-Session-Token')
    return await run_bootstrap_settings_db(_resolve_me, token)


@router.put('/profile', response_model=UserPublic)
@handle_errors(operation='update profile')
async def update_profile_route(
    request: Request,
    body: UpdateProfileRequest,
) -> UserPublic:
    token = request.cookies.get('session_token') or request.headers.get('X-Session-Token')
    return await _run_auth_db(_update_profile, token, body)


@router.put('/password')
@handle_errors(operation='change password')
async def change_password_route(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    await run_api_blocking(
        run_settings_db,
        commands.change_password,
        current_user.id,
        body.current_password,
        body.new_password,
    )
    return {'success': True}


@router.delete('/sessions')
@handle_errors(operation='revoke all sessions')
async def revoke_all_sessions_route(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    current_token = request.cookies.get('session_token') or request.headers.get('X-Session-Token')
    await run_api_blocking(
        run_settings_db,
        commands.revoke_all_user_sessions,
        user_id=current_user.id,
        current_session_id=current_token,
    )
    _clear_session_cookie(response)
    return {'success': True}


@router.get('/github')
@handle_errors(operation='github oauth start')
def github_oauth_start(request: Request) -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    params = {
        'client_id': auth_settings.github_client_id,
        'redirect_uri': _github_redirect_uri(request),
        'scope': 'read:user user:email',
        'state': state,
    }
    url = f'https://github.com/login/oauth/authorize?{urlencode(params)}'
    response = RedirectResponse(url=url)
    _set_oauth_state_cookie(
        response,
        provider=AuthProviderName.GITHUB.value,
        state=state,
        secure=request_scheme(request) == 'https',
    )
    return response


@router.get('/github/callback')
@handle_errors(operation='github oauth callback')
async def github_oauth_callback(
    request: Request,
    params: OAuthCallbackParams = Depends(),
) -> RedirectResponse:
    response = RedirectResponse(url=_github_frontend_callback_url(request))
    _validate_oauth_state(request, response, provider=AuthProviderName.GITHUB.value, state=params.state)
    payload = {
        'client_id': auth_settings.github_client_id,
        'client_secret': auth_settings.github_client_secret,
        'code': params.code,
        'redirect_uri': _github_redirect_uri(request),
    }
    headers = {'Accept': 'application/json'}
    client = http_client.get_async_client()
    token_resp = await client.post(
        'https://github.com/login/oauth/access_token',
        data=payload,
        headers=headers,
        timeout=15.0,
    )
    if token_resp.status_code != 200:
        raise OAuthError('GitHub token exchange failed')
    token_data = token_resp.json()
    access_token = token_data.get('access_token')
    if not isinstance(access_token, str) or not access_token:
        raise OAuthError('GitHub access token missing')
    auth_headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json',
    }
    user_resp = await client.get('https://api.github.com/user', headers=auth_headers, timeout=15.0)
    if user_resp.status_code != 200:
        raise OAuthError('Failed to fetch GitHub user profile')
    gh_user = user_resp.json()
    emails_resp = await client.get('https://api.github.com/user/emails', headers=auth_headers, timeout=15.0)
    if emails_resp.status_code != 200:
        raise OAuthError('Failed to fetch GitHub email')
    emails = emails_resp.json()
    subject = gh_user.get('id')
    if not isinstance(subject, int):
        raise OAuthError('GitHub user id missing')
    email = next(
        (item.get('email') for item in emails if item.get('primary') and item.get('verified')),
        None,
    )
    if not isinstance(email, str):
        email = next((item.get('email') for item in emails if item.get('verified')), None)
    if not isinstance(email, str):
        raise OAuthError('GitHub account has no verified email')
    result = await run_api_blocking(
        run_settings_db,
        _authenticate_oauth_user,
        provider=AuthProviderName.GITHUB,
        provider_subject=str(subject),
        email=email,
        display_name=str(gh_user.get('name') or gh_user.get('login') or email.split('@')[0]),
        avatar_url=gh_user.get('avatar_url') if isinstance(gh_user.get('avatar_url'), str) else None,
        device_info=_request_device_info(request),
        ip_address=_request_ip_address(request),
    )
    _set_session_cookie(response, result, secure=request_scheme(request) == 'https')
    return response


@router.post('/providers/{provider}/unlink')
@handle_errors(operation='unlink provider')
async def unlink_provider_route(
    provider: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    try:
        provider_name = AuthProviderName(provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Unsupported provider') from exc
    if provider_name not in {AuthProviderName.GOOGLE, AuthProviderName.GITHUB}:
        raise HTTPException(status_code=400, detail='Unsupported provider')
    await run_api_blocking(run_settings_db, commands.unlink_provider, current_user.id, provider_name)
    return {'success': True}
