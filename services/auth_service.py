"""Login: register, log in, refresh, log out, change and reset the password.

Rules (docs/project-brief.md §8, owner decisions of 2026-11-24):
- One owner account. Registration closes for good once it exists.
- Wrong passwords cause growing waits: 1 s, 2 s, 4 s ... up to 15 minutes.
  A correct login or a password reset clears the wait.
- The reset code goes to the owner's Telegram: six digits, valid 10 minutes,
  usable once, cancelled after five wrong guesses.
- An unknown email and a wrong password get the same answer, including the
  growing waits.

Every operation that issues or cancels tokens first locks the owner's row, so
two of them never run at the same moment. Without that, a token handed out
while the password is being changed would survive the change.

Nothing here logs or returns an email, a password, a token or a code.
"""

import hashlib
import logging
import math
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta

from config.settings import Settings
from database.models import User
from database.repositories.errors import DuplicateRow
from database.repositories.store import Store
from services import clock, security
from services.errors import (
    InvalidCredentials,
    InvalidRefreshToken,
    InvalidResetCode,
    NotAuthenticated,
    RegistrationClosed,
    TooManyAttempts,
)

logger = logging.getLogger(__name__)

LONGEST_LOGIN_WAIT_SECONDS = 15 * 60
MAX_RESET_CODE_ATTEMPTS = 5
# How often a reset code can be asked for. The limits count every code, also
# used and cancelled ones: otherwise burning a code with wrong guesses would
# buy a fresh one at once, and six digits could be guessed in a few hours.
RESET_CODE_MIN_INTERVAL = timedelta(seconds=60)
RESET_CODES_PER_HOUR = 3
RESET_CODES_PER_DAY = 10
# With these limits a guesser gets at most 50 tries a day out of a million.


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int  # seconds until the access token stops working


def normalise_email(email: str) -> str:
    return email.strip().lower()


def _wait_for_failures(failures: int) -> int:
    """Seconds to wait after this many wrong tries in a row: 1, 2, 4 ... 900."""
    return min(2 ** min(failures - 1, 20), LONGEST_LOGIN_WAIT_SECONDS)


class UnknownEmailWaits:
    """Growing waits for emails that have no account.

    A real email answers "wait" after wrong passwords. If an unknown email
    never did, the difference would show which emails exist. So unknown emails
    get the same schedule, remembered here in memory (there is no row to put
    it in). Only a hash of the email is kept, and only the newest few.
    """

    MOST_EMAILS = 1024

    def __init__(self) -> None:
        self._rows: OrderedDict[str, tuple[int, datetime]] = OrderedDict()

    @staticmethod
    def _key(email: str) -> str:
        return hashlib.sha256(email.encode()).hexdigest()

    def seconds_to_wait(self, email: str, now: datetime) -> int:
        row = self._rows.get(self._key(email))
        if row is None or now >= row[1]:
            return 0
        return max(1, math.ceil((row[1] - now).total_seconds()))

    def record_failure(self, email: str, now: datetime) -> None:
        key = self._key(email)
        failures = self._rows.pop(key, (0, now))[0] + 1
        until = now + timedelta(seconds=_wait_for_failures(failures))
        self._rows[key] = (failures, until)
        while len(self._rows) > self.MOST_EMAILS:
            self._rows.popitem(last=False)  # forget the oldest

    def clear(self) -> None:
        self._rows.clear()


unknown_email_waits = UnknownEmailWaits()


def _seconds_to_wait(user: User, now: datetime) -> int:
    """How long login is still paused for this user. 0 when it is not."""
    if user.locked_until is None or now >= user.locked_until:
        return 0
    return max(1, math.ceil((user.locked_until - now).total_seconds()))


async def _issue_tokens(
    store: Store, settings: Settings, user: User, now: datetime
) -> TokenPair:
    refresh_token, refresh_hash = security.new_refresh_token()
    await store.tokens.add(user.id, refresh_hash, now + security.REFRESH_TOKEN_TTL)
    return TokenPair(
        access_token=security.create_access_token(settings, user.id, now),
        refresh_token=refresh_token,
        expires_in=int(security.ACCESS_TOKEN_TTL.total_seconds()),
    )


async def register(
    store: Store, email: str, password: str, display_name: str | None
) -> User:
    """Create the owner account. Works only while no account exists."""
    if await store.users.count() > 0:
        raise RegistrationClosed
    user = User(
        email=normalise_email(email),
        password_hash=await security.hash_password_async(password),
        display_name=display_name,
    )
    try:
        await store.users.add(user)
    except DuplicateRow:
        # Another request created the account a moment earlier.
        raise RegistrationClosed from None
    await store.commit()
    logger.info("owner account created")
    return user


async def login(
    store: Store, settings: Settings, email: str, password: str
) -> TokenPair:
    now = clock.utc_now()
    email = normalise_email(email)
    # Locked: a second login try for this user waits here until this one is
    # done, so many tries sent together are still judged one after the other.
    user = await store.users.get_by_email(email, lock=True)
    if user is None:
        wait = unknown_email_waits.seconds_to_wait(email, now)
        if wait:
            raise TooManyAttempts(wait)
        await security.burn_password_check(password)
        unknown_email_waits.record_failure(email, now)
        logger.warning("login refused reason=unknown_email")
        raise InvalidCredentials

    wait = _seconds_to_wait(user, now)
    if wait:
        # The password is not even looked at, and the wait does not grow.
        logger.warning("login refused reason=waiting seconds=%s", wait)
        raise TooManyAttempts(wait)

    if not await security.verify_password_async(user.password_hash, password):
        await store.users.record_failed_login(user.id, now, LONGEST_LOGIN_WAIT_SECONDS)
        await store.commit()
        logger.warning("login refused reason=wrong_password")
        raise InvalidCredentials

    await store.users.record_successful_login(user.id, now)
    if security.needs_rehash(user.password_hash):
        await store.users.upgrade_password_hash(
            user.id, await security.hash_password_async(password)
        )
    tokens = await _issue_tokens(store, settings, user, now)
    await store.commit()
    logger.info("login ok")
    return tokens


async def refresh(store: Store, settings: Settings, refresh_token: str) -> TokenPair:
    """Swap a refresh token for a new pair. Each refresh token works once."""
    now = clock.utc_now()
    row = await store.tokens.get_by_hash(security.hash_refresh_token(refresh_token))
    if row is None:
        raise InvalidRefreshToken
    if row.revoked_at is not None:
        # A cancelled token is being used again: it may have been stolen.
        # Cancel every token so both the thief and the owner must log in again.
        await store.tokens.revoke_all_for_user(row.user_id, now)
        await store.commit()
        logger.warning("refresh refused reason=reused_token all_tokens_cancelled")
        raise InvalidRefreshToken
    if now >= row.expires_at:
        raise InvalidRefreshToken
    # Locked, so a password change cannot slip in between "this token is
    # still good" and "here is its replacement". If a change got there first,
    # the cancel below finds the token already cancelled and refuses.
    user = await store.users.get_by_id(row.user_id, lock=True)
    if user is None or not await store.tokens.revoke(row.id, now):
        raise InvalidRefreshToken
    tokens = await _issue_tokens(store, settings, user, now)
    await store.commit()
    return tokens


async def logout(store: Store, user: User, refresh_token: str) -> None:
    """Cancel the refresh token. Says nothing if it was unknown or already cancelled."""
    row = await store.tokens.get_by_hash(security.hash_refresh_token(refresh_token))
    if row is not None and row.user_id == user.id:
        await store.tokens.revoke(row.id, clock.utc_now())
        await store.commit()


async def authenticate(store: Store, settings: Settings, access_token: str) -> User:
    """The user an access token belongs to. Raises NotAuthenticated."""
    try:
        claims = security.read_access_token(settings, access_token, clock.utc_now())
    except security.InvalidAccessToken:
        raise NotAuthenticated from None
    user = await store.users.get_by_id(claims.user_id)
    if user is None:
        raise NotAuthenticated
    # Tokens from before the last password change stop working. Both times are
    # whole seconds, so a token issued right after the change still works.
    changed = user.password_changed_at
    if changed is not None and claims.issued_at < changed.replace(microsecond=0):
        raise NotAuthenticated
    return user


async def _set_new_password(
    store: Store, user: User, new_password: str, now: datetime
) -> None:
    await store.users.set_password(
        user.id,
        await security.hash_password_async(new_password),
        now.replace(microsecond=0),
    )
    await store.tokens.revoke_all_for_user(user.id, now)


async def change_password(
    store: Store,
    settings: Settings,
    user: User,
    current_password: str,
    new_password: str,
) -> TokenPair:
    """Change the password while logged in. Every other session is logged out;
    the caller gets a fresh pair of tokens.

    The login wait is not applied here: the caller already holds a valid
    access token, and a stranger's wrong logins must not stop the owner from
    changing his password.
    """
    now = clock.utc_now()
    locked = await store.users.get_by_id(user.id, lock=True)
    if locked is None:
        raise NotAuthenticated
    if not await security.verify_password_async(locked.password_hash, current_password):
        logger.warning("password change refused reason=wrong_password")
        raise InvalidCredentials("The current password is wrong.")
    await _set_new_password(store, locked, new_password, now)
    tokens = await _issue_tokens(store, settings, locked, now)
    await store.commit()
    logger.info("password changed")
    return tokens


async def _may_issue_reset_code(store: Store, user: User, now: datetime) -> str | None:
    """None when a new code may be issued, otherwise the reason it may not."""
    latest = await store.codes.get_latest(user.id)
    if latest is not None and now - latest.created_at < RESET_CODE_MIN_INTERVAL:
        return "asked_too_soon"
    last_hour = await store.codes.count_since(user.id, now - timedelta(hours=1))
    if last_hour >= RESET_CODES_PER_HOUR:
        return "hourly_limit"
    last_day = await store.codes.count_since(user.id, now - timedelta(days=1))
    if last_day >= RESET_CODES_PER_DAY:
        return "daily_limit"
    return None


async def start_password_reset(
    store: Store, settings: Settings, email: str
) -> str | None:
    """Make a reset code. Returns the Telegram text to send, or None.

    The caller answers the same sentence either way, so the response never
    shows whether the email exists or whether a limit was hit.
    """
    now = clock.utc_now()
    user = await store.users.get_by_email(normalise_email(email), lock=True)
    if user is None:
        logger.warning("reset code not issued reason=unknown_email")
        return None
    refusal = await _may_issue_reset_code(store, user, now)
    if refusal is not None:
        logger.warning("reset code not issued reason=%s", refusal)
        return None
    await store.codes.cancel_live(user.id, now)
    code = security.new_reset_code()
    try:
        await store.codes.add(
            user.id,
            security.hash_reset_code(settings, user.id, code),
            now + security.RESET_CODE_TTL,
            now,
        )
    except DuplicateRow:
        logger.warning("reset code not issued reason=another_request_was_first")
        return None
    await store.commit()
    logger.info("reset code issued")
    minutes = int(security.RESET_CODE_TTL.total_seconds() // 60)
    return (
        f"Your ArbiPilot reset code is {security.format_reset_code(code)}. "
        f"It works for {minutes} minutes. "
        "If you did not ask for it, ignore this message."
    )


async def finish_password_reset(
    store: Store, settings: Settings, email: str, code: str, new_password: str
) -> None:
    """Set a new password using the code. Every session is logged out."""
    now = clock.utc_now()
    user = await store.users.get_by_email(normalise_email(email), lock=True)
    if user is None:
        raise InvalidResetCode
    live = await store.codes.get_live(user.id)
    if live is None or now >= live.expires_at:
        raise InvalidResetCode

    # Count the guess before looking at it, so parallel guesses all count.
    attempts = await store.codes.add_attempt(live.id)
    if attempts > MAX_RESET_CODE_ATTEMPTS:
        await store.codes.mark_used(live.id, now)
        await store.commit()
        logger.warning("reset refused reason=too_many_guesses code_cancelled")
        raise InvalidResetCode
    given = security.hash_reset_code(settings, user.id, code)
    if not security.reset_code_matches(live.code_hash, given):
        await store.commit()
        logger.warning("reset refused reason=wrong_code")
        raise InvalidResetCode
    if not await store.codes.mark_used(live.id, now):
        await store.commit()  # keep the counted guess
        raise InvalidResetCode  # used a moment ago by another request

    await _set_new_password(store, user, new_password, now)
    await store.commit()
    logger.info("password reset with a code")
