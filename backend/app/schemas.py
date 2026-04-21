from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EventCreate(BaseModel):
    source: str = "manual"
    event_type: str
    path: str
    fingerprint: str | None = None
    observed_at: float


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    event_type: str
    path: str
    fingerprint: str | None
    observed_at: float
    created_at: datetime
