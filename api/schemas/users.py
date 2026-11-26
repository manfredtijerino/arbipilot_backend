"""Request and response shapes for `/users`."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    """The owner's profile. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    created_at: datetime
    last_login_at: datetime | None


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required: send null or "" to clear the name.
    display_name: Annotated[str | None, Field(max_length=100)]
