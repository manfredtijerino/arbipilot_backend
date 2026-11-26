"""The owner's profile."""

from database.models import User
from database.repositories.store import Store
from services.errors import NotAuthenticated


async def update_profile(store: Store, user: User, display_name: str | None) -> User:
    """Change the display name. An empty name clears it."""
    cleaned = (display_name or "").strip() or None
    updated = await store.users.set_display_name(user.id, cleaned)
    if updated is None:
        raise NotAuthenticated
    await store.commit()
    return updated
