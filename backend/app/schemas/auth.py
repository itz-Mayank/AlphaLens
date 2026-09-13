import re

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.user import UserRead

_PASSWORD_MIN_LENGTH = 8


def _validate_password_strength(value: str) -> str:
    if len(value) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters.")
    if not re.search(r"[A-Za-z]", value):
        raise ValueError("Password must contain at least one letter.")
    if not re.search(r"\d", value):
        raise ValueError("Password must contain at least one number.")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = Field(min_length=1, max_length=200)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class DeleteAccountRequest(BaseModel):
    password: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead
