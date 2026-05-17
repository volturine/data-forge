from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from modules.auth.models import AuthProviderName, UserStatus


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    avatar_url: str | None
    status: UserStatus
    email_verified: bool
    has_password: bool
    preferences: dict[str, object]
    providers: list[AuthProviderName]
    created_at: datetime


class UpdateProfileRequest(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None
    preferences: dict[str, object] | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class VerifyEmailRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class MessageResponse(BaseModel):
    message: str


class OAuthCallbackParams(BaseModel):
    code: str
    state: str | None = None


class ErrorResponse(BaseModel):
    error: str
    error_code: str
    details: dict[str, object] = Field(default_factory=dict)
