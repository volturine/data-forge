from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from core.database import get_settings_db
from core.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    ProviderUnlinkError,
    TokenExpiredError,
    TokenInvalidError,
)
from main import app
from modules.auth.dependencies import get_current_user, get_optional_user
from modules.auth.models import AuthProvider, User, UserSession, VerificationToken
from modules.auth.service import (
    change_password,
    create_session,
    create_user,
    create_verification_token,
    ensure_default_user,
    find_or_create_oauth_user,
    get_user_by_email,
    get_user_by_id,
    hash_password,
    revoke_all_sessions,
    revoke_session,
    send_verification_email,
    unlink_provider,
    update_profile,
    validate_password,
    validate_session,
    validate_verification_token,
    verify_password,
)


@pytest.fixture(scope='function')
def auth_engine():
    engine = create_engine(
        'sqlite:///:memory:',
        echo=False,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture(scope='function')
def auth_db_session(auth_engine):
    with Session(auth_engine) as session:
        yield session


@pytest.fixture(scope='function')
def auth_client(auth_db_session: Session, monkeypatch):
    monkeypatch.setattr('core.config.settings.debug', True)
    ensure_default_user(auth_db_session)

    def override_get_settings_db():
        yield auth_db_session

    if hasattr(app.state, 'mcp_registry'):
        del app.state.mcp_registry
    app.dependency_overrides[get_settings_db] = override_get_settings_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


class TestPasswordHashing:
    def test_hash_and_verify_correct_password(self) -> None:
        password = 'strongpassword123'

        hashed = hash_password(password)

        assert hashed.startswith('pbkdf2_sha256$')
        assert verify_password(password, hashed) is True

    def test_hash_and_verify_wrong_password(self) -> None:
        hashed = hash_password('strongpassword123')

        assert verify_password('wrongpassword123', hashed) is False

    def test_verify_malformed_hash(self) -> None:
        assert verify_password('strongpassword123', 'badhash') is False
        assert verify_password('strongpassword123', 'pbkdf2_sha256$abc$00$11') is False
        assert verify_password('strongpassword123', 'pbkdf2_sha256$200000$0$11') is False

    def test_validate_password_valid(self) -> None:
        validate_password('Strong123')

    def test_validate_password_too_short(self) -> None:
        with pytest.raises(ValueError, match='at least 8'):
            validate_password('short')

    def test_validate_password_requires_uppercase(self) -> None:
        with pytest.raises(ValueError, match='uppercase'):
            validate_password('strong123')

    def test_validate_password_requires_lowercase(self) -> None:
        with pytest.raises(ValueError, match='lowercase'):
            validate_password('STRONG123')

    def test_validate_password_requires_digit(self) -> None:
        with pytest.raises(ValueError, match='digit'):
            validate_password('StrongPass')


class TestUserService:
    def test_init_settings_db_seeds_default_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core import database

        engine = create_engine(
            'sqlite:///:memory:',
            echo=False,
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )
        monkeypatch.setattr(database, 'settings_engine', engine, raising=False)
        monkeypatch.setattr('core.config.settings.default_user_email', 'seeded@example.com')
        monkeypatch.setattr('core.config.settings.default_user_password', 'SeededPass123')
        monkeypatch.setattr('core.config.settings.default_user_name', 'Seeded User')

        database._init_settings_db()

        with Session(engine) as session:
            user = session.exec(select(User).where(User.email == 'seeded@example.com')).first()
            assert user is not None
            assert user.display_name == 'Seeded User'
            provider = session.exec(
                select(AuthProvider).where(AuthProvider.user_id == user.id, AuthProvider.provider == 'password')
            ).first()
            assert provider is not None

    def test_ensure_default_user_seeds_from_env(self, auth_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('core.config.settings.default_user_email', 'guest@example.com')
        monkeypatch.setattr('core.config.settings.default_user_password', 'GuestPass123')
        monkeypatch.setattr('core.config.settings.default_user_name', 'Guest User')

        user = ensure_default_user(auth_db_session)

        assert user.email == 'guest@example.com'
        assert user.display_name == 'Guest User'
        assert user.email_verified is True
        assert user.has_password is True
        provider = auth_db_session.exec(
            select(AuthProvider).where(AuthProvider.user_id == user.id, AuthProvider.provider == 'password')
        ).first()
        assert provider is not None
        assert provider.provider_subject == 'guest@example.com'
        assert isinstance(provider.provider_metadata, dict)
        assert provider.provider_metadata['managed_by'] == 'env_default_user'
        assert verify_password('GuestPass123', provider.provider_metadata['password_hash']) is True

    def test_ensure_default_user_updates_existing_account(self, auth_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('core.config.settings.default_user_email', 'first@example.com')
        monkeypatch.setattr('core.config.settings.default_user_password', 'FirstPass123')
        monkeypatch.setattr('core.config.settings.default_user_name', 'First User')
        first = ensure_default_user(auth_db_session)

        monkeypatch.setattr('core.config.settings.default_user_email', 'second@example.com')
        monkeypatch.setattr('core.config.settings.default_user_password', 'SecondPass123')
        monkeypatch.setattr('core.config.settings.default_user_name', 'Second User')
        updated = ensure_default_user(auth_db_session)

        assert updated.id == first.id
        assert updated.email == 'second@example.com'
        assert updated.display_name == 'Second User'
        provider = auth_db_session.exec(
            select(AuthProvider).where(AuthProvider.user_id == updated.id, AuthProvider.provider == 'password')
        ).first()
        assert provider is not None
        assert provider.provider_subject == 'second@example.com'
        assert isinstance(provider.provider_metadata, dict)
        assert verify_password('SecondPass123', provider.provider_metadata['password_hash']) is True

    def test_ensure_default_user_keeps_email_when_new_env_email_is_taken(
        self,
        auth_db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr('core.config.settings.default_user_email', 'default@example.com')
        monkeypatch.setattr('core.config.settings.default_user_password', 'DefaultPass123')
        monkeypatch.setattr('core.config.settings.default_user_name', 'Default User')
        user = ensure_default_user(auth_db_session)
        create_user(auth_db_session, 'taken@example.com', 'Password123', 'Taken User')

        monkeypatch.setattr('core.config.settings.default_user_email', 'taken@example.com')
        monkeypatch.setattr('core.config.settings.default_user_password', 'ChangedPass123')
        monkeypatch.setattr('core.config.settings.default_user_name', 'Renamed Default')
        updated = ensure_default_user(auth_db_session)

        assert updated.id == user.id
        assert updated.email == 'default@example.com'
        assert updated.display_name == 'Renamed Default'
        provider = auth_db_session.exec(
            select(AuthProvider).where(AuthProvider.user_id == updated.id, AuthProvider.provider == 'password')
        ).first()
        assert provider is not None
        assert provider.provider_subject == 'default@example.com'
        assert isinstance(provider.provider_metadata, dict)
        assert verify_password('ChangedPass123', provider.provider_metadata['password_hash']) is True

    def test_create_user_success(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')

        assert user.email == 'test@example.com'
        assert user.display_name == 'Test User'
        assert user.has_password is True

        provider = auth_db_session.exec(
            select(AuthProvider).where(AuthProvider.user_id == user.id, AuthProvider.provider == 'password')
        ).first()
        assert provider is not None
        assert provider.provider_subject == 'test@example.com'
        assert isinstance(provider.provider_metadata, dict)
        assert 'password_hash' in provider.provider_metadata

    def test_create_user_duplicate_email(self, auth_db_session: Session) -> None:
        create_user(auth_db_session, 'test@example.com', 'Password123', 'User One')

        with pytest.raises(EmailAlreadyExistsError):
            create_user(auth_db_session, 'test@example.com', 'Password123', 'User Two')

    def test_get_user_by_email(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')

        found = get_user_by_email(auth_db_session, 'TEST@EXAMPLE.COM')

        assert found is not None
        assert found.id == user.id

    def test_get_user_by_email_not_found(self, auth_db_session: Session) -> None:
        found = get_user_by_email(auth_db_session, 'missing@example.com')

        assert found is None

    def test_get_user_by_id(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')

        found = get_user_by_id(auth_db_session, user.id)

        assert found is not None
        assert found.email == 'test@example.com'

    def test_update_profile(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')

        updated = update_profile(
            auth_db_session,
            user_id=user.id,
            display_name='Updated Name',
            avatar_url=None,
            preferences=None,
        )

        assert updated.display_name == 'Updated Name'

    def test_change_password(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')

        change_password(auth_db_session, user.id, 'Password123', 'Newpassword123')

        provider = auth_db_session.exec(
            select(AuthProvider).where(AuthProvider.user_id == user.id, AuthProvider.provider == 'password')
        ).first()
        assert provider is not None
        assert isinstance(provider.provider_metadata, dict)
        hashed = provider.provider_metadata.get('password_hash')
        assert isinstance(hashed, str)
        assert verify_password('Newpassword123', hashed) is True
        assert verify_password('Password123', hashed) is False

    def test_change_password_wrong_current(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')

        with pytest.raises(InvalidCredentialsError):
            change_password(auth_db_session, user.id, 'wrongpassword', 'Newpassword123')


class TestSessionService:
    def test_create_session(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')

        user_session = create_session(auth_db_session, user.id, 'pytest-agent', '127.0.0.1')

        assert user_session.user_id == user.id
        assert user_session.revoked is False
        assert user_session.expires_at > datetime.now(UTC).replace(tzinfo=None)

    def test_validate_session_valid(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')
        user_session = create_session(auth_db_session, user.id, None, None)

        resolved = validate_session(auth_db_session, user_session.id)

        assert resolved is not None
        assert resolved.id == user.id
        assert resolved.last_login_at is not None

    def test_validate_session_expired(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')
        now = datetime.now(UTC).replace(tzinfo=None)
        user_session = UserSession(
            user_id=user.id,
            device_info=None,
            ip_address=None,
            created_at=now - timedelta(days=3),
            expires_at=now - timedelta(minutes=1),
            revoked=False,
        )
        auth_db_session.add(user_session)
        auth_db_session.commit()
        auth_db_session.refresh(user_session)

        resolved = validate_session(auth_db_session, user_session.id)

        assert resolved is None
        refreshed = auth_db_session.get(UserSession, user_session.id)
        assert refreshed is not None
        assert refreshed.revoked is True

    def test_validate_session_revoked(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')
        now = datetime.now(UTC).replace(tzinfo=None)
        user_session = UserSession(
            user_id=user.id,
            device_info=None,
            ip_address=None,
            created_at=now,
            expires_at=now + timedelta(days=1),
            revoked=True,
        )
        auth_db_session.add(user_session)
        auth_db_session.commit()
        auth_db_session.refresh(user_session)

        resolved = validate_session(auth_db_session, user_session.id)

        assert resolved is None

    def test_revoke_session(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')
        user_session = create_session(auth_db_session, user.id, None, None)

        revoke_session(auth_db_session, user_session.id)

        refreshed = auth_db_session.get(UserSession, user_session.id)
        assert refreshed is not None
        assert refreshed.revoked is True

    def test_revoke_all_sessions(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'test@example.com', 'Password123', 'Test User')
        first = create_session(auth_db_session, user.id, None, None)
        second = create_session(auth_db_session, user.id, None, None)

        revoke_all_sessions(auth_db_session, user.id)

        refreshed_first = auth_db_session.get(UserSession, first.id)
        refreshed_second = auth_db_session.get(UserSession, second.id)
        assert refreshed_first is not None
        assert refreshed_second is not None
        assert refreshed_first.revoked is True
        assert refreshed_second.revoked is True


class TestOAuthService:
    def test_find_or_create_oauth_user_new(self, auth_db_session: Session) -> None:
        user = find_or_create_oauth_user(
            session=auth_db_session,
            provider='google',
            provider_subject='google-subject-1',
            email='oauth@example.com',
            display_name='OAuth User',
            avatar_url='https://example.com/avatar.png',
        )

        assert user.email == 'oauth@example.com'
        assert user.has_password is False
        provider = auth_db_session.exec(
            select(AuthProvider).where(AuthProvider.user_id == user.id, AuthProvider.provider == 'google')
        ).first()
        assert provider is not None

    def test_find_or_create_oauth_user_existing_provider(self, auth_db_session: Session) -> None:
        user = find_or_create_oauth_user(
            session=auth_db_session,
            provider='github',
            provider_subject='github-subject-1',
            email='oauth@example.com',
            display_name='OAuth User',
            avatar_url=None,
        )

        resolved = find_or_create_oauth_user(
            session=auth_db_session,
            provider='github',
            provider_subject='github-subject-1',
            email='oauth-changed@example.com',
            display_name='Changed Name',
            avatar_url='https://example.com/new-avatar.png',
        )

        assert resolved.id == user.id
        providers = auth_db_session.exec(select(AuthProvider).where(AuthProvider.user_id == user.id)).all()
        assert len(providers) == 1

    def test_find_or_create_oauth_user_existing_email(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'existing@example.com', 'Password123', 'Existing User')

        resolved = find_or_create_oauth_user(
            session=auth_db_session,
            provider='google',
            provider_subject='google-subject-2',
            email='existing@example.com',
            display_name='OAuth Existing',
            avatar_url='https://example.com/avatar.png',
        )

        assert resolved.id == user.id
        providers = auth_db_session.exec(select(AuthProvider).where(AuthProvider.user_id == user.id)).all()
        names = {item.provider for item in providers}
        assert names == {'password', 'google'}

    def test_unlink_provider_success(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'existing@example.com', 'Password123', 'Existing User')
        find_or_create_oauth_user(
            session=auth_db_session,
            provider='google',
            provider_subject='google-subject-3',
            email='existing@example.com',
            display_name='OAuth Existing',
            avatar_url=None,
        )

        unlink_provider(auth_db_session, user.id, 'google')

        providers = auth_db_session.exec(select(AuthProvider).where(AuthProvider.user_id == user.id)).all()
        names = {item.provider for item in providers}
        assert names == {'password'}

    def test_unlink_provider_last(self, auth_db_session: Session) -> None:
        user = find_or_create_oauth_user(
            session=auth_db_session,
            provider='google',
            provider_subject='google-subject-4',
            email='oauth-last@example.com',
            display_name='OAuth Last',
            avatar_url=None,
        )

        with pytest.raises(ProviderUnlinkError):
            unlink_provider(auth_db_session, user.id, 'google')

    def test_unlink_provider_preserves_row_when_user_missing(self, auth_db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        user = create_user(auth_db_session, 'missing-user@example.com', 'Password123', 'Missing User')
        find_or_create_oauth_user(
            session=auth_db_session,
            provider='google',
            provider_subject='google-subject-5',
            email='missing-user@example.com',
            display_name='Missing User',
            avatar_url=None,
        )

        monkeypatch.setattr('modules.auth.service.get_user_by_id', lambda _session, _user_id: None)

        with pytest.raises(ProviderUnlinkError, match='missing account'):
            unlink_provider(auth_db_session, user.id, 'google')

        providers = auth_db_session.exec(select(AuthProvider).where(AuthProvider.user_id == user.id)).all()
        names = {item.provider for item in providers}
        assert names == {'password', 'google'}


class TestVerificationTokenService:
    def test_create_verification_token_returns_valid_token(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'verify-token@example.com', 'Password123', 'Verify Token User')

        token = create_verification_token(auth_db_session, user_id=user.id, token_type='email_verify')

        assert isinstance(token, str)
        assert len(token) >= 32
        row = auth_db_session.exec(select(VerificationToken).where(VerificationToken.token == token)).first()
        assert row is not None
        assert row.user_id == user.id
        assert row.token_type == 'email_verify'
        assert row.used is False

    def test_validate_verification_token_valid(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'validate-token@example.com', 'Password123', 'Validate Token User')
        token = create_verification_token(auth_db_session, user_id=user.id, token_type='email_verify')

        resolved_user_id = validate_verification_token(auth_db_session, token=token, token_type='email_verify')

        assert resolved_user_id == user.id
        row = auth_db_session.exec(select(VerificationToken).where(VerificationToken.token == token)).first()
        assert row is not None
        assert row.used is True

    def test_validate_verification_token_expired(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'expired-token@example.com', 'Password123', 'Expired Token User')
        token = create_verification_token(auth_db_session, user_id=user.id, token_type='email_verify', ttl_hours=-1)

        with pytest.raises(TokenExpiredError):
            validate_verification_token(auth_db_session, token=token, token_type='email_verify')

    def test_validate_verification_token_used(self, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'used-token@example.com', 'Password123', 'Used Token User')
        token = create_verification_token(auth_db_session, user_id=user.id, token_type='email_verify')
        validate_verification_token(auth_db_session, token=token, token_type='email_verify')

        with pytest.raises(TokenInvalidError):
            validate_verification_token(auth_db_session, token=token, token_type='email_verify')


class TestAuthRoutes:
    def test_dependencies_resolve_default_user_when_auth_disabled(
        self,
        auth_db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        monkeypatch.setattr('core.config.settings.default_user_email', 'guest@example.com')
        monkeypatch.setattr('core.config.settings.default_user_password', 'GuestPass123')
        monkeypatch.setattr('core.config.settings.default_user_name', 'Guest User')
        ensure_default_user(auth_db_session)

        app = FastAPI()

        def override_get_settings_db():
            yield auth_db_session

        @app.get('/current')
        async def current(user: User = Depends(get_current_user)) -> dict[str, str]:
            return {'email': user.email}

        @app.get('/optional')
        async def optional(user: User | None = Depends(get_optional_user)) -> dict[str, str | None]:
            return {'email': user.email if user else None}

        app.dependency_overrides[get_settings_db] = override_get_settings_db
        with TestClient(app) as client:
            resp_current = client.get('/current')
            resp_optional = client.get('/optional')

        assert resp_current.status_code == 200
        assert resp_current.json()['email'] == 'guest@example.com'
        assert resp_optional.status_code == 200
        assert resp_optional.json()['email'] == 'guest@example.com'

    def test_get_current_user_returns_401_when_auth_required(
        self,
        auth_db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', True)

        app = FastAPI()

        def override_get_settings_db():
            yield auth_db_session

        @app.get('/current')
        async def current(user: User = Depends(get_current_user)) -> dict[str, str]:
            return {'email': user.email}

        @app.get('/optional')
        async def optional(user: User | None = Depends(get_optional_user)) -> dict[str, str | None]:
            return {'email': user.email if user else None}

        app.dependency_overrides[get_settings_db] = override_get_settings_db
        with TestClient(app) as client:
            resp_current = client.get('/current')
            resp_optional = client.get('/optional')

        assert resp_current.status_code == 401
        assert resp_optional.status_code == 200
        assert resp_optional.json()['email'] is None

    def test_me_returns_default_user_when_auth_disabled(
        self,
        auth_client: TestClient,
        auth_db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', False)
        monkeypatch.setattr('core.config.settings.default_user_email', 'guest@example.com')
        monkeypatch.setattr('core.config.settings.default_user_password', 'GuestPass123')
        monkeypatch.setattr('core.config.settings.default_user_name', 'Guest User')
        ensure_default_user(auth_db_session)

        response = auth_client.get('/api/v1/auth/me')

        assert response.status_code == 200
        assert response.json()['email'] == 'guest@example.com'

    def test_register_success(self, auth_client: TestClient) -> None:
        response = auth_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'register@example.com',
                'password': 'Password123',
                'display_name': 'Register User',
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body['email'] == 'register@example.com'
        assert body['display_name'] == 'Register User'
        assert 'password' in body['providers']
        assert 'session_token' in response.cookies

    def test_register_duplicate_email(self, auth_client: TestClient) -> None:
        payload = {
            'email': 'duplicate@example.com',
            'password': 'Password123',
            'display_name': 'User One',
        }
        first = auth_client.post('/api/v1/auth/register', json=payload)
        second = auth_client.post('/api/v1/auth/register', json=payload)

        assert first.status_code == 200
        assert second.status_code == 409

    def test_register_weak_password(self, auth_client: TestClient) -> None:
        response = auth_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'weak@example.com',
                'password': 'short',
                'display_name': 'Weak User',
            },
        )

        assert response.status_code == 400

    def test_login_success(self, auth_client: TestClient) -> None:
        auth_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'login@example.com',
                'password': 'Password123',
                'display_name': 'Login User',
            },
        )

        response = auth_client.post('/api/v1/auth/login', json={'email': 'login@example.com', 'password': 'Password123'})

        assert response.status_code == 200
        assert response.json()['email'] == 'login@example.com'
        assert 'session_token' in response.cookies

    def test_login_wrong_password(self, auth_client: TestClient) -> None:
        auth_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'wrongpass@example.com',
                'password': 'Password123',
                'display_name': 'Wrong Pass User',
            },
        )

        response = auth_client.post('/api/v1/auth/login', json={'email': 'wrongpass@example.com', 'password': 'wrongpassword'})

        assert response.status_code == 401

    def test_login_nonexistent_email(self, auth_client: TestClient) -> None:
        response = auth_client.post('/api/v1/auth/login', json={'email': 'missing@example.com', 'password': 'Password123'})

        assert response.status_code == 401

    def test_me_authenticated(self, auth_client: TestClient) -> None:
        auth_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'me@example.com',
                'password': 'Password123',
                'display_name': 'Me User',
            },
        )

        response = auth_client.get('/api/v1/auth/me')

        assert response.status_code == 200
        assert response.json()['email'] == 'me@example.com'

    def test_me_unauthenticated(self, auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', True)

        response = auth_client.get('/api/v1/auth/me')

        assert response.status_code == 401

    def test_me_unauthenticated_when_auth_required(self, auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('core.config.settings.auth_required', True)

        response = auth_client.get('/api/v1/auth/me')

        assert response.status_code == 401

    def test_logout(self, auth_client: TestClient) -> None:
        auth_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'logout@example.com',
                'password': 'Password123',
                'display_name': 'Logout User',
            },
        )

        response = auth_client.post('/api/v1/auth/logout')

        assert response.status_code == 200
        assert response.json()['success'] is True
        set_cookie = response.headers.get('set-cookie', '')
        assert 'session_token=' in set_cookie
        assert 'Max-Age=0' in set_cookie

    def test_update_profile_authenticated(self, auth_client: TestClient) -> None:
        auth_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'profile@example.com',
                'password': 'Password123',
                'display_name': 'Profile User',
            },
        )

        response = auth_client.put(
            '/api/v1/auth/profile',
            json={'display_name': 'Updated Profile User'},
        )

        assert response.status_code == 200
        assert response.json()['display_name'] == 'Updated Profile User'

    def test_change_password_authenticated(self, auth_client: TestClient) -> None:
        auth_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'changepass@example.com',
                'password': 'Password123',
                'display_name': 'Change Password User',
            },
        )

        response = auth_client.put(
            '/api/v1/auth/password',
            json={'current_password': 'Password123', 'new_password': 'Newpassword123'},
        )

        assert response.status_code == 200
        assert response.json()['success'] is True

        auth_client.post('/api/v1/auth/logout')
        login = auth_client.post('/api/v1/auth/login', json={'email': 'changepass@example.com', 'password': 'Newpassword123'})
        assert login.status_code == 200

    def test_forgot_password_existing_email_creates_token(self, auth_client: TestClient, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'forgot-existing@example.com', 'Password123', 'Forgot Existing User')

        response = auth_client.post('/api/v1/auth/forgot-password', json={'email': user.email})

        assert response.status_code == 200
        assert response.json()['message'] == 'If the email exists, a password reset link has been sent'
        row = auth_db_session.exec(
            select(VerificationToken).where(
                VerificationToken.user_id == user.id,
                VerificationToken.token_type == 'password_reset',
            )
        ).first()
        assert row is not None
        assert row.used is False

    def test_forgot_password_nonexistent_email_returns_success(
        self,
        auth_client: TestClient,
        auth_db_session: Session,
    ) -> None:
        response = auth_client.post('/api/v1/auth/forgot-password', json={'email': 'missing-reset@example.com'})

        assert response.status_code == 200
        assert response.json()['message'] == 'If the email exists, a password reset link has been sent'
        rows = auth_db_session.exec(select(VerificationToken).where(VerificationToken.token_type == 'password_reset')).all()
        assert len(rows) == 0

    def test_reset_password_happy_path(self, auth_client: TestClient, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'reset-happy@example.com', 'Password123', 'Reset Happy User')
        user_session = create_session(auth_db_session, user.id, 'pytest-agent', '127.0.0.1')
        token = create_verification_token(auth_db_session, user_id=user.id, token_type='password_reset', ttl_hours=1)

        response = auth_client.post(
            '/api/v1/auth/reset-password',
            json={'token': token, 'new_password': 'Newpassword123'},
        )

        assert response.status_code == 200
        assert response.json()['message'] == 'Password reset successful'
        provider = auth_db_session.exec(
            select(AuthProvider).where(AuthProvider.user_id == user.id, AuthProvider.provider == 'password')
        ).first()
        assert provider is not None
        assert isinstance(provider.provider_metadata, dict)
        hashed = provider.provider_metadata.get('password_hash')
        assert isinstance(hashed, str)
        assert verify_password('Newpassword123', hashed) is True
        token_row = auth_db_session.exec(select(VerificationToken).where(VerificationToken.token == token)).first()
        assert token_row is not None
        assert token_row.used is True
        refreshed_session = auth_db_session.get(UserSession, user_session.id)
        assert refreshed_session is not None
        assert refreshed_session.revoked is True

    def test_reset_password_with_expired_token(self, auth_client: TestClient, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'reset-expired@example.com', 'Password123', 'Reset Expired User')
        token = create_verification_token(auth_db_session, user_id=user.id, token_type='password_reset', ttl_hours=-1)

        response = auth_client.post(
            '/api/v1/auth/reset-password',
            json={'token': token, 'new_password': 'Newpassword123'},
        )

        assert response.status_code == 400

    def test_reset_password_with_invalid_token(self, auth_client: TestClient) -> None:
        response = auth_client.post(
            '/api/v1/auth/reset-password',
            json={'token': 'invalid-token', 'new_password': 'Newpassword123'},
        )

        assert response.status_code == 400

    def test_reset_password_revokes_existing_sessions(self, auth_client: TestClient, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'reset-revoke@example.com', 'Password123', 'Reset Revoke User')
        first = create_session(auth_db_session, user.id, 'pytest-agent-1', '127.0.0.1')
        second = create_session(auth_db_session, user.id, 'pytest-agent-2', '127.0.0.2')
        token = create_verification_token(auth_db_session, user_id=user.id, token_type='password_reset', ttl_hours=1)

        response = auth_client.post(
            '/api/v1/auth/reset-password',
            json={'token': token, 'new_password': 'Anotherpass123'},
        )

        assert response.status_code == 200
        refreshed_first = auth_db_session.get(UserSession, first.id)
        refreshed_second = auth_db_session.get(UserSession, second.id)
        assert refreshed_first is not None
        assert refreshed_second is not None
        assert refreshed_first.revoked is True
        assert refreshed_second.revoked is True

    def test_google_oauth_start_sets_state_cookie(self, auth_client: TestClient) -> None:
        response = auth_client.get('/api/v1/auth/google', follow_redirects=False)

        assert response.status_code in {302, 307}
        location = response.headers.get('location', '')
        assert location.startswith('https://accounts.google.com/o/oauth2/v2/auth?')
        query = parse_qs(urlparse(location).query)
        assert 'state' in query
        assert query['state']
        state = query['state'][0]
        assert response.cookies.get('oauth_state_google') == state
        set_cookie = response.headers.get('set-cookie', '')
        assert 'oauth_state_google=' in set_cookie
        assert 'HttpOnly' in set_cookie
        assert 'SameSite=lax' in set_cookie

    def test_github_oauth_start_sets_state_cookie(self, auth_client: TestClient) -> None:
        response = auth_client.get('/api/v1/auth/github', follow_redirects=False)

        assert response.status_code in {302, 307}
        location = response.headers.get('location', '')
        assert location.startswith('https://github.com/login/oauth/authorize?')
        query = parse_qs(urlparse(location).query)
        assert 'state' in query
        assert query['state']
        state = query['state'][0]
        assert response.cookies.get('oauth_state_github') == state
        set_cookie = response.headers.get('set-cookie', '')
        assert 'oauth_state_github=' in set_cookie
        assert 'HttpOnly' in set_cookie
        assert 'SameSite=lax' in set_cookie

    def test_google_oauth_callback_requires_matching_state(self, auth_client: TestClient) -> None:
        start = auth_client.get('/api/v1/auth/google', follow_redirects=False)
        location = start.headers.get('location', '')
        query = parse_qs(urlparse(location).query)
        state = query['state'][0]

        mismatch = auth_client.get(
            f'/api/v1/auth/google/callback?code=test-code&state={state}-mismatch',
            follow_redirects=False,
        )

        assert mismatch.status_code == 400

    def test_github_oauth_callback_requires_state(self, auth_client: TestClient) -> None:
        missing = auth_client.get('/api/v1/auth/github/callback?code=test-code', follow_redirects=False)

        assert missing.status_code == 400

    def test_session_cookie_secure_flag_follows_debug(self, auth_client: TestClient, monkeypatch) -> None:
        monkeypatch.setattr('core.config.settings.debug', False)

        response = auth_client.post(
            '/api/v1/auth/register',
            json={
                'email': 'secure-cookie@example.com',
                'password': 'Password123',
                'display_name': 'Secure Cookie User',
            },
        )

        assert response.status_code == 200
        set_cookie = response.headers.get('set-cookie', '')
        assert 'session_token=' in set_cookie
        assert 'Secure' in set_cookie
        assert 'SameSite=lax' in set_cookie

    def test_verify_email_route_happy_path(self, auth_client: TestClient, auth_db_session: Session) -> None:
        user = create_user(auth_db_session, 'verify-route@example.com', 'Password123', 'Verify Route User')
        token = create_verification_token(auth_db_session, user_id=user.id, token_type='email_verify')

        response = auth_client.post('/api/v1/auth/verify-email', json={'token': token})

        assert response.status_code == 200
        assert response.json()['message'] == 'Email verified successfully'
        refreshed = get_user_by_id(auth_db_session, user.id)
        assert refreshed is not None
        assert refreshed.email_verified is True

    def test_resend_verification_route_happy_path(
        self,
        auth_client: TestClient,
        auth_db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = create_user(auth_db_session, 'resend-route@example.com', 'Password123', 'Resend Route User')
        user_session = create_session(auth_db_session, user.id, 'pytest-agent', '127.0.0.1')

        sent: list[tuple[str, str]] = []

        async def fake_send(email: str, token: str) -> bool:
            sent.append((email, token))
            return True

        monkeypatch.setattr('modules.auth.service.send_verification_email', fake_send)
        auth_client.cookies.set('session_token', user_session.id)

        response = auth_client.post('/api/v1/auth/resend-verification')

        assert response.status_code == 200
        assert response.json()['message'] == 'Verification email sent'
        assert len(sent) == 1
        assert sent[0][0] == user.email

    def test_resend_verification_rate_limit(
        self,
        auth_client: TestClient,
        auth_db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = create_user(auth_db_session, 'resend-limit@example.com', 'Password123', 'Resend Limit User')
        user_session = create_session(auth_db_session, user.id, 'pytest-agent', '127.0.0.1')
        monkeypatch.setattr('modules.auth.service.send_verification_email', send_verification_email)

        async def fake_send(*_args) -> bool:
            return True

        monkeypatch.setattr('modules.auth.service.send_verification_email', fake_send)
        auth_client.cookies.set('session_token', user_session.id)

        first = auth_client.post('/api/v1/auth/resend-verification')
        second = auth_client.post('/api/v1/auth/resend-verification')

        assert first.status_code == 200
        assert second.status_code == 400
