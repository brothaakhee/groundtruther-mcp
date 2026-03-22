"""Tests for GroundTruther MCP tools using mocked HTTP calls."""
import pytest
import json
import os
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
from decimal import Decimal
import httpx


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
def api_key():
    """Sample API key for testing."""
    return "gt_sk_test_123456789"


@pytest.fixture
def api_base_url():
    """Sample API base URL."""
    return "http://localhost:8000/api/v1"


@pytest.fixture
def mission_uuid():
    """Sample task UUID."""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def template_uuid():
    """Sample template UUID."""
    return "550e8400-e29b-41d4-a716-446655440001"


class TestPostMission:
    """Tests for post_mission tool."""

    @pytest.mark.asyncio
    async def test_post_task_success(self, api_key, api_base_url, mission_uuid):
        """Test successful task creation."""
        from groundtruther_mcp.tools import post_mission

        request_body = {
            "title": "Find a coffee shop",
            "description": "Find a good coffee shop near downtown",
            "latitude": "40.7128",
            "longitude": "-74.0060",
            "radius_km": "5",
            "deadline": (datetime.now() + timedelta(days=7)).isoformat(),
            "budget_amount": "50.00",
            "category": "location-based",
        }

        response_data = {
            "id": mission_uuid,
            "title": "Find a coffee shop",
            "description": "Find a good coffee shop near downtown",
            "status": "OPEN",
            "budget_amount": "50.00",
            "created_at": datetime.now().isoformat(),
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await post_mission(
                title="Find a coffee shop",
                description="Find a good coffee shop near downtown",
                lat=40.7128,
                lng=-74.0060,
                radius_km=5.0,
                deadline=(datetime.now() + timedelta(days=7)).isoformat(),
                budget_amount=50.00,
                category="location-based",
                template_id=None,
            )

            # Verify API call was made
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "/tasks/" in call_args[0][0]
            assert "Bearer gt_sk_" in call_args[1]["headers"]["Authorization"]

            # Verify response
            response = json.loads(result)
            assert response["id"] == mission_uuid
            assert response["status"] == "OPEN"

    @pytest.mark.asyncio
    async def test_post_task_with_template(self, api_key, api_base_url, mission_uuid, template_uuid):
        """Test task creation with template."""
        from groundtruther_mcp.tools import post_mission

        response_data = {
            "id": mission_uuid,
            "title": "Find a coffee shop",
            "status": "OPEN",
            "template": {"id": template_uuid, "name": "Location Finding"},
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await post_mission(
                title="Find a coffee shop",
                description="Find a good coffee shop near downtown",
                lat=40.7128,
                lng=-74.0060,
                radius_km=5.0,
                deadline=(datetime.now() + timedelta(days=7)).isoformat(),
                budget_amount=50.00,
                category="location-based",
                template_id=template_uuid,
            )

            response = json.loads(result)
            assert response["template"]["id"] == str(template_uuid)

    @pytest.mark.asyncio
    async def test_post_task_insufficient_funds(self, api_key, api_base_url):
        """Test task creation with insufficient funds (402 error)."""
        from groundtruther_mcp.tools import post_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 402
            mock_response.json.return_value = {
                "detail": "Insufficient funds. Balance: 10.00, Required: 50.00"
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await post_mission(
                title="Expensive task",
                description="This is too expensive",
                lat=40.7128,
                lng=-74.0060,
                radius_km=5.0,
                deadline=(datetime.now() + timedelta(days=7)).isoformat(),
                budget_amount=999.00,
                category="location-based",
            )

            response = json.loads(result)
            assert "error" in response
            assert "Insufficient funds" in response["error"]

    @pytest.mark.asyncio
    async def test_post_task_invalid_request(self, api_key, api_base_url):
        """Test task creation with invalid data (400 error)."""
        from groundtruther_mcp.tools import post_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "title": ["This field is required."]
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await post_mission(
                title="",
                description="Missing title",
                lat=40.7128,
                lng=-74.0060,
                radius_km=5.0,
                deadline=(datetime.now() + timedelta(days=7)).isoformat(),
                budget_amount=50.00,
                category="location-based",
            )

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_post_task_unauthorized(self, api_key, api_base_url):
        """Test task creation with invalid API key (401 error)."""
        from groundtruther_mcp.tools import post_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await post_mission(
                title="Task",
                description="Description",
                lat=40.7128,
                lng=-74.0060,
                radius_km=5.0,
                deadline=(datetime.now() + timedelta(days=7)).isoformat(),
                budget_amount=50.00,
                category="location-based",
            )

            response = json.loads(result)
            assert "error" in response


class TestCheckMissionStatus:
    """Tests for check_task_status tool."""

    @pytest.mark.asyncio
    async def test_check_task_status_success(self, api_key, api_base_url, mission_uuid):
        """Test successfully checking task status."""
        from groundtruther_mcp.tools import check_mission_status

        response_data = {
            "id": mission_uuid,
            "title": "Find a coffee shop",
            "status": "CLAIMED",
            "budget_amount": "50.00",
            "claimed_by": "worker_123",
            "created_at": datetime.now().isoformat(),
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await check_mission_status(mission_uuid)

            # Verify API call
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert f"/tasks/{mission_uuid}/" in call_args[0][0]

            # Verify response
            response = json.loads(result)
            assert response["id"] == mission_uuid
            assert response["status"] == "CLAIMED"

    @pytest.mark.asyncio
    async def test_check_task_status_not_found(self, api_key, api_base_url, mission_uuid):
        """Test checking status of non-existent task (404 error)."""
        from groundtruther_mcp.tools import check_mission_status

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {"detail": "Task not found."}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await check_mission_status(mission_uuid)

            response = json.loads(result)
            assert "error" in response
            assert "not found" in response["error"].lower()

    @pytest.mark.asyncio
    async def test_check_task_status_unauthorized(self, api_key, api_base_url, mission_uuid):
        """Test checking task status with invalid API key."""
        from groundtruther_mcp.tools import check_mission_status

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await check_mission_status(mission_uuid)

            response = json.loads(result)
            assert "error" in response


class TestListMyMissions:
    """Tests for list_my_missions tool."""

    @pytest.mark.asyncio
    async def test_list_my_tasks_success(self, api_key, api_base_url, mission_uuid):
        """Test successfully listing agent's tasks."""
        from groundtruther_mcp.tools import list_my_missions

        response_data = {
            "results": [
                {
                    "id": mission_uuid,
                    "title": "Find a coffee shop",
                    "status": "OPEN",
                    "budget_amount": "50.00",
                    "created_at": datetime.now().isoformat(),
                },
                {
                    "id": "550e8400-e29b-41d4-a716-446655440002",
                    "title": "Find a restaurant",
                    "status": "CLAIMED",
                    "budget_amount": "75.00",
                    "created_at": datetime.now().isoformat(),
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await list_my_missions()

            # Verify API call
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert "/tasks/" in call_args[0][0]

            # Verify response
            response = json.loads(result)
            assert len(response["results"]) == 2
            assert response["results"][0]["status"] == "OPEN"

    @pytest.mark.asyncio
    async def test_list_my_tasks_with_filters(self, api_key, api_base_url, mission_uuid):
        """Test listing tasks with status and category filters."""
        from groundtruther_mcp.tools import list_my_missions

        response_data = {
            "results": [
                {
                    "id": mission_uuid,
                    "title": "Find a coffee shop",
                    "status": "OPEN",
                    "category": "location-based",
                    "budget_amount": "50.00",
                    "created_at": datetime.now().isoformat(),
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await list_my_missions(status="OPEN", category="location-based")

            # Verify query parameters were included
            call_args = mock_client.get.call_args
            assert "status=OPEN" in call_args[0][0] or "status" in str(call_args)

            response = json.loads(result)
            assert len(response["results"]) == 1

    @pytest.mark.asyncio
    async def test_list_my_tasks_empty(self, api_key, api_base_url):
        """Test listing tasks when agent has none."""
        from groundtruther_mcp.tools import list_my_missions

        response_data = {"results": []}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await list_my_missions()

            response = json.loads(result)
            assert response["results"] == []

    @pytest.mark.asyncio
    async def test_list_my_tasks_unauthorized(self, api_key, api_base_url):
        """Test listing tasks with invalid API key."""
        from groundtruther_mcp.tools import list_my_missions

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await list_my_missions()

            response = json.loads(result)
            assert "error" in response


class TestApproveMission:
    """Tests for approve_mission tool."""

    @pytest.mark.asyncio
    async def test_approve_task_success(self, api_key, api_base_url, mission_uuid):
        """Test successfully approving a task."""
        from groundtruther_mcp.tools import approve_mission

        response_data = {
            "id": mission_uuid,
            "title": "Find a coffee shop",
            "status": "COMPLETED",
            "budget_amount": "50.00",
            "completed_at": datetime.now().isoformat(),
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await approve_mission(mission_uuid)

            # Verify API call
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert f"/tasks/{mission_uuid}/approve/" in call_args[0][0]

            # Verify response
            response = json.loads(result)
            assert response["id"] == mission_uuid
            assert response["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_approve_task_not_found(self, api_key, api_base_url, mission_uuid):
        """Test approving non-existent task."""
        from groundtruther_mcp.tools import approve_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {"detail": "Task not found."}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await approve_mission(mission_uuid)

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_approve_task_invalid_state(self, api_key, api_base_url, mission_uuid):
        """Test approving task in invalid state (400 error)."""
        from groundtruther_mcp.tools import approve_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "detail": "Cannot approve task in OPEN status. Only PROOF_SUBMITTED tasks can be approved."
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await approve_mission(mission_uuid)

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_approve_task_unauthorized(self, api_key, api_base_url, mission_uuid):
        """Test approving task with invalid API key."""
        from groundtruther_mcp.tools import approve_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await approve_mission(mission_uuid)

            response = json.loads(result)
            assert "error" in response


class TestRejectMission:
    """Tests for reject_mission tool."""

    @pytest.mark.asyncio
    async def test_reject_task_success(self, api_key, api_base_url, mission_uuid):
        """Test successfully rejecting a task."""
        from groundtruther_mcp.tools import reject_mission

        response_data = {
            "id": mission_uuid,
            "title": "Find a coffee shop",
            "status": "IN_PROGRESS",
            "budget_amount": "50.00",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await reject_mission(mission_uuid, "Image quality is poor")

            # Verify API call
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert f"/tasks/{mission_uuid}/reject/" in call_args[0][0]
            # Verify reason was sent in body
            assert call_args[1]["json"]["reason"] == "Image quality is poor"

            # Verify response
            response = json.loads(result)
            assert response["id"] == mission_uuid
            assert response["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_reject_task_not_found(self, api_key, api_base_url, mission_uuid):
        """Test rejecting non-existent task."""
        from groundtruther_mcp.tools import reject_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {"detail": "Task not found."}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await reject_mission(mission_uuid, "Invalid proof")

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_reject_task_invalid_state(self, api_key, api_base_url, mission_uuid):
        """Test rejecting task in invalid state."""
        from groundtruther_mcp.tools import reject_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "detail": "Cannot reject task in OPEN status. Only PROOF_SUBMITTED tasks can be rejected."
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await reject_mission(mission_uuid, "Invalid proof")

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_reject_task_unauthorized(self, api_key, api_base_url, mission_uuid):
        """Test rejecting task with invalid API key."""
        from groundtruther_mcp.tools import reject_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await reject_mission(mission_uuid, "Invalid proof")

            response = json.loads(result)
            assert "error" in response


class TestGetTemplates:
    """Tests for get_templates tool."""

    @pytest.mark.asyncio
    async def test_get_templates_success(self, api_key, api_base_url, template_uuid):
        """Test successfully getting task templates."""
        from groundtruther_mcp.tools import get_templates

        response_data = {
            "results": [
                {
                    "id": template_uuid,
                    "name": "Location Finding",
                    "category": "location-based",
                    "description": "Find a location based on criteria",
                    "min_budget": "10.00",
                    "estimated_duration_minutes": 30,
                    "is_active": True,
                },
                {
                    "id": "550e8400-e29b-41d4-a716-446655440002",
                    "name": "Photo Collection",
                    "category": "photography",
                    "description": "Collect photos of locations",
                    "min_budget": "20.00",
                    "estimated_duration_minutes": 60,
                    "is_active": True,
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await get_templates()

            # Verify API call
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert "/templates/" in call_args[0][0]

            # Verify response (templates endpoint uses AllowAny, no auth needed)
            response = json.loads(result)
            assert len(response["results"]) == 2
            assert response["results"][0]["name"] == "Location Finding"

    @pytest.mark.asyncio
    async def test_get_templates_empty(self, api_key, api_base_url):
        """Test getting templates when none are available."""
        from groundtruther_mcp.tools import get_templates

        response_data = {"results": []}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await get_templates()

            response = json.loads(result)
            assert response["results"] == []

    @pytest.mark.asyncio
    async def test_get_templates_network_error(self, api_key, api_base_url):
        """Test getting templates with network error."""
        from groundtruther_mcp.tools import get_templates

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection failed")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await get_templates()

            response = json.loads(result)
            assert "error" in response


class TestCheckBalance:
    """Tests for check_balance tool."""

    @pytest.mark.asyncio
    async def test_check_balance_success(self, api_key, api_base_url):
        """Test successfully checking wallet balance."""
        from groundtruther_mcp.tools import check_balance

        response_data = {
            "id": "wallet-uuid",
            "balance": "1000.50",
            "currency": "USD",
            "recent_transactions": [
                {
                    "id": "txn-1",
                    "type": "deposit",
                    "amount": "500.00",
                    "created_at": datetime.now().isoformat(),
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await check_balance()

            # Verify API call
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert "/wallet/" in call_args[0][0]

            # Verify response
            response = json.loads(result)
            assert response["balance"] == "1000.50"
            assert response["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_check_balance_zero(self, api_key, api_base_url):
        """Test checking balance with zero funds."""
        from groundtruther_mcp.tools import check_balance

        response_data = {
            "id": "wallet-uuid",
            "balance": "0.00",
            "currency": "USD",
            "recent_transactions": []
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await check_balance()

            response = json.loads(result)
            assert response["balance"] == "0.00"

    @pytest.mark.asyncio
    async def test_check_balance_unauthorized(self, api_key, api_base_url):
        """Test checking balance with invalid API key."""
        from groundtruther_mcp.tools import check_balance

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid or missing API key"}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await check_balance()

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_check_balance_network_error(self, api_key, api_base_url):
        """Test checking balance with network error."""
        from groundtruther_mcp.tools import check_balance

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.RequestError("Network error")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await check_balance()

            response = json.loads(result)
            assert "error" in response


class TestSendMessage:
    """Tests for send_message tool."""

    @pytest.mark.asyncio
    async def test_send_message_success(self, api_key, api_base_url, mission_uuid):
        """Test successfully sending a message."""
        from groundtruther_mcp.tools import send_message

        response_data = {
            "id": "msg-uuid",
            "task_id": mission_uuid,
            "sender_type": "agent",
            "content": "Please include the sign in your photo",
            "attachments": [],
            "created_at": datetime.now().isoformat(),
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await send_message(mission_uuid, "Please include the sign in your photo")

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert f"/tasks/{mission_uuid}/messages/" in call_args[0][0]
            assert call_args[1]["json"]["content"] == "Please include the sign in your photo"

            response = json.loads(result)
            assert response["sender_type"] == "agent"

    @pytest.mark.asyncio
    async def test_send_message_task_completed(self, api_key, api_base_url, mission_uuid):
        """Test sending message on completed task (400 error)."""
        from groundtruther_mcp.tools import send_message

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "detail": "Messages are only available on CLAIMED, IN_PROGRESS, or PROOF_SUBMITTED tasks."
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await send_message(mission_uuid, "Thanks!")

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_send_message_unauthorized(self, api_key, api_base_url, mission_uuid):
        """Test sending message with invalid API key."""
        from groundtruther_mcp.tools import send_message

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await send_message(mission_uuid, "Hello")

            response = json.loads(result)
            assert "error" in response


class TestGetMessages:
    """Tests for get_messages tool."""

    @pytest.mark.asyncio
    async def test_get_messages_success(self, api_key, api_base_url, mission_uuid):
        """Test successfully getting messages."""
        from groundtruther_mcp.tools import get_messages

        response_data = {
            "results": [
                {
                    "id": "msg-1",
                    "sender_type": "agent",
                    "content": "Please include the sign",
                    "created_at": datetime.now().isoformat(),
                },
                {
                    "id": "msg-2",
                    "sender_type": "worker",
                    "content": "Will do!",
                    "created_at": datetime.now().isoformat(),
                },
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await get_messages(mission_uuid)

            mock_client.get.assert_called_once()
            response = json.loads(result)
            assert len(response["results"]) == 2

    @pytest.mark.asyncio
    async def test_get_messages_empty(self, api_key, api_base_url, mission_uuid):
        """Test getting messages when none exist."""
        from groundtruther_mcp.tools import get_messages

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"results": []}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await get_messages(mission_uuid)

            response = json.loads(result)
            assert response["results"] == []

    @pytest.mark.asyncio
    async def test_get_messages_unauthorized(self, api_key, api_base_url, mission_uuid):
        """Test getting messages with invalid API key."""
        from groundtruther_mcp.tools import get_messages

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await get_messages(mission_uuid)

            response = json.loads(result)
            assert "error" in response


class TestCancelMission:
    """Tests for cancel_mission tool."""

    @pytest.mark.asyncio
    async def test_cancel_open_task(self, api_key, api_base_url, mission_uuid):
        """Test cancelling an OPEN task (immediate)."""
        from groundtruther_mcp.tools import cancel_mission

        response_data = {
            "id": mission_uuid,
            "status": "CANCELLED",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await cancel_mission(mission_uuid, "No longer needed")

            mock_client.post.assert_called_once()
            response = json.loads(result)
            assert response["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_cancel_in_progress_mutual(self, api_key, api_base_url, mission_uuid):
        """Test cancelling IN_PROGRESS task (mutual consent, 202)."""
        from groundtruther_mcp.tools import cancel_mission

        response_data = {
            "id": mission_uuid,
            "status": "IN_PROGRESS",
            "cancellation_requested_by": "agent",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 202
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await cancel_mission(mission_uuid, "Budget cut")

            response = json.loads(result)
            assert "_note" in response
            assert "Waiting for worker consent" in response["_note"]

    @pytest.mark.asyncio
    async def test_cancel_task_invalid_state(self, api_key, api_base_url, mission_uuid):
        """Test cancelling a COMPLETED task (400 error)."""
        from groundtruther_mcp.tools import cancel_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {"detail": "Cannot cancel completed task"}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await cancel_mission(mission_uuid)

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_cancel_task_unauthorized(self, api_key, api_base_url, mission_uuid):
        """Test cancelling task with invalid API key."""
        from groundtruther_mcp.tools import cancel_mission

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await cancel_mission(mission_uuid)

            response = json.loads(result)
            assert "error" in response


class TestPollEvents:
    """Tests for poll_events tool."""

    @pytest.mark.asyncio
    async def test_poll_events_success(self, api_key, api_base_url):
        """Test successfully polling events."""
        from groundtruther_mcp.tools import poll_events

        response_data = {
            "results": [
                {
                    "id": "evt-1",
                    "event_type": "task_claimed",
                    "task_id": "task-uuid",
                    "created_at": datetime.now().isoformat(),
                },
                {
                    "id": "evt-2",
                    "event_type": "proof_submitted",
                    "task_id": "task-uuid",
                    "created_at": datetime.now().isoformat(),
                },
            ],
            "count": 2,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await poll_events()

            mock_client.get.assert_called_once()
            response = json.loads(result)
            assert len(response["results"]) == 2

    @pytest.mark.asyncio
    async def test_poll_events_with_since(self, api_key, api_base_url):
        """Test polling events with since parameter."""
        from groundtruther_mcp.tools import poll_events

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"results": [], "count": 0}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            since = "2026-03-14T00:00:00Z"
            result = await poll_events(since=since, limit=10)

            call_args = mock_client.get.call_args
            assert "since" in str(call_args) or since in str(call_args)

    @pytest.mark.asyncio
    async def test_poll_events_unauthorized(self, api_key, api_base_url):
        """Test polling events with invalid API key."""
        from groundtruther_mcp.tools import poll_events

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await poll_events()

            response = json.loads(result)
            assert "error" in response


class TestSubmitReview:
    """Tests for submit_review tool."""

    @pytest.mark.asyncio
    async def test_submit_review_success(self, api_key, api_base_url, mission_uuid):
        """Test successfully submitting a review."""
        from groundtruther_mcp.tools import submit_review

        response_data = {
            "id": "review-uuid",
            "task": mission_uuid,
            "reviewer_type": "agent",
            "rating": 5,
            "comment": "Excellent work",
            "created_at": datetime.now().isoformat(),
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await submit_review(mission_uuid, 5, "Excellent work")

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert f"/tasks/{mission_uuid}/review/" in call_args[0][0]
            assert call_args[1]["json"]["rating"] == 5

            response = json.loads(result)
            assert response["rating"] == 5

    @pytest.mark.asyncio
    async def test_submit_review_invalid_rating(self, api_key, api_base_url, mission_uuid):
        """Test submitting review with invalid rating."""
        from groundtruther_mcp.tools import submit_review

        result = await submit_review(mission_uuid, 6)

        response = json.loads(result)
        assert "error" in response
        assert "between 1 and 5" in response["error"]

    @pytest.mark.asyncio
    async def test_submit_review_duplicate(self, api_key, api_base_url, mission_uuid):
        """Test submitting duplicate review (400 error)."""
        from groundtruther_mcp.tools import submit_review

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "detail": "You have already reviewed this task."
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await submit_review(mission_uuid, 4)

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_submit_review_not_completed(self, api_key, api_base_url, mission_uuid):
        """Test submitting review on non-completed task."""
        from groundtruther_mcp.tools import submit_review

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "detail": "Reviews can only be submitted for completed tasks."
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await submit_review(mission_uuid, 3)

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_submit_review_unauthorized(self, api_key, api_base_url, mission_uuid):
        """Test submitting review with invalid API key."""
        from groundtruther_mcp.tools import submit_review

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await submit_review(mission_uuid, 4)

            response = json.loads(result)
            assert "error" in response


class TestRespondToCancellation:
    """Tests for respond_to_cancellation tool."""

    @pytest.mark.asyncio
    async def test_approve_cancellation_success(self, api_key, api_base_url, mission_uuid):
        """Test approving a worker's cancellation request."""
        from groundtruther_mcp.tools import respond_to_cancellation

        response_data = {
            "id": mission_uuid,
            "status": "CANCELLED",
            "cancellation_requested_by": "worker",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await respond_to_cancellation(mission_uuid, "approve")

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert f"/tasks/{mission_uuid}/cancel/approve/" in call_args[0][0]

            response = json.loads(result)
            assert response["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_decline_cancellation_success(self, api_key, api_base_url, mission_uuid):
        """Test declining a worker's cancellation request."""
        from groundtruther_mcp.tools import respond_to_cancellation

        response_data = {
            "id": mission_uuid,
            "status": "IN_PROGRESS",
            "cancellation_requested_by": None,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await respond_to_cancellation(mission_uuid, "decline", "Worker must complete")

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert f"/tasks/{mission_uuid}/cancel/decline/" in call_args[0][0]
            assert call_args[1]["json"]["reason"] == "Worker must complete"

            response = json.loads(result)
            assert response["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_invalid_action(self, api_key, api_base_url, mission_uuid):
        """Test with invalid action value."""
        from groundtruther_mcp.tools import respond_to_cancellation

        result = await respond_to_cancellation(mission_uuid, "reject")

        response = json.loads(result)
        assert "error" in response
        assert "approve" in response["error"]

    @pytest.mark.asyncio
    async def test_no_pending_cancellation(self, api_key, api_base_url, mission_uuid):
        """Test responding when no cancellation is pending."""
        from groundtruther_mcp.tools import respond_to_cancellation

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "detail": "No pending cancellation request on this task."
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await respond_to_cancellation(mission_uuid, "approve")

            response = json.loads(result)
            assert "error" in response

    @pytest.mark.asyncio
    async def test_unauthorized(self, api_key, api_base_url, mission_uuid):
        """Test with invalid API key."""
        from groundtruther_mcp.tools import respond_to_cancellation

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"detail": "Invalid API key"}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await respond_to_cancellation(mission_uuid, "approve")

            response = json.loads(result)
            assert "error" in response


class TestGetCategories:
    """Tests for get_categories tool."""

    @pytest.mark.asyncio
    async def test_get_categories_success(self, api_key, api_base_url):
        """Test successfully getting categories."""
        from groundtruther_mcp.tools import get_categories

        response_data = [
            {"value": "PHYSICAL_WORLD", "label": "Physical World", "color": "#3B82F6"},
            {"value": "IDENTITY_LEGAL", "label": "Identity & Legal", "color": "#8B5CF6"},
            {"value": "EMBODIED_JUDGMENT", "label": "Embodied Judgment", "color": "#22C55E"},
        ]

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_data
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await get_categories()

            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert "/tasks/categories/" in call_args[0][0]
            # Verify no auth header (public endpoint)
            headers = call_args[1].get("headers", {})
            assert "Authorization" not in headers

            response = json.loads(result)
            assert len(response) == 3
            assert response[0]["value"] == "PHYSICAL_WORLD"

    @pytest.mark.asyncio
    async def test_get_categories_network_error(self, api_key, api_base_url):
        """Test getting categories with network error."""
        from groundtruther_mcp.tools import get_categories

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.RequestError("Network error")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await get_categories()

            response = json.loads(result)
            assert "error" in response


class TestPostMissionExtended:
    """Tests for post_mission tool with new parameters."""

    @pytest.mark.asyncio
    async def test_post_task_with_verification_type(self, api_key, api_base_url, mission_uuid):
        """Test task creation with verification_type."""
        from groundtruther_mcp.tools import post_mission

        response_data = {"id": mission_uuid, "status": "OPEN", "verification_type": "STRUCTURED_DATA"}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await post_mission(
                title="Survey",
                description="Fill out survey",
                lat=40.7128,
                lng=-74.0060,
                radius_km=5.0,
                deadline="2026-04-01T00:00:00Z",
                budget_amount=25.00,
                category="PHYSICAL_WORLD",
                verification_type="STRUCTURED_DATA",
            )

            call_args = mock_client.post.call_args
            payload = call_args[1]["json"]
            assert payload["verification_type"] == "STRUCTURED_DATA"

            response = json.loads(result)
            assert response["verification_type"] == "STRUCTURED_DATA"

    @pytest.mark.asyncio
    async def test_post_task_with_acceptance_contract(self, api_key, api_base_url, mission_uuid):
        """Test task creation with acceptance_contract JSON."""
        from groundtruther_mcp.tools import post_mission

        contract = json.dumps({
            "required_fields": [{"name": "store_name", "type": "text", "label": "Store Name"}],
            "min_photos": 2,
            "require_gps": True,
        })

        response_data = {"id": mission_uuid, "status": "OPEN"}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = response_data
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await post_mission(
                title="Store check",
                description="Check store details",
                lat=40.7128,
                lng=-74.0060,
                radius_km=5.0,
                deadline="2026-04-01T00:00:00Z",
                budget_amount=25.00,
                category="PHYSICAL_WORLD",
                acceptance_contract=contract,
            )

            call_args = mock_client.post.call_args
            payload = call_args[1]["json"]
            assert "acceptance_contract" in payload
            assert payload["acceptance_contract"]["min_photos"] == 2

    @pytest.mark.asyncio
    async def test_post_task_with_invalid_contract_json(self, api_key, api_base_url):
        """Test task creation with invalid acceptance_contract JSON."""
        from groundtruther_mcp.tools import post_mission

        result = await post_mission(
            title="Test",
            description="Test",
            lat=40.7128,
            lng=-74.0060,
            radius_km=5.0,
            deadline="2026-04-01T00:00:00Z",
            budget_amount=25.00,
            category="PHYSICAL_WORLD",
            acceptance_contract="not valid json{",
        )

        response = json.loads(result)
        assert "error" in response
        assert "valid JSON" in response["error"]
