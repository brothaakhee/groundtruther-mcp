"""HTTP client wrapper for GroundTruther Django API."""
import httpx
import json
from typing import Dict, Any, Optional
from .config import Config


class APIClient:
    """HTTP client for communicating with Django REST API."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize API client.

        Args:
            base_url: Base URL for API calls (defaults to config)
            api_key: API key for authentication (defaults to config)
        """
        self.base_url = base_url or Config.API_BASE_URL
        self.api_key = api_key or Config.API_KEY
        self.timeout = 30

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        use_auth: bool = True,
    ) -> httpx.Response:
        """
        Make a GET request to the API.

        Args:
            endpoint: API endpoint (e.g., '/tasks/')
            params: Query parameters
            use_auth: Whether to include authorization header

        Returns:
            HTTP response
        """
        url = self._build_url(endpoint)
        headers = self._get_headers(use_auth)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.get(url, params=params, headers=headers)

    async def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        use_auth: bool = True,
    ) -> httpx.Response:
        """
        Make a POST request to the API.

        Args:
            endpoint: API endpoint (e.g., '/tasks/')
            data: Request body as dictionary
            params: Query parameters
            use_auth: Whether to include authorization header

        Returns:
            HTTP response
        """
        url = self._build_url(endpoint)
        headers = self._get_headers(use_auth)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.post(
                url, json=data, params=params, headers=headers
            )

    def _build_url(self, endpoint: str) -> str:
        """
        Build full URL from endpoint.

        Args:
            endpoint: API endpoint

        Returns:
            Full URL
        """
        if endpoint.startswith("/"):
            endpoint = endpoint[1:]
        return f"{self.base_url}/{endpoint}"

    def _get_headers(self, use_auth: bool = True) -> Dict[str, str]:
        """
        Get request headers.

        Args:
            use_auth: Whether to include authorization header

        Returns:
            Headers dictionary
        """
        headers = {
            "Content-Type": "application/json",
        }

        if use_auth and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    @staticmethod
    def handle_response(response: httpx.Response) -> Dict[str, Any]:
        """
        Handle API response and return parsed JSON or error.

        Args:
            response: HTTP response

        Returns:
            Parsed JSON response or error dictionary
        """
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            data = {"detail": response.text or "Unknown error"}

        # Return both status code and data for caller to handle
        return {
            "status_code": response.status_code,
            "data": data,
        }
