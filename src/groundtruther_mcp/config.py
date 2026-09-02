"""Configuration for GroundTruther MCP Server."""
import os
from typing import Optional


class Config:
    """MCP Server configuration."""

    # API Key from environment variable
    API_KEY: Optional[str] = os.getenv("GT_API_KEY")

    # API base URL from environment variable. The default matches the local
    # docker-compose stack, which publishes the API on host port 8001.
    API_BASE_URL: str = os.getenv("GT_API_URL", "http://localhost:8001/api/v1")

    # On-chain escrow (optional). When enabled and a payer key is configured, escrow tools sign
    # client-side (Mode A). The payer secret key NEVER leaves this process.
    GT_ESCROW_ENABLED: bool = os.getenv("GT_ESCROW_ENABLED", "false").lower() in ("1", "true", "yes")
    GT_SOLANA_PAYER_SK: Optional[str] = os.getenv("GT_SOLANA_PAYER_SK")

    # Server configuration
    SERVER_NAME: str = "groundtruther"
    SERVER_DESCRIPTION: str = "MCP server for GroundTruther marketplace"

    @classmethod
    def validate(cls) -> None:
        """Validate configuration.

        Called AFTER the wallet-auth bootstrap: in wallet-native mode (GT_API_KEY
        unset, GT_SOLANA_PAYER_SK set) the bootstrap has already minted/loaded an
        API key into cls.API_KEY, so reaching here without one means neither
        credential path is configured.
        """
        if not cls.API_KEY:
            raise ValueError(
                "No credentials configured. Set GT_API_KEY (gt_sk_...) or, for "
                "wallet-native auto-auth, GT_SOLANA_PAYER_SK (your Solana payer "
                "secret key — an agent and API key are provisioned automatically "
                "from a wallet signature)."
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
