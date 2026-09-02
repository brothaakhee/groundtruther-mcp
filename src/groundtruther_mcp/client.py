"""HTTP client wrapper for GroundTruther Django API."""
import httpx
import json
import os
import sys
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
        # Config.API_KEY is set by the wallet-auth bootstrap in wallet-native mode;
        # the env fallback keeps a late-set GT_API_KEY working regardless of when
        # the Config class was first imported.
        self.base_url = base_url or os.getenv("GT_API_URL") or Config.API_BASE_URL
        self.api_key = api_key or Config.API_KEY or os.getenv("GT_API_KEY")
        # Escrow calls block on devnet/mainnet RPC confirmation server-side and can
        # exceed 30s; GT_HTTP_TIMEOUT raises the ceiling without a code change.
        try:
            self.timeout = float(os.getenv("GT_HTTP_TIMEOUT", "30"))
        except ValueError:
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
        return await self._request_with_reauth(
            "get", self._build_url(endpoint), self._get_headers(use_auth),
            use_auth=use_auth, params=params)

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
        return await self._request_with_reauth(
            "post", self._build_url(endpoint), self._get_headers(use_auth),
            use_auth=use_auth, params=params, json_data=data)

    async def _send(self, method: str, url: str, headers, params=None, json_data=None):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if method == "get":
                return await client.get(url, params=params, headers=headers)
            return await client.post(url, json=json_data, params=params, headers=headers)

    async def _request_with_reauth(self, method: str, url: str, headers, *,
                                   use_auth: bool, params=None, json_data=None):
        """One request, plus at most ONE retry after a wallet re-auth.

        The retry triggers on a 401 (key rotated/revoked elsewhere) OR on a
        request TIMEOUT of an auth-carrying call: a stale key can stall
        server-side past our timeout, so the promised 401 never reaches us —
        treat the timeout as a potential stale-key symptom (wallet mode only).
        Timeouts that survive the retry are re-raised with a real message
        (str(httpx.ReadTimeout()) is empty, which used to surface as the
        useless "Network error: ").
        """
        try:
            response = await self._send(method, url, headers, params, json_data)
        except httpx.TimeoutException as exc:
            fresh = await self._reauth_once() if use_auth else None
            if not fresh:
                raise self._descriptive_timeout(exc, url) from exc
            headers["Authorization"] = f"Bearer {fresh}"
            try:
                response = await self._send(method, url, headers, params, json_data)
            except httpx.TimeoutException as exc2:
                raise self._descriptive_timeout(exc2, url) from exc2
            self._warn_if_still_unauthorized(response)
            return response
        if use_auth and response.status_code == 401:
            fresh = await self._reauth_once()
            if fresh:
                headers["Authorization"] = f"Bearer {fresh}"
                response = await self._send(method, url, headers, params, json_data)
                self._warn_if_still_unauthorized(response)
        return response

    def _descriptive_timeout(self, exc: "httpx.TimeoutException", url: str):
        """A same-typed timeout whose str() actually says what happened."""
        detail = str(exc).strip()
        msg = (f"request to {url} timed out after {self.timeout}s"
               + (f" ({detail})" if detail else "")
               + " — the server may be slow (escrow calls block on RPC confirmation);"
                 " raise GT_HTTP_TIMEOUT (default 30) if this recurs")
        try:
            return type(exc)(msg)
        except Exception:  # noqa: BLE001 — exotic exception signature: keep the original
            return exc

    async def _reauth_once(self):
        """One-shot wallet re-auth after a 401 (key rotated/revoked elsewhere).

        Only applies in wallet-native mode: an explicitly pinned GT_API_KEY is
        respected (its 401 surfaces to the caller). Returns the fresh key or None.
        """
        from . import wallet_auth

        if not wallet_auth.wallet_auth_available():
            return None
        try:
            fresh = await wallet_auth.mint_fresh_credentials()
        except wallet_auth.WalletAuthError as exc:
            print(f"groundtruther-mcp: API key was rejected (401) and wallet re-auth "
                  f"FAILED: {exc}", file=sys.stderr)
            return None
        if fresh:
            self.api_key = fresh
        return fresh

    @staticmethod
    def _warn_if_still_unauthorized(response) -> None:
        if response.status_code == 401:
            print("groundtruther-mcp: still unauthorized AFTER a successful wallet "
                  "re-auth — the server is rejecting freshly minted keys; giving up "
                  "(no retry loop). Check the deployment.", file=sys.stderr)

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
