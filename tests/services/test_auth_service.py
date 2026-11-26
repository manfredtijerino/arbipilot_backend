"""The login rules, on an in-memory store. No database, no network."""

from collections.abc import Callable
from datetime import timedelta

import pytest

from config.settings import Settings
from services import auth_service, security
from services.errors import (
    InvalidCredentials,
    InvalidRefreshToken,
    InvalidResetCode,
    NotAuthenticated,
    RegistrationClosed,
    TooManyAttempts,
)
from tests.conftest import FakeClock
from tests.helpers.memory_store import MemoryStore

EMAIL = "owner@example.test"
PASSWORD = "test-password-123"
NEW_PASSWORD = "new-test-password-456"


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture
def store(fake_clock: FakeClock) -> MemoryStore:
    return MemoryStore()


@pytest.fixture
async def owner(store: MemoryStore):
    return await auth_service.register(store, EMAIL, PASSWORD, "Owner")


def code_from(text: str) -> str:
    """The six digits out of the Telegram message."""
    digits = "".join(ch for ch in text.split(" is ")[1].split(".")[0] if ch.isdigit())
    assert len(digits) == 6
    return digits


async def wrong_login(store: MemoryStore, settings: Settings) -> None:
    with pytest.raises(InvalidCredentials):
        await auth_service.login(store, settings, EMAIL, "wrong-password")


# --- Register ---


async def test_register_creates_the_owner_with_a_hashed_password(
    store: MemoryStore,
) -> None:
    user = await auth_service.register(store, "  Owner@Example.Test ", PASSWORD, None)
    assert user.email == EMAIL  # stored in lowercase, without spaces
    assert user.password_hash != PASSWORD
    assert security.verify_password(user.password_hash, PASSWORD)
    assert store.commits == 1


async def test_registration_closes_once_the_owner_exists(
    store: MemoryStore, owner
) -> None:
    with pytest.raises(RegistrationClosed):
        await auth_service.register(store, "stranger@example.test", PASSWORD, None)
    assert await store.users.count() == 1


async def test_two_registrations_at_once_create_one_account(
    store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both requests saw "no account yet"; the table refuses the second row.
    async def nobody_yet() -> int:
        return 0

    await auth_service.register(store, EMAIL, PASSWORD, None)
    monkeypatch.setattr(store.users, "count", nobody_yet)
    with pytest.raises(RegistrationClosed):
        await auth_service.register(store, "stranger@example.test", PASSWORD, None)


# --- Login ---


async def test_login_returns_a_working_pair_of_tokens(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    tokens = await auth_service.login(store, settings, "OWNER@example.test", PASSWORD)
    assert tokens.expires_in == 30 * 60
    user = await auth_service.authenticate(store, settings, tokens.access_token)
    assert user.id == owner.id
    assert owner.last_login_at == fake_clock.now
    # Only the hash of the refresh token is stored.
    stored = store.tokens.rows[0]
    assert stored.token_hash == security.hash_refresh_token(tokens.refresh_token)
    assert stored.expires_at == fake_clock.now + timedelta(days=7)


async def test_wrong_password_and_unknown_email_get_the_same_answer(
    store: MemoryStore, settings: Settings, owner
) -> None:
    with pytest.raises(InvalidCredentials) as wrong:
        await auth_service.login(store, settings, EMAIL, "wrong-password")
    with pytest.raises(InvalidCredentials) as unknown:
        await auth_service.login(store, settings, "nobody@example.test", PASSWORD)
    assert wrong.value.message == unknown.value.message
    assert wrong.value.status_code == unknown.value.status_code == 401


async def test_wrong_passwords_cause_growing_waits(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    waits = []
    for _ in range(5):
        await wrong_login(store, settings)
        waits.append((owner.locked_until - fake_clock.now).total_seconds())
        fake_clock.now = owner.locked_until  # wait it out
    assert waits == [1, 2, 4, 8, 16]


async def test_the_wait_never_exceeds_15_minutes(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    for _ in range(14):
        await wrong_login(store, settings)
        fake_clock.now = owner.locked_until
    await wrong_login(store, settings)
    assert owner.locked_until - fake_clock.now == timedelta(minutes=15)


async def test_during_a_wait_even_the_right_password_is_refused(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    for _ in range(3):
        await wrong_login(store, settings)
        fake_clock.now = owner.locked_until
    await wrong_login(store, settings)  # now waiting 8 s
    with pytest.raises(TooManyAttempts) as refused:
        await auth_service.login(store, settings, EMAIL, PASSWORD)
    assert refused.value.status_code == 429
    assert refused.value.retry_after_seconds == 8


async def test_tries_during_a_wait_do_not_make_it_longer(
    store: MemoryStore, settings: Settings, owner
) -> None:
    await wrong_login(store, settings)
    until, count = owner.locked_until, owner.failed_login_count
    for _ in range(10):
        with pytest.raises(TooManyAttempts):
            await auth_service.login(store, settings, EMAIL, "wrong-password")
    assert (owner.locked_until, owner.failed_login_count) == (until, count)


async def test_a_correct_login_after_the_wait_clears_the_count(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    await wrong_login(store, settings)
    fake_clock.now = owner.locked_until
    await auth_service.login(store, settings, EMAIL, PASSWORD)
    assert owner.failed_login_count == 0 and owner.locked_until is None


# --- Access tokens ---


async def test_an_expired_access_token_is_refused(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    tokens = await auth_service.login(store, settings, EMAIL, PASSWORD)
    fake_clock.advance(minutes=30)
    with pytest.raises(NotAuthenticated):
        await auth_service.authenticate(store, settings, tokens.access_token)


async def test_a_token_for_a_user_that_no_longer_exists_is_refused(
    store: MemoryStore, settings: Settings, owner
) -> None:
    tokens = await auth_service.login(store, settings, EMAIL, PASSWORD)
    store.users.rows.clear()
    with pytest.raises(NotAuthenticated):
        await auth_service.authenticate(store, settings, tokens.access_token)


async def test_a_refresh_token_is_not_an_access_token(
    store: MemoryStore, settings: Settings, owner
) -> None:
    tokens = await auth_service.login(store, settings, EMAIL, PASSWORD)
    with pytest.raises(NotAuthenticated):
        await auth_service.authenticate(store, settings, tokens.refresh_token)


# --- Refresh ---


async def test_refresh_gives_a_new_pair_and_uses_up_the_old_token(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    first = await auth_service.login(store, settings, EMAIL, PASSWORD)
    fake_clock.advance(minutes=31)
    second = await auth_service.refresh(store, settings, first.refresh_token)
    assert second.refresh_token != first.refresh_token
    user = await auth_service.authenticate(store, settings, second.access_token)
    assert user.id == owner.id
    assert len(store.tokens.live()) == 1


async def test_using_a_refresh_token_twice_logs_everyone_out(
    store: MemoryStore, settings: Settings, owner
) -> None:
    first = await auth_service.login(store, settings, EMAIL, PASSWORD)
    second = await auth_service.refresh(store, settings, first.refresh_token)
    with pytest.raises(InvalidRefreshToken):
        await auth_service.refresh(store, settings, first.refresh_token)
    # The newer token is cancelled too: the old one may have been stolen.
    assert store.tokens.live() == []
    with pytest.raises(InvalidRefreshToken):
        await auth_service.refresh(store, settings, second.refresh_token)


async def test_a_refresh_token_stops_working_after_7_days(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    tokens = await auth_service.login(store, settings, EMAIL, PASSWORD)
    fake_clock.advance(days=7)
    with pytest.raises(InvalidRefreshToken):
        await auth_service.refresh(store, settings, tokens.refresh_token)


async def test_an_unknown_refresh_token_is_refused(
    store: MemoryStore, settings: Settings, owner
) -> None:
    with pytest.raises(InvalidRefreshToken):
        await auth_service.refresh(store, settings, "made-up-token")


# --- Logout ---


async def test_logout_cancels_the_refresh_token(
    store: MemoryStore, settings: Settings, owner
) -> None:
    tokens = await auth_service.login(store, settings, EMAIL, PASSWORD)
    await auth_service.logout(store, owner, tokens.refresh_token)
    assert store.tokens.live() == []
    with pytest.raises(InvalidRefreshToken):
        await auth_service.refresh(store, settings, tokens.refresh_token)


async def test_logout_with_an_unknown_token_does_nothing(
    store: MemoryStore, settings: Settings, owner
) -> None:
    tokens = await auth_service.login(store, settings, EMAIL, PASSWORD)
    await auth_service.logout(store, owner, "made-up-token")
    assert len(store.tokens.live()) == 1
    await auth_service.refresh(store, settings, tokens.refresh_token)


# --- Change password ---


async def test_change_password_swaps_it_and_logs_out_old_sessions(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    old = await auth_service.login(store, settings, EMAIL, PASSWORD)
    fake_clock.advance(minutes=5)
    new = await auth_service.change_password(
        store, settings, owner, PASSWORD, NEW_PASSWORD
    )
    # The old tokens stop working, the new ones work.
    with pytest.raises(NotAuthenticated):
        await auth_service.authenticate(store, settings, old.access_token)
    with pytest.raises(InvalidRefreshToken):
        await auth_service.refresh(store, settings, old.refresh_token)
    assert (await auth_service.authenticate(store, settings, new.access_token)).id
    # Only the new password logs in.
    await wrong_login_with(store, settings, PASSWORD)
    fake_clock.now = owner.locked_until
    await auth_service.login(store, settings, EMAIL, NEW_PASSWORD)


async def wrong_login_with(
    store: MemoryStore, settings: Settings, password: str
) -> None:
    with pytest.raises(InvalidCredentials):
        await auth_service.login(store, settings, EMAIL, password)


async def test_a_token_from_the_same_second_as_the_change_still_works(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    fake_clock.now = fake_clock.now.replace(microsecond=900_000)
    new = await auth_service.change_password(
        store, settings, owner, PASSWORD, NEW_PASSWORD
    )
    assert (await auth_service.authenticate(store, settings, new.access_token)).id


async def test_change_password_needs_the_current_password(
    store: MemoryStore, settings: Settings, owner
) -> None:
    with pytest.raises(InvalidCredentials):
        await auth_service.change_password(
            store, settings, owner, "wrong-password", NEW_PASSWORD
        )
    assert security.verify_password(owner.password_hash, PASSWORD)
    # It does not touch the login wait: that belongs to the login door.
    assert owner.failed_login_count == 0 and owner.locked_until is None


async def test_a_login_wait_does_not_stop_the_owner_changing_the_password(
    store: MemoryStore, settings: Settings, owner
) -> None:
    # A stranger's wrong logins must not block the logged-in owner.
    await wrong_login(store, settings)
    assert owner.locked_until is not None
    await auth_service.change_password(store, settings, owner, PASSWORD, NEW_PASSWORD)
    assert security.verify_password(owner.password_hash, NEW_PASSWORD)


# --- Forgot / reset ---


async def test_reset_with_the_code_sets_a_new_password(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    old = await auth_service.login(store, settings, EMAIL, PASSWORD)
    text = await auth_service.start_password_reset(store, settings, EMAIL)
    assert "10 minutes" in text
    code = code_from(text)
    assert code not in store.codes.rows[0].code_hash  # only a hash is stored

    fake_clock.advance(minutes=9)
    await auth_service.finish_password_reset(store, settings, EMAIL, code, NEW_PASSWORD)
    await auth_service.login(store, settings, EMAIL, NEW_PASSWORD)
    with pytest.raises(InvalidRefreshToken):
        await auth_service.refresh(store, settings, old.refresh_token)


async def test_a_reset_clears_a_login_wait(
    store: MemoryStore, settings: Settings, owner
) -> None:
    await wrong_login(store, settings)
    code = code_from(await auth_service.start_password_reset(store, settings, EMAIL))
    await auth_service.finish_password_reset(store, settings, EMAIL, code, NEW_PASSWORD)
    await auth_service.login(store, settings, EMAIL, NEW_PASSWORD)  # no wait left


async def test_an_unknown_email_gets_no_code(
    store: MemoryStore, settings: Settings, owner
) -> None:
    text = await auth_service.start_password_reset(
        store, settings, "nobody@example.test"
    )
    assert text is None and store.codes.rows == []


async def test_a_code_works_once(store: MemoryStore, settings: Settings, owner) -> None:
    code = code_from(await auth_service.start_password_reset(store, settings, EMAIL))
    await auth_service.finish_password_reset(store, settings, EMAIL, code, NEW_PASSWORD)
    with pytest.raises(InvalidResetCode):
        await auth_service.finish_password_reset(store, settings, EMAIL, code, PASSWORD)


async def test_a_code_stops_working_after_10_minutes(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    code = code_from(await auth_service.start_password_reset(store, settings, EMAIL))
    fake_clock.advance(minutes=10)
    with pytest.raises(InvalidResetCode):
        await auth_service.finish_password_reset(
            store, settings, EMAIL, code, NEW_PASSWORD
        )


async def test_five_wrong_guesses_cancel_the_code(
    store: MemoryStore, settings: Settings, owner
) -> None:
    code = code_from(await auth_service.start_password_reset(store, settings, EMAIL))
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(InvalidResetCode):
            await auth_service.finish_password_reset(
                store, settings, EMAIL, wrong, NEW_PASSWORD
            )
    # The sixth try is refused even with the right code.
    with pytest.raises(InvalidResetCode):
        await auth_service.finish_password_reset(
            store, settings, EMAIL, code, NEW_PASSWORD
        )
    assert security.verify_password(owner.password_hash, PASSWORD)


async def test_a_new_code_cannot_be_asked_for_within_a_minute(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    first = await auth_service.start_password_reset(store, settings, EMAIL)
    fake_clock.advance(seconds=59)
    assert await auth_service.start_password_reset(store, settings, EMAIL) is None
    fake_clock.advance(seconds=1)
    second = await auth_service.start_password_reset(store, settings, EMAIL)
    assert second is not None
    # The newer code replaced the older one.
    with pytest.raises(InvalidResetCode):
        await auth_service.finish_password_reset(
            store, settings, EMAIL, code_from(first), NEW_PASSWORD
        )
    assert len([row for row in store.codes.rows if row.used_at is None]) == 1


async def test_every_reset_failure_gets_the_same_answer(
    store: MemoryStore, settings: Settings, owner
) -> None:
    await auth_service.start_password_reset(store, settings, EMAIL)
    with pytest.raises(InvalidResetCode) as wrong_code:
        await auth_service.finish_password_reset(
            store, settings, EMAIL, "000000", NEW_PASSWORD
        )
    with pytest.raises(InvalidResetCode) as unknown_email:
        await auth_service.finish_password_reset(
            store, settings, "nobody@example.test", "000000", NEW_PASSWORD
        )
    assert wrong_code.value.message == unknown_email.value.message


# --- Limits on asking for codes (a code must not be guessable by asking again) ---


async def burn_code(store: MemoryStore, settings: Settings) -> None:
    """Six wrong guesses: the code is cancelled."""
    for _ in range(6):
        with pytest.raises(InvalidResetCode):
            await auth_service.finish_password_reset(
                store, settings, EMAIL, "000000", NEW_PASSWORD
            )


async def test_burning_a_code_does_not_buy_a_new_one_at_once(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    first = await auth_service.start_password_reset(store, settings, EMAIL)
    if code_from(first) == "000000":  # one chance in a million
        pytest.skip("the random code equals the wrong guess used here")
    await burn_code(store, settings)
    assert await store.codes.get_live(owner.id) is None
    # No unused code is left, yet the one-minute rule still holds.
    fake_clock.advance(seconds=30)
    assert await auth_service.start_password_reset(store, settings, EMAIL) is None
    fake_clock.advance(seconds=30)
    assert await auth_service.start_password_reset(store, settings, EMAIL) is not None


async def test_at_most_three_codes_an_hour(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    for _ in range(3):
        assert await auth_service.start_password_reset(store, settings, EMAIL)
        fake_clock.advance(minutes=2)
    assert await auth_service.start_password_reset(store, settings, EMAIL) is None
    fake_clock.advance(minutes=55)  # the first code is now over an hour old
    assert await auth_service.start_password_reset(store, settings, EMAIL)


async def test_at_most_ten_codes_a_day(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    issued = 0
    for _ in range(40):  # one request every 30 minutes for 20 hours
        if await auth_service.start_password_reset(store, settings, EMAIL):
            issued += 1
        fake_clock.advance(minutes=30)
    assert issued == 10
    assert len(store.codes.rows) == 10


async def test_two_code_requests_at_once_issue_one_code(
    store: MemoryStore, settings: Settings, owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The second request lost the race: the table refused its code.
    from database.repositories.errors import DuplicateRow

    async def refused(*args: object) -> None:
        raise DuplicateRow

    monkeypatch.setattr(store.codes, "add", refused)
    assert await auth_service.start_password_reset(store, settings, EMAIL) is None


# --- An unknown email behaves like a real one ---


async def test_an_unknown_email_gets_the_same_growing_waits(
    store: MemoryStore, settings: Settings, owner, fake_clock: FakeClock
) -> None:
    unknown = "nobody@example.test"
    waits = []
    for _ in range(4):
        with pytest.raises(InvalidCredentials):
            await auth_service.login(store, settings, unknown, "wrong-password")
        with pytest.raises(TooManyAttempts) as refused:
            await auth_service.login(store, settings, unknown, "wrong-password")
        waits.append(refused.value.retry_after_seconds)
        fake_clock.advance(seconds=refused.value.retry_after_seconds)
    assert waits == [1, 2, 4, 8]
    # And it never touched the real account.
    assert owner.failed_login_count == 0


def test_the_memory_of_unknown_emails_is_bounded(fake_clock: FakeClock) -> None:
    waits = auth_service.UnknownEmailWaits()
    for number in range(waits.MOST_EMAILS + 50):
        waits.record_failure(f"nobody{number}@example.test", fake_clock.now)
    assert len(waits._rows) == waits.MOST_EMAILS
    assert waits.seconds_to_wait("nobody0@example.test", fake_clock.now) == 0
    newest = f"nobody{waits.MOST_EMAILS + 49}@example.test"
    assert waits.seconds_to_wait(newest, fake_clock.now) == 1
