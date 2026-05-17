from __future__ import annotations

from core.exceptions import AppError


class AuthError(AppError):
    """Base exception for backend authentication errors."""


class InvalidCredentialsError(AuthError):
    def __init__(self):
        super().__init__(message="Invalid email or password", error_code="INVALID_CREDENTIALS")


class EmailAlreadyExistsError(AuthError):
    def __init__(self):
        super().__init__(
            message="Email address is already registered",
            error_code="EMAIL_ALREADY_EXISTS",
        )


class SessionExpiredError(AuthError):
    def __init__(self):
        super().__init__(message="Session is invalid or expired", error_code="SESSION_EXPIRED")


class AccountDisabledError(AuthError):
    def __init__(self):
        super().__init__(message="Account is disabled", error_code="ACCOUNT_DISABLED")


class DefaultUserDeletionError(AuthError):
    def __init__(self):
        super().__init__(
            message="The default account cannot be deleted",
            error_code="DEFAULT_USER_DELETION_FORBIDDEN",
        )


class ProviderUnlinkError(AuthError):
    def __init__(self, message: str = "Cannot unlink the last login method"):
        super().__init__(message=message, error_code="PROVIDER_UNLINK_ERROR")


class OAuthError(AuthError):
    def __init__(self, message: str = "OAuth authentication failed"):
        super().__init__(message=message, error_code="OAUTH_ERROR")


class TokenExpiredError(AuthError):
    def __init__(self):
        super().__init__(message="Token has expired", error_code="TOKEN_EXPIRED")


class TokenInvalidError(AuthError):
    def __init__(self):
        super().__init__(message="Token is invalid", error_code="TOKEN_INVALID")
