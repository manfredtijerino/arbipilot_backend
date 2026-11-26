"""The cryptography behind login: password hashes, tokens and reset codes.

Pure functions: nothing here talks to the database or the network.

- Passwords: Argon2id. Only the hash is ever stored.
- Access token: a signed JWT, valid 30 minutes, sent with every request.
- Refresh token: a long random string, valid 7 days. Only its SHA-256 is stored.
- Reset code: six digits. Only a keyed hash (HMAC) is stored, because a plain
  hash of six digits could be reversed in under a second.
"""

import asyncio
import hashlib
import hmac
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from config.settings import Settings

ACCESS_TOKEN_TTL = timedelta(minutes=30)
REFRESH_TOKEN_TTL = timedelta(days=7)
RESET_CODE_TTL = timedelta(minutes=10)
RESET_CODE_DIGITS = 6
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a label, not a secret

# Module-level so tests can swap in a cheaper one.
hasher = PasswordHasher()


class InvalidAccessToken(Exception):
    """The access token is missing, forged, expired or not an access token."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    issued_at: datetime


# --- Passwords ---


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# Argon2 is slow on purpose. It runs on these two threads so the rest of the
# app (later: the trading loop) keeps running, and so a flood of login
# requests can never run more than two hashes at once.
_hashing_threads = ThreadPoolExecutor(max_workers=2, thread_name_prefix="argon2")


async def hash_password_async(password: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_hashing_threads, hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _hashing_threads, verify_password, password_hash, password
    )


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with older, weaker settings."""
    return hasher.check_needs_rehash(password_hash)


async def burn_password_check(password: str) -> None:
    """Spend the time of a real check when there is no account to check.

    Without it, an unknown email would answer faster than a wrong password,
    and the difference would reveal which emails exist.
    """
    await verify_password_async(_decoy_hash(), password)


_decoy: str | None = None


def _decoy_hash() -> str:
    global _decoy
    if _decoy is None:
        _decoy = hash_password(secrets.token_urlsafe(16))
    return _decoy


# --- Access tokens ---


def create_access_token(settings: Settings, user_id: uuid.UUID, now: datetime) -> str:
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM
    )


def read_access_token(settings: Settings, token: str, now: datetime) -> AccessClaims:
    """Check the signature and the dates. Raises InvalidAccessToken."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],  # never trust the algorithm in the token
            # The dates are checked below against `now`, so tests control time.
            options={
                "require": ["sub", "iat", "exp", "type"],
                "verify_exp": False,
                "verify_iat": False,
            },
        )
        user_id = uuid.UUID(str(payload["sub"]))
        issued_at = datetime.fromtimestamp(int(payload["iat"]), UTC)
        expires_at = datetime.fromtimestamp(int(payload["exp"]), UTC)
    except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
        raise InvalidAccessToken from None
    if payload["type"] != ACCESS_TOKEN_TYPE or now >= expires_at:
        raise InvalidAccessToken
    return AccessClaims(user_id=user_id, issued_at=issued_at)


# --- Refresh tokens ---


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """A new token and its hash: the token for the caller, the hash for the database."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


# --- Reset codes ---


def new_reset_code() -> str:
    return f"{secrets.randbelow(10**RESET_CODE_DIGITS):0{RESET_CODE_DIGITS}d}"


def hash_reset_code(settings: Settings, user_id: uuid.UUID, code: str) -> str:
    key = settings.jwt_secret.get_secret_value().encode()
    message = f"password-reset:{user_id}:{code}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def reset_code_matches(expected_hash: str, actual_hash: str) -> bool:
    return hmac.compare_digest(expected_hash, actual_hash)


def format_reset_code(code: str) -> str:
    """493201 -> "493 201", easier to read on a phone."""
    half = len(code) // 2
    return f"{code[:half]} {code[half:]}"
