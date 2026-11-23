"""The map of the API: every route group is registered here, under `/api/v1`.

Every group except health must require login (added with the login work).
"""

from fastapi import APIRouter

from api.routes import health

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX)

# No login needed.
api_router.include_router(health.router)
