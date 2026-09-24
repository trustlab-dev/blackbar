"""
LLM Configuration Models
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Value returned in place of every custom header value (LLM-05). Sending it
# back unchanged on update keeps the stored value for that header.
MASKED_HEADER_VALUE = "********"


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
    max_tokens: int = Field(default=4000, gt=0, le=32000)
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

    model_config = ConfigDict(from_attributes=True)

    id: str
    # Empty when the key was cleared because the endpoint or provider
    # changed without a new key being supplied (LLM-05).
    api_key_encrypted: str = Field(..., description="Encrypted API key")
    created_at: datetime
    updated_at: datetime
    created_by: str


class LLMConfigResponse(LLMConfigBase):
    """LLM configuration for API responses: no key, header values masked."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
    created_by: str
    api_key_set: bool = Field(
        default=True,
        description="False when the API key must be re-entered (endpoint or provider changed)",
    )

    @field_validator("headers")
    @classmethod
    def _mask_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if not value:
            return value
        return dict.fromkeys(value, MASKED_HEADER_VALUE)

    @classmethod
    def from_config(cls, config: "LLMConfig") -> "LLMConfigResponse":
        data = config.model_dump(exclude={"api_key_encrypted"})
        data["api_key_set"] = bool(config.api_key_encrypted)
        return cls(**data)
