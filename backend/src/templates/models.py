from datetime import datetime

from pydantic import BaseModel


class TemplateCreate(BaseModel):
    """Create a new template"""

    name: str
    description: str | None = None
    content: str
    category: str | None = "general"  # general, response_letter, status_update, etc.
    is_active: bool = True


class TemplateUpdate(BaseModel):
    """Update template fields"""

    name: str | None = None
    description: str | None = None
    content: str | None = None
    category: str | None = None
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    """Template response model"""

    id: str
    name: str
    description: str | None
    content: str
    category: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: str

    class Config:
        from_attributes = True
