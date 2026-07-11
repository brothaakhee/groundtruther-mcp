"""Tests for on-chain escrow MCP tools (mocked HTTP)."""
import pytest
import json
import os
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture(autouse=True)
def setup_api_key():
    """Set up API key/URL in environment for all tests."""
    os.environ["GT_API_KEY"] = "gt_sk_test_123456789"
    os.environ["GT_API_URL"] = "http://localhost:8000/api/v1"
    yield
    if "GT_API_KEY" in os.environ:
        del os.environ["GT_API_KEY"]
    if "GT_API_URL" in os.environ:
        del os.environ["GT_API_URL"]


@pytest.fixture
def task_id():
    return "550e8400-e29b-41d4-a716-446655440000"


class TestEscalateMission:
    """Tests for the off-chain escalate_mission escrow tool (rung 3 arbitration request)."""

    @pytest.mark.asyncio
    async def test_escalate_posts_empty_body_to_escalate_path(self, task_id):
        """POSTs an empty body to the escalate endpoint and returns the mission JSON."""
        from groundtruther_mcp.tools_escrow import escalate_mission

        response_data = {
            "task_id": task_id,
            "onchain_status": "DISPUTED",
            "escalated": True,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await escalate_mission(task_id)

            # Verify the POST hit the right path with an empty body.
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert f"/escrow/missions/{task_id}/escalate/" in call_args[0][0]
            assert call_args[1]["json"] == {}
            assert "Bearer gt_sk_" in call_args[1]["headers"]["Authorization"]

            # Verify the returned string is the backend mission payload.
            parsed = json.loads(result)
            assert parsed["task_id"] == task_id
            assert parsed["escalated"] is True

    @pytest.mark.asyncio
    async def test_escalate_409_surfaces_detail(self, task_id):
        """A 409 (already escalated / not disputed) surfaces the backend detail."""
        from groundtruther_mcp.tools_escrow import escalate_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 409
            mock_response.json.return_value = {
                "detail": "This mission has already been escalated to GroundTruther."
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await escalate_mission(task_id)

            parsed = json.loads(result)
            assert "error" in parsed
            assert "409" in parsed["error"]
            assert "already been escalated" in parsed["error"]
