"""What a route can ask for: a database conversation, and the logged-in user.

`current_user` is the "must be logged in" check. Every route outside health
and the token-getting `/auth` routes depends on it.
"""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import DBAPIError

from config.database import get_engine, session_factory
from config.settings import Settings
from database.models import User
from database.repositories.store import Store
from services import auth_service
from services.errors import DatabaseUnavailable, NotAuthenticated

logger = logging.getLogger(__name__)

# auto_error=False: a missing header is answered by us, in the one error shape.
_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_store(request: Request) -> AsyncIterator[Store]:
    """One database session per request. Unsaved work is dropped when it ends."""
    state = request.app.state
    if state.sessions is None:
        state.sessions = session_factory(get_engine(state.settings))
    async with state.sessions() as session:
        yield Store(session)


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    store: Annotated[Store, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """The owner, proven by the access token in the Authorization header."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise NotAuthenticated
    try:
        return await auth_service.authenticate(store, settings, credentials.credentials)
    except (DBAPIError, OSError, TimeoutError) as exc:
        # Looking the owner up needs the database. When it is down, say so
        # plainly instead of answering "something went wrong".
        logger.error("login check failed: database error type=%s", type(exc).__name__)
        raise DatabaseUnavailable from None


StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CurrentUser = Annotated[User, Depends(current_user)]
