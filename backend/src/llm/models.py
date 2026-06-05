"""
LLM Configuration Models
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RequestFormat(str, Enum):
    """Supported LLM request formats"""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    COHERE = "cohere"
    CUSTOM = "custom"


class LLMSettings(BaseModel):
    """Default settings for LLM requests"""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, gt=0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)


class LLMConfigBase(BaseModel):
    """Base LLM configuration model"""

    name: str = Field(..., description="Display name for this LLM configuration")
    enabled: bool = Field(default=True, description="Whether this LLM is available for use")
    api_endpoint: str = Field(..., description="Full API endpoint URL")
    model_name: str = Field(..., description="Model identifier for API calls")
    request_format: RequestFormat = Field(..., description="API request format type")
    default_settings: LLMSettings = Field(default_factory=LLMSettings)
    headers: dict[str, str] | None = Field(default=None, description="Optional custom headers")
    notes: str | None = Field(default=None, description="Admin notes about this configuration")


class LLMConfigCreate(LLMConfigBase):
    """Model for creating a new LLM configuration"""

    api_key: str = Field(..., description="API key (will be encrypted on storage)")


class LLMConfigUpdate(BaseModel):
    """Model for updating an LLM configuration"""

    name: str | None = None
    enabled: bool | None = None
    api_endpoint: str | None = None
    model_name: str | None = None
    request_format: RequestFormat | None = None
    default_settings: LLMSettings | None = None
    headers: dict[str, str] | None = None
    notes: str | None = None
    api_key: str | None = None  # If provided, will be re-encrypted


class LLMConfig(LLMConfigBase):
    """Full LLM configuration model (from database)"""

    id: str
    api_key_encrypted: str = Field(..., description="Encrypted API key")
    created_at: datetime
    updated_at: datetime
    created_by: str

    class Config:
        from_attributes = True


class LLMConfigResponse(LLMConfigBase):
    """LLM configuration for API responses (no encrypted key)"""

    id: str
    created_at: datetime
    updated_at: datetime
    created_by: str

    class Config:
        from_attributes = True
