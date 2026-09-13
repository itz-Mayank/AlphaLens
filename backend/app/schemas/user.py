import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    is_email_verified: bool
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
