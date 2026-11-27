"""The map of the API: every route group is registered here, under `/api/v1`.

Every route needs a valid access token, except:
- the two health routes, and
- the five `/auth` routes that exist to get a token in the first place
  (register, login, refresh, forgot and reset password).
`tests/api/test_protection.py` fails if any other route answers without one.
"""

from fastapi import APIRouter

from api.routes import auth, health, integrations, market, users

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX)

# No login needed.
api_router.include_router(health.router)

# Login. Each route in here that needs a token asks for it itself.
api_router.include_router(auth.router)

# Login needed for everything below.
api_router.include_router(users.router)
api_router.include_router(integrations.router)
api_router.include_router(market.router)
