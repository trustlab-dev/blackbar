"""Team models for case management"""

from datetime import datetime

from pydantic import BaseModel, Field


class TeamBase(BaseModel):
    """Base team model"""

    name: str
    description: str | None = None
    manager_id: str | None = None


class TeamCreate(TeamBase):
    """Create a new team"""

    member_ids: list[str] = Field(default_factory=list)
    auto_assign: bool = False
    round_robin: bool = True


class TeamUpdate(BaseModel):
    """Update team fields"""

    name: str | None = None
    description: str | None = None
    manager_id: str | None = None
    member_ids: list[str] | None = None
    auto_assign: bool | None = None
    round_robin: bool | None = None


class TeamDB(TeamBase):
    """Complete team document in database"""

    id: str
    member_ids: list[str] = Field(default_factory=list)

    # Assignment settings
    auto_assign: bool = False
    round_robin: bool = True
    last_assigned_index: int = 0  # For round-robin assignment

    # Stats
    active_cases: int = 0

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str
