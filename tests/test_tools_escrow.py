"""Tests for on-chain escrow MCP tools (mocked HTTP)."""
import pytest
import json
import os
from unittest.mock import AsyncMock, patch, MagicMock

# Shared mocked-HTTP sequence helper (single implementation across test modules).
from tests.test_tools_qa import _mock_http_seq as _mock_http_seq_method


@pytest.fixture(autouse=True)
def setup_api_key():
    """Set up API key/URL in environment for all tests (and keep escrow env vars from leaking)."""
    os.environ["GT_API_KEY"] = "gt_sk_test_123456789"
    os.environ["GT_API_URL"] = "http://localhost:8000/api/v1"
    os.environ.pop("GT_SOLANA_PAYER_SK", None)
    os.environ.pop("GT_ESCROW_ENABLED", None)
    yield
    for var in ("GT_API_KEY", "GT_API_URL", "GT_SOLANA_PAYER_SK", "GT_ESCROW_ENABLED"):
        os.environ.pop(var, None)


@pytest.fixture
def task_id():
    return "550e8400-e29b-41d4-a716-446655440000"


def _mock_http_seq(responses):
    """Patch httpx.AsyncClient serving a sequence of POST responses."""
    return _mock_http_seq_method("post", responses)


def _create_response(task_id):
    return {
        "mission": {"task_id": task_id, "onchain_status": "PENDING_FUND",
                    "mission_pda": "8zHy5bSKuxqFUr8AgzL7LG8XddRtDrsbPpyuftRGaXCP"},
        "quote": {"amount_base": 5_000_000},
        "fund_transaction": {"tx_base64": "dW5zaWduZWQtdHg="},
    }


class TestPostMissionOnchain:
    """post_mission_onchain via the shared create_and_fund_escrow_mission helper."""

    _ARGS = dict(
        title="QA web test", description="Scripted QA run.", deadline="2026-09-02T22:00:00Z",
        budget_amount=5.0, category="DIGITAL_REMOTE",
        acceptance_contract='{"notes": "n", "required_urls": [{"key": "screen_recording", "required": true}]}',
    )

    @pytest.mark.asyncio
    async def test_mode_b_returns_unsigned_fund_transaction(self, task_id):
        """Without a payer key, the unsigned fund tx comes back for an external wallet."""
        from groundtruther_mcp.tools_escrow import post_mission_onchain

        patcher, mock_client = _mock_http_seq([(201, _create_response(task_id))])
        try:
            result = await post_mission_onchain(**self._ARGS)

            mock_client.post.assert_called_once()
            assert "/escrow/missions/" in mock_client.post.call_args[0][0]
            parsed = json.loads(result)
            assert parsed["mode"] == "unsigned"
            assert parsed["mission"]["task_id"] == task_id
            assert parsed["fund_transaction"] == {"tx_base64": "dW5zaWduZWQtdHg="}
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_mode_a_signs_and_submits_fund(self, task_id):
        """With a payer key, the fund tx is signed locally and submitted in the same call."""
        from groundtruther_mcp.tools_escrow import post_mission_onchain

        signer = MagicMock()
        signer.configured = True
        signer.payer_pubkey = "G9vPMFWDf12wBD2ShmD5V28sY2N2JRKYLxRYGz2RdS9b"
        signer.sign_and_serialize.return_value = "c2lnbmVkLXR4"

        patcher, mock_client = _mock_http_seq([
            (201, _create_response(task_id)),
            (200, {"onchain_status": "FUNDED", "fund_sig": "sig123"}),
        ])
        try:
            with patch("groundtruther_mcp.tools_escrow.SolanaSigner", return_value=signer):
                result = await post_mission_onchain(**self._ARGS)

            signer.sign_and_serialize.assert_called_once_with("dW5zaWduZWQtdHg=")
            fund_call = mock_client.post.call_args_list[1]
            assert f"/escrow/missions/{task_id}/submit-fund/" in fund_call[0][0]
            assert fund_call[1]["json"] == {"signed_tx_base64": "c2lnbmVkLXR4"}

            parsed = json.loads(result)
            assert parsed["mode"] == "funded"
            assert parsed["onchain_status"] == "FUNDED"
            assert parsed["fund_sig"] == "sig123"
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_create_failure_keeps_stage_prefixed_error(self, task_id):
        """A failed create surfaces the original 'create failed (HTTP …)' error shape."""
        from groundtruther_mcp.tools_escrow import post_mission_onchain

        patcher, _ = _mock_http_seq([
            (403, {"detail": "on-chain escrow is not enabled for this agent."}),
        ])
        try:
            result = await post_mission_onchain(**self._ARGS)
            error = json.loads(result)["error"]
            assert error.startswith("create failed (HTTP 403)")
            assert "not enabled" in error
        finally:
            patcher.stop()


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
