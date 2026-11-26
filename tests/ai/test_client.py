"""Claude API connection check. The client is a fake; no network, no tokens."""

from collections.abc import Callable

import anthropic
import httpx
import pytest

from ai.client import AICheckError, check_claude
from config.settings import Settings


class _FakeModels:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.asked_for: list[str] = []

    async def retrieve(self, model: str) -> object:
        self.asked_for.append(model)
        if self.error:
            raise self.error
        return object()


class _FakeClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.models = _FakeModels(error)


def status_error(kind: type[anthropic.APIStatusError], code: int) -> Exception:
    request = httpx.Request("GET", "https://anthropic.test.invalid/v1/models/x")
    return kind("x", response=httpx.Response(code, request=request), body=None)


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(anthropic_api_key="test-key", anthropic_model="test-model")


async def test_looks_up_the_configured_model(settings: Settings) -> None:
    client = _FakeClient()
    assert await check_claude(settings, client) == "test-model"
    assert client.models.asked_for == ["test-model"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (status_error(anthropic.AuthenticationError, 401), "key was refused"),
        (status_error(anthropic.NotFoundError, 404), "test-model is not in"),
        (status_error(anthropic.RateLimitError, 429), "status 429"),
        (status_error(anthropic.PermissionDeniedError, 403), "not allowed"),
        (status_error(anthropic.InternalServerError, 529), "status 529"),
        (anthropic.AnthropicError("odd"), r"check failed \(AnthropicError\)"),
        (ValueError("unreadable body"), r"check failed \(ValueError\)"),
        (
            anthropic.APIConnectionError(
                request=httpx.Request("GET", "https://anthropic.test.invalid")
            ),
            "could not reach",
        ),
        (
            anthropic.APITimeoutError(
                request=httpx.Request("GET", "https://anthropic.test.invalid")
            ),
            "in time",
        ),
    ],
)
async def test_each_failure_gets_a_plain_reason(
    settings: Settings, error: Exception, expected: str
) -> None:
    with pytest.raises(AICheckError, match=expected) as caught:
        await check_claude(settings, _FakeClient(error))
    assert "test-key" not in str(caught.value)


@pytest.mark.parametrize(
    ("overrides", "key"),
    [
        ({"anthropic_model": "test-model"}, "ANTHROPIC_API_KEY"),
        ({"anthropic_api_key": "test-key"}, "ANTHROPIC_MODEL"),
    ],
)
async def test_missing_setting_fails_without_calling(
    make_settings: Callable[..., Settings], overrides: dict, key: str
) -> None:
    client = _FakeClient()
    with pytest.raises(AICheckError, match=key):
        await check_claude(make_settings(**overrides), client)
    assert client.models.asked_for == []
