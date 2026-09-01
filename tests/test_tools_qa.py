"""Tests for QA vertical MCP tools (request_qa_test / get_qa_result) using mocked HTTP calls."""
import pytest
import json
import os
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone


@pytest.fixture(autouse=True)
def setup_api_key():
    """Set up API key in environment for all tests."""
    os.environ["GT_API_KEY"] = "gt_sk_test_123456789"
    os.environ["GT_API_URL"] = "http://localhost:8000/api/v1"
    yield
    # Cleanup after test
    if "GT_API_KEY" in os.environ:
        del os.environ["GT_API_KEY"]
    if "GT_API_URL" in os.environ:
        del os.environ["GT_API_URL"]


@pytest.fixture
def mission_uuid():
    """Sample task UUID."""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def staging_url():
    """Sample staging URL."""
    return "https://staging.example.com"


@pytest.fixture
def steps_json():
    """Sample steps JSON with explicit ids."""
    return json.dumps([
        {"id": "login", "instruction": "Log in with the test account", "expected": "Dashboard loads"},
        {"id": "checkout", "instruction": "Add an item to cart and check out", "expected": "Order confirmation page shown"},
    ])


@pytest.fixture
def qa_contract(staging_url):
    """Acceptance contract of a QA mission, as the API returns it."""
    return {
        "notes": "QA test run instructions for the tester.",
        "qa_script": {
            "staging_url": staging_url,
            "environment": "Chrome desktop",
            "steps": [
                {"id": "s1", "instruction": "Log in with the test account", "expected": "Dashboard loads"},
                {"id": "s2", "instruction": "Add an item to cart and check out", "expected": "Order confirmation page shown"},
            ],
        },
        "required_urls": [
            {"key": "screen_recording", "label": "Screen recording of the full test run", "required": True},
        ],
    }


def _make_task_response(mission_uuid, qa_contract, status="OPEN", proofs=None):
    """Build a task detail payload as GET /tasks/{id}/ returns it."""
    return {
        "id": mission_uuid,
        "title": "QA web test — staging.example.com (2 steps)",
        "status": status,
        "category": "DIGITAL_REMOTE",
        "acceptance_contract": qa_contract,
        "proofs": proofs or [],
    }


def _make_qa_proof(step_verdicts, overall_verdict, submitted_at="2026-08-30T12:00:00Z",
                   recording_url="https://loom.com/share/abc123", tester_notes=None):
    """Build a structured_data QA proof as nested in the task detail response.

    step_verdicts: list of (id, verdict, observed-or-None)
    """
    qa_result = {
        "overall_verdict": overall_verdict,
        "steps": [
            {"id": sid, "verdict": verdict, **({"observed": observed} if observed is not None else {})}
            for sid, verdict, observed in step_verdicts
        ],
        "tester_environment": "Chrome 129 / macOS 15",
    }
    if tester_notes is not None:
        qa_result["notes"] = tester_notes
    return {
        "id": "proof-1",
        "proof_type": "structured_data",
        "file_urls": [],
        "gps_lat": None,
        "gps_lng": None,
        "structured_data": {"qa_result": qa_result},
        "proof_urls": [{"key": "screen_recording", "url": recording_url}],
        "submitted_at": submitted_at,
    }


def _mock_http(method, status_code, response_data):
    """Return (patch context manager, mock client) with one mocked response."""
    patcher = patch("httpx.AsyncClient")
    mock_client_class = patcher.start()
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_data
    getattr(mock_client, method).return_value = mock_response
    mock_client_class.return_value.__aenter__.return_value = mock_client
    return patcher, mock_client


def _mock_http_seq(method, responses):
    """Like _mock_http but serves a sequence of responses (or raises exceptions).

    responses: list of (status_code, data) tuples or Exception instances.
    """
    patcher = patch("httpx.AsyncClient")
    mock_client_class = patcher.start()
    mock_client = AsyncMock()
    side_effects = []
    for item in responses:
        if isinstance(item, Exception):
            side_effects.append(item)
            continue
        status_code, data = item
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = data
        side_effects.append(mock_response)
    getattr(mock_client, method).side_effect = side_effects
    mock_client_class.return_value.__aenter__.return_value = mock_client
    return patcher, mock_client


class TestRequestQaTest:
    """Tests for request_qa_test tool."""

    @pytest.mark.asyncio
    async def test_request_qa_test_success(self, mission_uuid, staging_url, steps_json):
        """Happy path: creates a DIGITAL_REMOTE task with a full QA contract."""
        from groundtruther_mcp.tools_qa import request_qa_test

        response_data = {"id": mission_uuid, "status": "OPEN", "title": "QA web test"}
        patcher, mock_client = _mock_http("post", 201, response_data)
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps_json)

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "/tasks/" in call_args[0][0]
            assert "Bearer gt_sk_" in call_args[1]["headers"]["Authorization"]

            payload = call_args[1]["json"]
            assert payload["category"] == "DIGITAL_REMOTE"
            assert payload["budget_amount"] == 15.0
            assert "latitude" not in payload and "longitude" not in payload

            contract = payload["acceptance_contract"]
            assert contract["notes"]  # auto-composed tester brief
            assert "screen recording" in contract["notes"].lower()
            assert "observed" in contract["notes"]

            script = contract["qa_script"]
            assert script["staging_url"] == staging_url
            assert [s["id"] for s in script["steps"]] == ["login", "checkout"]
            assert script["steps"][0]["instruction"] == "Log in with the test account"
            assert script["steps"][0]["expected"] == "Dashboard loads"

            recording = [u for u in contract["required_urls"] if u["key"] == "screen_recording"]
            assert len(recording) == 1
            assert recording[0]["required"] is True
            assert recording[0]["label"]

            response = json.loads(result)
            assert response["task_id"] == mission_uuid
            # Raw OPEN maps through the same lowercase vocabulary as get_qa_result.
            assert response["status"] == "pending"
            assert "next" in response
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_public_url_has_no_warning(self, mission_uuid, staging_url, steps_json):
        """A publicly reachable staging URL produces no reachability warning."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, _ = _mock_http("post", 201, {"id": mission_uuid, "status": "OPEN"})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps_json)
            assert "warning" not in json.loads(result)
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_private_url_warns_but_does_not_block(self, mission_uuid, steps_json):
        """Loopback/private/internal staging URLs still post, but carry a tunnel-teaching warning."""
        from groundtruther_mcp.tools_qa import request_qa_test

        for url, host in [
            ("http://localhost:5173", "localhost"),
            ("http://127.0.0.1:8000", "127.0.0.1"),
            ("http://[::1]:5173", "::1"),
            ("http://192.168.1.10:3000", "192.168.1.10"),
            ("http://10.0.0.5", "10.0.0.5"),
            ("http://169.254.10.10", "169.254.10.10"),
            ("https://myapp.local", "myapp.local"),
            ("https://staging.internal", "staging.internal"),
        ]:
            patcher, mock_client = _mock_http("post", 201, {"id": mission_uuid, "status": "OPEN"})
            try:
                result = await request_qa_test(staging_url=url, steps=steps_json)

                # Not blocked: the mission was still posted.
                mock_client.post.assert_called_once()
                response = json.loads(result)
                assert response["task_id"] == mission_uuid

                warning = response.get("warning")
                assert warning, f"expected a reachability warning for {url}"
                assert f"Testers can't reach {host}" in warning
                assert "cloudflared tunnel --url http://localhost:PORT" in warning
                assert "ngrok" in warning
                assert "server may reject" in warning
            finally:
                patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_auto_assigns_step_ids(self, mission_uuid, staging_url):
        """Steps without ids get s1..sN assigned in order."""
        from groundtruther_mcp.tools_qa import request_qa_test

        steps = json.dumps([
            {"instruction": "Open the home page", "expected": "Hero section visible"},
            {"instruction": "Search for 'shoes'", "expected": "Results list shows items"},
            {"instruction": "Open the first result", "expected": "Product page loads"},
        ])
        patcher, mock_client = _mock_http("post", 201, {"id": mission_uuid, "status": "OPEN"})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps)

            payload = mock_client.post.call_args[1]["json"]
            step_ids = [s["id"] for s in payload["acceptance_contract"]["qa_script"]["steps"]]
            assert step_ids == ["s1", "s2", "s3"]
            assert "error" not in json.loads(result)
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_mixed_ids(self, mission_uuid, staging_url):
        """Explicit ids are preserved; missing ones get positional ids."""
        from groundtruther_mcp.tools_qa import request_qa_test

        steps = json.dumps([
            {"id": "login", "instruction": "Log in", "expected": "Dashboard loads"},
            {"instruction": "Log out", "expected": "Login page shown"},
        ])
        patcher, mock_client = _mock_http("post", 201, {"id": mission_uuid, "status": "OPEN"})
        try:
            await request_qa_test(staging_url=staging_url, steps=steps)

            payload = mock_client.post.call_args[1]["json"]
            step_ids = [s["id"] for s in payload["acceptance_contract"]["qa_script"]["steps"]]
            assert step_ids == ["login", "s2"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_environment_and_credentials(self, mission_uuid, staging_url, steps_json):
        """environment / credentials_note land in qa_script."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, mock_client = _mock_http("post", 201, {"id": mission_uuid, "status": "OPEN"})
        try:
            await request_qa_test(
                staging_url=staging_url,
                steps=steps_json,
                environment="Firefox on Windows",
                credentials_note="Use test@example.com / hunter2",
            )

            script = mock_client.post.call_args[1]["json"]["acceptance_contract"]["qa_script"]
            assert script["environment"] == "Firefox on Windows"
            assert script["credentials_note"] == "Use test@example.com / hunter2"
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_omits_optional_script_keys(self, mission_uuid, staging_url, steps_json):
        """environment / credentials_note are omitted from qa_script when not given."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, mock_client = _mock_http("post", 201, {"id": mission_uuid, "status": "OPEN"})
        try:
            await request_qa_test(staging_url=staging_url, steps=steps_json)

            script = mock_client.post.call_args[1]["json"]["acceptance_contract"]["qa_script"]
            assert "environment" not in script
            assert "credentials_note" not in script
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_custom_title_budget_deadline(self, mission_uuid, staging_url, steps_json):
        """title/budget/deadline_hours flow into the task payload."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, mock_client = _mock_http("post", 201, {"id": mission_uuid, "status": "OPEN"})
        try:
            before = datetime.now(timezone.utc)
            await request_qa_test(
                staging_url=staging_url,
                steps=steps_json,
                budget=25.0,
                deadline_hours=48,
                title="QA: checkout regression",
            )
            after = datetime.now(timezone.utc)

            payload = mock_client.post.call_args[1]["json"]
            assert payload["title"] == "QA: checkout regression"
            assert payload["budget_amount"] == 25.0

            deadline = datetime.fromisoformat(payload["deadline"].replace("Z", "+00:00"))
            assert before + timedelta(hours=47, minutes=59) <= deadline <= after + timedelta(hours=48, minutes=1)
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_invalid_url(self, steps_json):
        """A non-http(s) staging_url is rejected before any API call."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, mock_client = _mock_http("post", 201, {})
        try:
            result = await request_qa_test(staging_url="not-a-url", steps=steps_json)

            mock_client.post.assert_not_called()
            response = json.loads(result)
            assert "staging_url" in response["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_steps_not_json(self, staging_url):
        """Malformed steps JSON is rejected before any API call."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, mock_client = _mock_http("post", 201, {})
        try:
            result = await request_qa_test(staging_url=staging_url, steps="not json at all")

            mock_client.post.assert_not_called()
            response = json.loads(result)
            assert "steps" in response["error"]
            assert "JSON" in response["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_empty_steps(self, staging_url):
        """An empty steps list is rejected before any API call."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, mock_client = _mock_http("post", 201, {})
        try:
            result = await request_qa_test(staging_url=staging_url, steps="[]")

            mock_client.post.assert_not_called()
            assert "steps" in json.loads(result)["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_too_many_steps(self, staging_url):
        """More than 30 steps is rejected before any API call."""
        from groundtruther_mcp.tools_qa import request_qa_test

        steps = json.dumps([
            {"instruction": f"Step {i}", "expected": f"Result {i}"} for i in range(31)
        ])
        patcher, mock_client = _mock_http("post", 201, {})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps)

            mock_client.post.assert_not_called()
            assert "30" in json.loads(result)["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_duplicate_ids(self, staging_url):
        """Duplicate step ids are rejected before any API call."""
        from groundtruther_mcp.tools_qa import request_qa_test

        steps = json.dumps([
            {"id": "login", "instruction": "Log in", "expected": "Dashboard"},
            {"id": "login", "instruction": "Log in again", "expected": "Error shown"},
        ])
        patcher, mock_client = _mock_http("post", 201, {})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps)

            mock_client.post.assert_not_called()
            response = json.loads(result)
            assert "login" in response["error"]
            assert "duplicate" in response["error"].lower()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_missing_instruction(self, staging_url):
        """A step missing instruction/expected is rejected with the step index."""
        from groundtruther_mcp.tools_qa import request_qa_test

        steps = json.dumps([
            {"instruction": "Open the app", "expected": "Home page loads"},
            {"expected": "Something happens"},
        ])
        patcher, mock_client = _mock_http("post", 201, {})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps)

            mock_client.post.assert_not_called()
            response = json.loads(result)
            assert "instruction" in response["error"]
            assert "[1]" in response["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_unknown_step_key(self, staging_url):
        """Steps with unknown keys are rejected before any API call."""
        from groundtruther_mcp.tools_qa import request_qa_test

        steps = json.dumps([
            {"instruction": "Open the app", "expected": "Home page loads", "note": "extra"},
        ])
        patcher, mock_client = _mock_http("post", 201, {})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps)

            mock_client.post.assert_not_called()
            assert "note" in json.loads(result)["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_invalid_budget_and_deadline(self, staging_url, steps_json):
        """Non-positive budget or deadline_hours is rejected before any API call."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, mock_client = _mock_http("post", 201, {})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps_json, budget=0)
            assert "budget" in json.loads(result)["error"]

            result = await request_qa_test(staging_url=staging_url, steps=steps_json, deadline_hours=0)
            assert "deadline_hours" in json.loads(result)["error"]

            mock_client.post.assert_not_called()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_insufficient_funds(self, staging_url, steps_json):
        """402 from the API maps to a payment-required error."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, _ = _mock_http("post", 402, {"detail": "Insufficient funds"})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps_json)
            assert json.loads(result)["error"] == "Insufficient funds"
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_bad_request(self, staging_url, steps_json):
        """400 from the API surfaces the validation detail."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, _ = _mock_http("post", 400, {"acceptance_contract": ["invalid"]})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps_json)
            assert "Bad request" in json.loads(result)["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_request_qa_test_unauthorized(self, staging_url, steps_json):
        """401 from the API maps to an auth error."""
        from groundtruther_mcp.tools_qa import request_qa_test

        patcher, _ = _mock_http("post", 401, {"detail": "Invalid API key"})
        try:
            result = await request_qa_test(staging_url=staging_url, steps=steps_json)
            assert "Unauthorized" in json.loads(result)["error"]
        finally:
            patcher.stop()


class TestGetQaResult:
    """Tests for get_qa_result tool."""

    @pytest.mark.asyncio
    async def test_get_qa_result_not_found(self, mission_uuid):
        """404 from the API maps to a not-found error."""
        from groundtruther_mcp.tools_qa import get_qa_result

        patcher, _ = _mock_http("get", 404, {"detail": "Not found."})
        try:
            result = await get_qa_result(mission_uuid)
            assert mission_uuid in json.loads(result)["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_unauthorized(self, mission_uuid):
        """401 from the API maps to an auth error."""
        from groundtruther_mcp.tools_qa import get_qa_result

        patcher, _ = _mock_http("get", 401, {"detail": "Invalid API key"})
        try:
            result = await get_qa_result(mission_uuid)
            assert "Unauthorized" in json.loads(result)["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_non_qa_task(self, mission_uuid):
        """A task without qa_script in its contract is rejected with a clear error."""
        from groundtruther_mcp.tools_qa import get_qa_result

        task = _make_task_response(
            mission_uuid,
            {"notes": "Take a photo", "required_media": [{"type": "photo", "label": "Photo", "required": True}]},
        )
        patcher, _ = _mock_http("get", 200, task)
        try:
            result = await get_qa_result(mission_uuid)
            response = json.loads(result)
            assert "not a QA mission" in response["error"]
            assert "check_mission_status" in response["error"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_pending(self, mission_uuid, qa_contract):
        """OPEN task, no proof: status=pending, empty failed_steps, no verdict."""
        from groundtruther_mcp.tools_qa import get_qa_result

        task = _make_task_response(mission_uuid, qa_contract, status="OPEN")
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "pending"
            assert response["failed_steps"] == []
            assert "overall_verdict" not in response
            assert "recording_url" not in response
            assert response["next_action"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_claimed(self, mission_uuid, qa_contract):
        """CLAIMED task maps to status=claimed."""
        from groundtruther_mcp.tools_qa import get_qa_result

        task = _make_task_response(mission_uuid, qa_contract, status="CLAIMED")
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "claimed"
            assert response["next_action"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_in_progress_no_proof(self, mission_uuid, qa_contract):
        """IN_PROGRESS with no proof maps to status=in_progress."""
        from groundtruther_mcp.tools_qa import get_qa_result

        task = _make_task_response(mission_uuid, qa_contract, status="IN_PROGRESS")
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "in_progress"
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_rejected(self, mission_uuid, qa_contract):
        """IN_PROGRESS with an existing proof means the last submission was rejected."""
        from groundtruther_mcp.tools_qa import get_qa_result

        proof = _make_qa_proof([("s1", "pass", None), ("s2", "fail", "Checkout button did nothing")], "fail")
        task = _make_task_response(mission_uuid, qa_contract, status="IN_PROGRESS", proofs=[proof])
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "rejected"
            # The rejected submission is still surfaced for context
            assert response["overall_verdict"] == "fail"
            assert "resubmit" in response["next_action"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_awaiting_review_pass(self, mission_uuid, qa_contract):
        """PROOF_SUBMITTED with a passing result: awaiting_review + approve guidance."""
        from groundtruther_mcp.tools_qa import get_qa_result

        proof = _make_qa_proof([("s1", "pass", None), ("s2", "pass", None)], "pass",
                               tester_notes="Smooth run, no issues.")
        task = _make_task_response(mission_uuid, qa_contract, status="PROOF_SUBMITTED", proofs=[proof])
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "awaiting_review"
            assert response["overall_verdict"] == "pass"
            assert response["failed_steps"] == []
            assert response["recording_url"] == "https://loom.com/share/abc123"
            assert response["tester_environment"] == "Chrome 129 / macOS 15"
            assert response["notes"] == "Smooth run, no issues."
            assert "approve_mission" in response["next_action"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_fail_joins_failed_steps(self, mission_uuid, qa_contract):
        """failed_steps is pre-joined from qa_script (instruction/expected) + qa_result (observed)."""
        from groundtruther_mcp.tools_qa import get_qa_result

        proof = _make_qa_proof(
            [("s1", "pass", None), ("s2", "fail", "Checkout returned a 500 error")], "fail")
        task = _make_task_response(mission_uuid, qa_contract, status="COMPLETED", proofs=[proof])
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "completed"
            assert response["overall_verdict"] == "fail"

            assert response["failed_steps"] == [{
                "id": "s2",
                "instruction": "Add an item to cart and check out",
                "expected": "Order confirmation page shown",
                "observed": "Checkout returned a 500 error",
            }]

            # Full joined step view is also present
            assert response["steps"][0]["id"] == "s1"
            assert response["steps"][0]["verdict"] == "pass"
            assert response["steps"][0]["instruction"] == "Log in with the test account"
            assert response["steps"][1]["verdict"] == "fail"

            assert "fix the failed steps" in response["next_action"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_completed_pass(self, mission_uuid, qa_contract):
        """COMPLETED passing run: no further action needed."""
        from groundtruther_mcp.tools_qa import get_qa_result

        proof = _make_qa_proof([("s1", "pass", None), ("s2", "pass", None)], "pass")
        task = _make_task_response(mission_uuid, qa_contract, status="COMPLETED", proofs=[proof])
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "completed"
            assert response["overall_verdict"] == "pass"
            assert response["failed_steps"] == []
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_blocked(self, mission_uuid, qa_contract):
        """A blocked run surfaces blocked_steps (pre-joined), not failed_steps."""
        from groundtruther_mcp.tools_qa import get_qa_result

        proof = _make_qa_proof(
            [("s1", "blocked", "Staging site returned 502 — could not start"),
             ("s2", "blocked", "Blocked by step 1")],
            "blocked")
        task = _make_task_response(mission_uuid, qa_contract, status="PROOF_SUBMITTED", proofs=[proof])
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["overall_verdict"] == "blocked"
            assert response["failed_steps"] == []
            # blocked_steps mirrors failed_steps: joined with instruction/expected
            assert response["blocked_steps"] == [
                {
                    "id": "s1",
                    "instruction": "Log in with the test account",
                    "expected": "Dashboard loads",
                    "observed": "Staging site returned 502 — could not start",
                },
                {
                    "id": "s2",
                    "instruction": "Add an item to cart and check out",
                    "expected": "Order confirmation page shown",
                    "observed": "Blocked by step 1",
                },
            ]
            verdicts = [s["verdict"] for s in response["steps"]]
            assert verdicts == ["blocked", "blocked"]
            assert response["steps"][0]["observed"] == "Staging site returned 502 — could not start"
            assert "blocked" in response["next_action"]
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_mixed_fail_and_blocked_steps(self, mission_uuid, qa_contract):
        """fail and blocked steps land in their respective lists (failed_steps stays fail-only)."""
        from groundtruther_mcp.tools_qa import get_qa_result

        proof = _make_qa_proof(
            [("s1", "fail", "Login form 500s"),
             ("s2", "blocked", "Cannot proceed past login")],
            "fail")
        task = _make_task_response(mission_uuid, qa_contract, status="PROOF_SUBMITTED", proofs=[proof])
        patcher, mock_client = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert [s["id"] for s in response["failed_steps"]] == ["s1"]
            assert [s["id"] for s in response["blocked_steps"]] == ["s2"]
            assert response["blocked_steps"][0]["observed"] == "Cannot proceed past login"
            # No claim-request lookup for a submitted mission — single API call.
            mock_client.get.assert_called_once()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_claim_requested(self, mission_uuid, qa_contract):
        """OPEN task with a pending claim request: the approval gate is surfaced."""
        from groundtruther_mcp.tools_qa import get_qa_result

        task = _make_task_response(mission_uuid, qa_contract, status="OPEN")
        claim_requests = {"results": [
            {"id": "cr-pending-1", "status": "pending",
             "created_at": "2026-08-30T12:00:00Z"},
            {"id": "cr-declined-1", "status": "declined",
             "created_at": "2026-08-30T11:00:00Z"},
        ]}
        patcher, mock_client = _mock_http_seq("get", [(200, task), (200, claim_requests)])
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "claim_requested"
            assert response["pending_claim_requests"] == [
                {"request_id": "cr-pending-1", "created_at": "2026-08-30T12:00:00Z"},
            ]
            assert "respond_to_claim_request" in response["next_action"]
            assert "list_pending_claim_requests" in response["next_action"]
            # The claim-request lookup is scoped to this mission.
            cr_call = mock_client.get.call_args_list[1]
            assert "/agent/claim-requests/" in cr_call[0][0]
            assert cr_call[1]["params"]["mission_uuid"] == mission_uuid
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_pending_when_no_claim_requests(self, mission_uuid, qa_contract):
        """OPEN task with an empty claim-request list stays status=pending."""
        from groundtruther_mcp.tools_qa import get_qa_result

        task = _make_task_response(mission_uuid, qa_contract, status="OPEN")
        patcher, mock_client = _mock_http_seq("get", [(200, task), (200, {"results": []})])
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "pending"
            assert "pending_claim_requests" not in response
            assert mock_client.get.call_count == 2
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_claim_request_lookup_failure_is_non_fatal(
            self, mission_uuid, qa_contract):
        """A failing claim-request lookup degrades to the plain status, not an error."""
        import httpx as _httpx
        from groundtruther_mcp.tools_qa import get_qa_result

        task = _make_task_response(mission_uuid, qa_contract, status="OPEN")
        patcher, _ = _mock_http_seq(
            "get", [(200, task), _httpx.RequestError("boom")])
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "pending"
            assert "error" not in response
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_uses_latest_proof(self, mission_uuid, qa_contract):
        """With multiple proofs, the most recently submitted one wins."""
        from groundtruther_mcp.tools_qa import get_qa_result

        old_proof = _make_qa_proof(
            [("s1", "fail", "Login broken"), ("s2", "blocked", "Blocked by step 1")],
            "fail", submitted_at="2026-08-29T09:00:00Z")
        new_proof = _make_qa_proof(
            [("s1", "pass", None), ("s2", "pass", None)],
            "pass", submitted_at="2026-08-30T15:00:00Z",
            recording_url="https://loom.com/share/retest")
        # Deliberately out of order
        task = _make_task_response(
            mission_uuid, qa_contract, status="PROOF_SUBMITTED", proofs=[new_proof, old_proof])
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["overall_verdict"] == "pass"
            assert response["failed_steps"] == []
            assert response["recording_url"] == "https://loom.com/share/retest"
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_get_qa_result_cancelled(self, mission_uuid, qa_contract):
        """Terminal non-QA-outcome statuses are surfaced honestly."""
        from groundtruther_mcp.tools_qa import get_qa_result

        task = _make_task_response(mission_uuid, qa_contract, status="CANCELLED")
        patcher, _ = _mock_http("get", 200, task)
        try:
            response = json.loads(await get_qa_result(mission_uuid))
            assert response["status"] == "cancelled"
            assert response["next_action"]
        finally:
            patcher.stop()
