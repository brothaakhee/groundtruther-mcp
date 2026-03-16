"""Configuration for GroundTruther MCP Server."""
import os
from typing import Optional


class Config:
    """MCP Server configuration."""

    # API Key from environment variable
    API_KEY: Optional[str] = os.getenv("GT_API_KEY")

    # API base URL from environment variable, default to localhost
    API_BASE_URL: str = os.getenv("GT_API_URL", "http://localhost:8000/api/v1")

    # Server configuration
    SERVER_NAME: str = "groundtruther"
    SERVER_DESCRIPTION: str = "MCP server for GroundTruther marketplace"

    @classmethod
    def validate(cls) -> None:
        """Validate configuration."""
        if not cls.API_KEY:
            raise ValueError(
                "GT_API_KEY environment variable is required. "
                "Format: gt_sk_..."
            )
        if not cls.API_KEY.startswith("gt_sk_"):
            raise ValueError(
                "API key must start with 'gt_sk_'. "
                f"Got: {cls.API_KEY[:10]}..."
            )

    @classmethod
    def get_auth_header(cls) -> dict:
        """Get authorization header for API requests."""
        if not cls.API_KEY:
            raise ValueError("API_KEY not set")
        return {"Authorization": f"Bearer {cls.API_KEY}"}
