"""
Configuration management for BlackBar
Validates required environment variables and provides secure defaults
"""

import os
import secrets
import warnings


class Config:
    """Application configuration with validation"""

    def __init__(self):

        # MongoDB
        self.MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://mongodb:27017/blackbar")

        # JWT Secret
        self.JWT_SECRET = os.getenv("JWT_SECRET")
        self.ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

        if not self.JWT_SECRET:
            if self.ENVIRONMENT == "production":
                raise ValueError("JWT_SECRET environment variable must be set in production!")
            # Generate temporary secret for development only
            self.JWT_SECRET = secrets.token_urlsafe(32)
            warnings.warn(
                "⚠️  WARNING: Using auto-generated JWT secret. "
                "Set JWT_SECRET environment variable for production.",
                RuntimeWarning,
            )

        # Validate JWT secret strength
        if len(self.JWT_SECRET) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")

        # Optional OpenAI key — primary configuration is in the admin LLM settings
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

        # CORS - Allow localhost for development
        origins_env = os.getenv("ALLOWED_ORIGINS", "")
        if origins_env:
            self.ALLOWED_ORIGINS = origins_env.split(",")
        else:
            # Default to localhost for development
            self.ALLOWED_ORIGINS = ["http://localhost:3000", "http://localhost:8000"]

        # Algorithm
        self.ALGORITHM = "HS256"

        # Access-token lifetime. Reads JWT_EXPIRATION env var (integer
        # minutes) if set; falls back to 60 minutes otherwise. The
        # `.env.example` previously documented a `24h` duration string
        # which was silently ignored — Phase 4 Batch 4.4 (audit B5)
        # standardises on integer minutes and actually reads the var.
        jwt_exp_raw = os.getenv("JWT_EXPIRATION")
        if jwt_exp_raw:
            try:
                self.ACCESS_TOKEN_EXPIRE_MINUTES = int(jwt_exp_raw)
            except ValueError:
                warnings.warn(
                    f"JWT_EXPIRATION={jwt_exp_raw!r} is not an integer "
                    f"(minutes); falling back to 60.",
                    RuntimeWarning,
                )
                self.ACCESS_TOKEN_EXPIRE_MINUTES = 60
        else:
            self.ACCESS_TOKEN_EXPIRE_MINUTES = 60


# Create singleton instance
config = Config()

# Export commonly used values
JWT_SECRET = config.JWT_SECRET
ALGORITHM = config.ALGORITHM
MONGODB_URI = config.MONGODB_URI
OPENAI_API_KEY = config.OPENAI_API_KEY
ALLOWED_ORIGINS = config.ALLOWED_ORIGINS
ACCESS_TOKEN_EXPIRE_MINUTES = config.ACCESS_TOKEN_EXPIRE_MINUTES
