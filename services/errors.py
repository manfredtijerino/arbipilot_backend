"""Errors the services raise on purpose. The API turns each into the one error shape.

Every message here is written by us and is safe to show the caller.
"""


class ServiceError(Exception):
    """A request was refused for a reason the caller may be told."""

    status_code = 400
    code = "bad_request"
    message = "The request could not be completed."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.retry_after_seconds: int | None = None


class NotAuthenticated(ServiceError):
    status_code = 401
    code = "not_authenticated"
    message = "Log in first."


class InvalidCredentials(ServiceError):
    # The same answer for a wrong password and for an unknown email, so nobody
    # can find out which emails exist.
    status_code = 401
    code = "invalid_credentials"
    message = "The email or password is wrong."


class InvalidRefreshToken(ServiceError):
    status_code = 401
    code = "invalid_refresh_token"
    message = "The refresh token is not valid. Log in again."


class RegistrationClosed(ServiceError):
    status_code = 409
    code = "registration_closed"
    message = "The owner account already exists."


class InvalidResetCode(ServiceError):
    # One answer for every reason a reset can fail (unknown email, wrong,
    # expired or used code), so a guesser learns nothing from it.
    status_code = 400
    code = "invalid_reset_code"
    message = "The code is wrong or has expired. Ask for a new one."


class TooManyAttempts(ServiceError):
    status_code = 429
    code = "too_many_attempts"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            f"Too many wrong attempts. Try again in {retry_after_seconds} seconds."
        )
        self.retry_after_seconds = retry_after_seconds


class TooManyRequests(ServiceError):
    """The same check was asked for again too soon."""

    status_code = 429
    code = "too_many_requests"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            f"This was done a moment ago. Try again in {retry_after_seconds} seconds."
        )
        self.retry_after_seconds = retry_after_seconds


class DatabaseUnavailable(ServiceError):
    status_code = 503
    code = "database_unavailable"
    message = "The database cannot be reached right now. Try again shortly."


class PauseNotSaved(ServiceError):
    """The stop button was pressed while the database could not be reached."""

    status_code = 503
    code = "pause_not_saved"
    message = (
        "Trading is paused now, but the pause could not be saved: a restart "
        "would forget it. Press kill again in a moment."
    )


class UnknownSymbol(ServiceError):
    status_code = 404
    code = "unknown_symbol"
    message = "This pair is not on the watch list."


class MarketNotReady(ServiceError):
    """The market data asked for has not arrived yet."""

    status_code = 503
    code = "market_not_ready"
    message = "Market data is not ready yet. Try again in a few seconds."
