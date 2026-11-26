"""Request and response shapes for `/auth`."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PASSWORD_MIN_LENGTH = 12
# A cap, so nobody can make the server hash a megabyte of text.
PASSWORD_MAX_LENGTH = 128
EMAIL_MAX_LENGTH = 320
EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

Password = Annotated[
    str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
]
# For checking an existing password: any length up to the cap.
GivenPassword = Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]


class Request(BaseModel):
    """Unknown fields are refused, so a typo in a field name is noticed."""

    model_config = ConfigDict(extra="forbid")


class WithEmail(Request):
    email: Annotated[str, Field(max_length=EMAIL_MAX_LENGTH)]

    @field_validator("email")
    @classmethod
    def _looks_like_an_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_SHAPE.fullmatch(value):
            raise ValueError("must look like name@example.com")
        return value


class RegisterRequest(WithEmail):
    password: Password
    display_name: Annotated[str | None, Field(max_length=100)] = None


class LoginRequest(WithEmail):
    password: GivenPassword


class RefreshRequest(Request):
    refresh_token: Annotated[str, Field(min_length=1, max_length=512)]


class LogoutRequest(RefreshRequest):
    pass


class ChangePasswordRequest(Request):
    current_password: GivenPassword
    new_password: Password


class ForgotPasswordRequest(WithEmail):
    pass


class ResetPasswordRequest(WithEmail):
    # Six digits; a space in the middle (as shown in Telegram) is accepted.
    code: Annotated[str, Field(max_length=16)]
    new_password: Password

    @field_validator("code")
    @classmethod
    def _six_digits(cls, value: str) -> str:
        value = value.replace(" ", "")
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError("must be the six digits from Telegram")
        return value


class TokenResponse(BaseModel):
    """The two tokens. `expires_in` is the access token's life in seconds."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class MessageResponse(BaseModel):
    message: str
