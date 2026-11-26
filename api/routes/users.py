"""`/users`: the owner's profile. Login needed."""

from fastapi import APIRouter

from api.dependencies import CurrentUser, StoreDep
from api.schemas.users import UpdateUserRequest, UserResponse
from services import user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserResponse)
async def read_me(user: CurrentUser) -> UserResponse:
    """The logged-in user's profile."""
    return UserResponse.model_validate(user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: UpdateUserRequest, user: CurrentUser, store: StoreDep
) -> UserResponse:
    """Change the display name."""
    updated = await user_service.update_profile(store, user, body.display_name)
    return UserResponse.model_validate(updated)
