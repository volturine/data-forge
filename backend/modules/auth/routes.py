import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from core.config import settings
from core.database import get_settings_db
from core.error_handlers import handle_errors
from core.exceptions import AccountDisabledError, InvalidCredentialsError, OAuthError
from modules.auth.dependencies import get_current_user
from modules.auth.models import AuthProvider, User
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
    change_password,
    create_password_reset_token,
    create_session,
    create_user,
    create_verification_token,
    find_or_create_oauth_user,
    get_user_by_email,
    get_user_by_id,
    get_user_providers,
    resend_verification,
    reset_password,
    revoke_all_sessions,
    revoke_session,
    send_password_reset_email,
    send_verification_email,
    unlink_provider,
    validate_verification_token,
    verify_password,
)

router = APIRouter(prefix='/auth', tags=['auth'])
_OAUTH_STATE_MAX_AGE_SECONDS = 600


def _set_session_cookie(response: Response, session_token: str) -> None:
    response.set_cookie(
        key='session_token',
        value=session_token,
        httponly=True,
        secure=not settings.debug,
        samesite='lax',
        max_age=30 * 24 * 3600,
        path='/',
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key='session_token', path='/')


def _oauth_state_cookie_key(provider: str) -> str:
    return f'oauth_state_{provider}'


def _set_oauth_state_cookie(response: Response, provider: str, state: str) -> None:
    response.set_cookie(
        key=_oauth_state_cookie_key(provider),
        value=state,
        httponly=True,
        secure=not settings.debug,
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
    xff = request.headers.get('x-forwarded-for')
    if xff:
        return xff.split(',')[0].strip()[:128]
    if request.client:
        return str(request.client.host)
    return None


@router.post('/register', response_model=UserPublic)
@handle_errors(operation='register')
async def register(body: RegisterRequest, request: Request, response: Response, session: Session = Depends(get_settings_db)) -> UserPublic:
    user = create_user(session, body.email, body.password, body.display_name)
    token = create_verification_token(session, user_id=user.id, token_type='email_verify')
    send_verification_email(user.email, token)
    created_session = create_session(
        session,
        user_id=user.id,
        device_info=_request_device_info(request),
        ip_address=_request_ip_address(request),
    )
    _set_session_cookie(response, created_session.id)
    return _build_user_public(session, user)


@router.post('/login', response_model=UserPublic)
@handle_errors(operation='login')
async def login(body: LoginRequest, request: Request, response: Response, session: Session = Depends(get_settings_db)) -> UserPublic:
    user = get_user_by_email(session, body.email)
    if not user:
        raise InvalidCredentialsError()
    if user.status == 'disabled':
        raise AccountDisabledError()
    password_provider = session.exec(
        select(AuthProvider).where(
            AuthProvider.user_id == user.id,
            AuthProvider.provider == 'password',
        )
    ).first()
    if not password_provider:
        raise InvalidCredentialsError()
    metadata = password_provider.provider_metadata or {}
    hashed = metadata.get('password_hash')
    if not isinstance(hashed, str):
        raise InvalidCredentialsError()
    if not verify_password(body.password, hashed):
        raise InvalidCredentialsError()
    created_session = create_session(
        session,
        user_id=user.id,
        device_info=_request_device_info(request),
        ip_address=_request_ip_address(request),
    )
    _set_session_cookie(response, created_session.id)
    return _build_user_public(session, user)


@router.post('/logout')
@handle_errors(operation='logout')
async def logout(request: Request, response: Response, session: Session = Depends(get_settings_db)) -> dict[str, bool]:
    token = request.cookies.get('session_token') or request.headers.get('X-Session-Token')
    if token:
        revoke_session(session, token)
    _clear_session_cookie(response)
    return {'success': True}


@router.post('/verify-email', response_model=MessageResponse)
@handle_errors(operation='verify email')
async def verify_email(body: VerifyEmailRequest, session: Session = Depends(get_settings_db)) -> MessageResponse:
    user_id = validate_verification_token(session, token=body.token, token_type='email_verify')
    user = get_user_by_id(session, user_id)
    if not user:
        raise InvalidCredentialsError()
    user.email_verified = True
    session.add(user)
    session.commit()
    return MessageResponse(message='Email verified successfully')


@router.post('/resend-verification', response_model=MessageResponse)
@handle_errors(operation='resend verification')
async def resend_verification_route(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_settings_db),
) -> MessageResponse:
    resend_verification(session, current_user.id)
    return MessageResponse(message='Verification email sent')


@router.post('/forgot-password', response_model=MessageResponse)
@handle_errors(operation='forgot password')
async def forgot_password(body: ForgotPasswordRequest, session: Session = Depends(get_settings_db)) -> MessageResponse:
    token = create_password_reset_token(session, body.email)
    if token:
        send_password_reset_email(body.email.strip().lower(), token)
    return MessageResponse(message='If the email exists, a password reset link has been sent')


@router.post('/reset-password', response_model=MessageResponse)
@handle_errors(operation='reset password')
async def reset_password_route(body: ResetPasswordRequest, session: Session = Depends(get_settings_db)) -> MessageResponse:
    reset_password(session, body.token, body.new_password)
    return MessageResponse(message='Password reset successful')


@router.get('/me', response_model=UserPublic)
@handle_errors(operation='get current user')
async def me(current_user: User = Depends(get_current_user), session: Session = Depends(get_settings_db)) -> UserPublic:
    return _build_user_public(session, current_user)


@router.put('/profile', response_model=UserPublic)
@handle_errors(operation='update profile')
async def update_profile_route(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_settings_db),
) -> UserPublic:
    from modules.auth.service import update_profile

    updated = update_profile(
        session,
        user_id=current_user.id,
        display_name=body.display_name,
        avatar_url=body.avatar_url,
        preferences=body.preferences,
    )
    return _build_user_public(session, updated)


@router.put('/password')
@handle_errors(operation='change password')
async def change_password_route(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_settings_db),
) -> dict[str, bool]:
    change_password(session, current_user.id, body.current_password, body.new_password)
    return {'success': True}


@router.delete('/sessions')
@handle_errors(operation='revoke all sessions')
async def revoke_all_sessions_route(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_settings_db),
) -> dict[str, bool]:
    current_token = request.cookies.get('session_token') or request.headers.get('X-Session-Token')
    revoke_all_sessions(session, current_user.id)
    if current_token:
        revoke_session(session, current_token)
    _clear_session_cookie(response)
    return {'success': True}


@router.get('/google')
@handle_errors(operation='google oauth start')
async def google_oauth_start() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    params = {
        'client_id': settings.google_client_id,
        'redirect_uri': settings.google_redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'online',
        'prompt': 'select_account',
        'state': state,
    }
    url = f'https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}'
    response = RedirectResponse(url=url)
    _set_oauth_state_cookie(response, provider='google', state=state)
    return response


@router.get('/google/callback')
@handle_errors(operation='google oauth callback')
async def google_oauth_callback(
    request: Request,
    params: OAuthCallbackParams = Depends(),
    session: Session = Depends(get_settings_db),
) -> RedirectResponse:
    redirect_url = f'{settings.auth_frontend_url}/#/auth/callback'
    response = RedirectResponse(url=redirect_url)
    _validate_oauth_state(request, response, provider='google', state=params.state)
    token_payload = {
        'code': params.code,
        'client_id': settings.google_client_id,
        'client_secret': settings.google_client_secret,
        'redirect_uri': settings.google_redirect_uri,
        'grant_type': 'authorization_code',
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post('https://oauth2.googleapis.com/token', data=token_payload)
        if token_resp.status_code != 200:
            raise OAuthError('Google token exchange failed')
        token_data = token_resp.json()
        access_token = token_data.get('access_token')
        if not isinstance(access_token, str) or not access_token:
            raise OAuthError('Google access token missing')
        info_resp = await client.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
        )
        if info_resp.status_code != 200:
            raise OAuthError('Failed to fetch Google user info')
        info = info_resp.json()
    subject = info.get('id')
    email = info.get('email')
    if not isinstance(subject, str) or not isinstance(email, str):
        raise OAuthError('Google user info missing id or email')
    user = find_or_create_oauth_user(
        session=session,
        provider='google',
        provider_subject=subject,
        email=email,
        display_name=str(info.get('name') or email.split('@')[0]),
        avatar_url=info.get('picture') if isinstance(info.get('picture'), str) else None,
    )
    created_session = create_session(
        session,
        user_id=user.id,
        device_info=_request_device_info(request),
        ip_address=_request_ip_address(request),
    )
    _set_session_cookie(response, created_session.id)
    return response


@router.get('/github')
@handle_errors(operation='github oauth start')
async def github_oauth_start() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    params = {
        'client_id': settings.github_client_id,
        'redirect_uri': settings.github_redirect_uri,
        'scope': 'read:user user:email',
        'state': state,
    }
    url = f'https://github.com/login/oauth/authorize?{urlencode(params)}'
    response = RedirectResponse(url=url)
    _set_oauth_state_cookie(response, provider='github', state=state)
    return response


@router.get('/github/callback')
@handle_errors(operation='github oauth callback')
async def github_oauth_callback(
    request: Request,
    params: OAuthCallbackParams = Depends(),
    session: Session = Depends(get_settings_db),
) -> RedirectResponse:
    redirect_url = f'{settings.auth_frontend_url}/#/auth/callback'
    response = RedirectResponse(url=redirect_url)
    _validate_oauth_state(request, response, provider='github', state=params.state)
    payload = {
        'client_id': settings.github_client_id,
        'client_secret': settings.github_client_secret,
        'code': params.code,
        'redirect_uri': settings.github_redirect_uri,
    }
    headers = {'Accept': 'application/json'}
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post('https://github.com/login/oauth/access_token', data=payload, headers=headers)
        if token_resp.status_code != 200:
            raise OAuthError('GitHub token exchange failed')
        token_data = token_resp.json()
        access_token = token_data.get('access_token')
        if not isinstance(access_token, str) or not access_token:
            raise OAuthError('GitHub access token missing')
        auth_headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'}
        user_resp = await client.get('https://api.github.com/user', headers=auth_headers)
        if user_resp.status_code != 200:
            raise OAuthError('Failed to fetch GitHub user profile')
        gh_user = user_resp.json()
        emails_resp = await client.get('https://api.github.com/user/emails', headers=auth_headers)
        if emails_resp.status_code != 200:
            raise OAuthError('Failed to fetch GitHub email')
        emails = emails_resp.json()
    subject = gh_user.get('id')
    if not isinstance(subject, int):
        raise OAuthError('GitHub user id missing')
    email = next((item.get('email') for item in emails if item.get('primary') and item.get('verified')), None)
    if not isinstance(email, str):
        email = next((item.get('email') for item in emails if item.get('verified')), None)
    if not isinstance(email, str):
        raise OAuthError('GitHub account has no verified email')
    user = find_or_create_oauth_user(
        session=session,
        provider='github',
        provider_subject=str(subject),
        email=email,
        display_name=str(gh_user.get('name') or gh_user.get('login') or email.split('@')[0]),
        avatar_url=gh_user.get('avatar_url') if isinstance(gh_user.get('avatar_url'), str) else None,
    )
    created_session = create_session(
        session,
        user_id=user.id,
        device_info=_request_device_info(request),
        ip_address=_request_ip_address(request),
    )
    _set_session_cookie(response, created_session.id)
    return response


@router.post('/providers/{provider}/unlink')
@handle_errors(operation='unlink provider')
async def unlink_provider_route(
    provider: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_settings_db),
) -> dict[str, bool]:
    if provider not in {'google', 'github'}:
        raise HTTPException(status_code=400, detail='Unsupported provider')
    unlink_provider(session, current_user.id, provider)
    return {'success': True}
