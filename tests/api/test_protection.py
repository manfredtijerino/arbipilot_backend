"""Hard rule 12: every endpoint needs login, except a short written list.

This test walks every route the app has. A new endpoint that forgets the
"must be logged in" check makes it fail.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

# The only routes that may answer without a token, and why.
PUBLIC = {
    ("GET", "/api/v1/health"),  # is the app alive
    ("GET", "/api/v1/health/ready"),  # is everything connected
    ("POST", "/api/v1/auth/register"),  # no account exists yet
    ("POST", "/api/v1/auth/login"),  # this is how a token is obtained
    ("POST", "/api/v1/auth/refresh"),  # proves itself with the refresh token
    ("POST", "/api/v1/auth/password/forgot"),  # the owner cannot log in
    ("POST", "/api/v1/auth/password/reset"),  # proves itself with the code
}


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def all_routes(app: FastAPI) -> set[tuple[str, str]]:
    """Every (method, path) the app serves, read from its own description.

    The description page is switched off for callers (`/openapi.json` is 404),
    but the app can still produce it for this test.
    """
    return {
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        for method in methods
        if method in HTTP_METHODS
    }


def test_every_route_outside_the_public_list_refuses_a_request_without_a_token(
    app: FastAPI, client: TestClient
) -> None:
    protected = all_routes(app) - PUBLIC
    assert protected, "expected at least one protected route"
    for method, path in sorted(protected):
        response = client.request(method, path, json={})
        assert response.status_code == 401, f"{method} {path} answered without a token"
        assert response.json()["error"]["code"] == "not_authenticated"


def test_the_public_list_names_only_routes_that_exist(app: FastAPI) -> None:
    # A stale entry here would hide a mistake, so the list must stay exact.
    assert PUBLIC <= all_routes(app)
