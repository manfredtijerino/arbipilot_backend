"""`/auth`: register, log in, refresh, log out, change and reset the password.

Thin routes: each one checks the input shape, calls `services/auth_service.py`
and returns the response shape.
"""

from fastapi import APIRouter, BackgroundTasks, Response, status

from api.dependencies import CurrentUser, SettingsDep, StoreDep
from api.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from api.schemas.users import UserResponse
from services import auth_service
from services.auth_service import TokenPair
from telegram_bot.alerts import send_reset_code

router = APIRouter(prefix="/auth", tags=["Login"])

FORGOT_ANSWER = "If the account exists, a code was sent to the owner's Telegram."
RESET_ANSWER = "The password was changed. Log in with the new one."


def _tokens(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(body: RegisterRequest, store: StoreDep) -> UserResponse:
    """Create the owner account. Works once; afterwards it answers 409."""
    user = await auth_service.register(
        store, body.email, body.password, body.display_name
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, store: StoreDep, settings: SettingsDep
) -> TokenResponse:
    """Check the email and password; return an access and a refresh token."""
    return _tokens(await auth_service.login(store, settings, body.email, body.password))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, store: StoreDep, settings: SettingsDep
) -> TokenResponse:
    """Swap a refresh token for a new pair. Each refresh token works once."""
    return _tokens(await auth_service.refresh(store, settings, body.refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, user: CurrentUser, store: StoreDep) -> Response:
    """Cancel the refresh token. Needs login."""
    await auth_service.logout(store, user, body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/change", response_model=TokenResponse)
async def change_password(
    body: ChangePasswordRequest,
    user: CurrentUser,
    store: StoreDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Change the password while logged in. Other sessions are logged out."""
    pair = await auth_service.change_password(
        store, settings, user, body.current_password, body.new_password
    )
    return _tokens(pair)


@router.post("/password/forgot", response_model=MessageResponse)
async def forgot_password(
    body: ForgotPasswordRequest,
    store: StoreDep,
    settings: SettingsDep,
    background: BackgroundTasks,
) -> MessageResponse:
    """Send a one-time reset code to the owner's Telegram.

    The answer is the same whether or not the email exists. The message is
    sent after the answer, so the response time gives nothing away either.
    """
    text = await auth_service.start_password_reset(store, settings, body.email)
    if text is not None:
        background.add_task(send_reset_code, settings, text)
    return MessageResponse(message=FORGOT_ANSWER)


@router.post("/password/reset", response_model=MessageResponse)
async def reset_password(
    body: ResetPasswordRequest, store: StoreDep, settings: SettingsDep
) -> MessageResponse:
    """Set a new password using the code from Telegram."""
    await auth_service.finish_password_reset(
        store, settings, body.email, body.code, body.new_password
    )
    return MessageResponse(message=RESET_ANSWER)
