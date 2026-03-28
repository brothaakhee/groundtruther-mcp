"""MCP tool implementations for GroundTruther."""
import json
from datetime import datetime
from typing import Optional, Dict, Any
import httpx
from .client import APIClient


def _error_response(message: str) -> str:
    """Create an error response JSON string."""
    return json.dumps({"error": message})


async def post_mission(
    title: str,
    description: str,
    deadline: str,
    budget_amount: float,
    category: str,
    acceptance_contract: str,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_mi: Optional[float] = None,
    template_id: Optional[str] = None,
) -> str:
    """
    Create a new mission.

    Args:
        title: Mission title
        description: Mission description
        deadline: Mission deadline (ISO format)
        budget_amount: Budget in USD
        category: Mission category (PHYSICAL_WORLD, IDENTITY_LEGAL, OFFLINE_GATED,
                  EMBODIED_JUDGMENT, SOCIAL_RELATIONAL, EXPERT_CURATION, DELIVERY, DIGITAL_REMOTE)
        acceptance_contract: JSON string defining what proof the worker must submit.
                  Valid keys: "notes" (required), "required_media", "required_fields",
                  "required_urls", "gps_required", "gps_max_distance_mi",
                  "gps_required_at_waypoints", "min_photos_per_waypoint".
                  Must include "notes" and at least one of: required_media, required_fields, required_urls.
        lat: Latitude for mission location (required for physical categories, omit for DIGITAL_REMOTE)
        lng: Longitude for mission location
        radius_mi: Search radius in miles
        template_id: Optional mission template UUID

    Returns:
        JSON string with mission details or error
    """
    try:
        client = APIClient()

        # Parse acceptance_contract
        try:
            parsed_contract = json.loads(acceptance_contract)
        except json.JSONDecodeError:
            return _error_response("acceptance_contract must be valid JSON")

        # Build request payload
        payload = {
            "title": title,
            "description": description,
            "deadline": deadline,
            "budget_amount": budget_amount,
            "category": category,
            "acceptance_contract": parsed_contract,
        }

        if lat is not None:
            payload["latitude"] = lat
        if lng is not None:
            payload["longitude"] = lng
        if radius_mi is not None:
            payload["radius_mi"] = radius_mi
        if template_id:
            payload["template_id"] = template_id

        # Make API call
        response = await client.post("/tasks/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] == 201:
            return json.dumps(result["data"])
        elif result["status_code"] == 402:
            return _error_response(
                result["data"].get("detail", "Payment required (insufficient funds)")
            )
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        elif result["status_code"] == 400:
            return _error_response(
                f"Bad request: {result['data']}"
            )
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def check_mission_status(mission_uuid: str) -> str:
    """
    Get mission details and current status.

    Args:
        mission_uuid: Mission UUID

    Returns:
        JSON string with mission details or error
    """
    try:
        client = APIClient()

        # Make API call
        response = await client.get(f"/tasks/{mission_uuid}/")
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 404:
            return _error_response(f"Mission not found: {mission_uuid}")
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def list_my_missions(
    status: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """
    List agent's missions with optional filtering.

    Args:
        status: Filter by status (e.g., 'OPEN', 'CLAIMED', 'COMPLETED')
        category: Filter by category (e.g., 'location-based')

    Returns:
        JSON string with list of missions or error
    """
    try:
        client = APIClient()

        # Build query parameters
        params = {}
        if status:
            params["status"] = status
        if category:
            params["category"] = category

        # Make API call
        response = await client.get("/tasks/", params=params)
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def approve_mission(mission_uuid: str) -> str:
    """
    Approve a mission proof and release payment.

    Args:
        mission_uuid: Mission UUID

    Returns:
        JSON string with updated mission details or error
    """
    try:
        client = APIClient()

        # Make API call (POST with no body)
        response = await client.post(f"/tasks/{mission_uuid}/approve/", data={})
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 404:
            return _error_response(f"Mission not found: {mission_uuid}")
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot approve mission in current state")
            )
        elif result["status_code"] == 409:
            return _error_response(
                result["data"].get("detail", "Cannot approve — cancellation is pending")
            )
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def reject_mission(mission_uuid: str, reason: str) -> str:
    """
    Reject a mission proof and return mission to IN_PROGRESS.

    Args:
        mission_uuid: Mission UUID
        reason: Reason for rejection (max 500 chars)

    Returns:
        JSON string with updated mission details or error
    """
    try:
        client = APIClient()

        # Build request payload
        payload = {"reason": reason}

        # Make API call
        response = await client.post(
            f"/tasks/{mission_uuid}/reject/", data=payload
        )
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 404:
            return _error_response(f"Mission not found: {mission_uuid}")
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot reject mission in current state")
            )
        elif result["status_code"] == 409:
            return _error_response(
                result["data"].get("detail", "Cannot reject — cancellation is pending")
            )
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def escalate_mission(mission_uuid: str, note: str) -> str:
    """
    Escalate a disputed mission for manual review.

    Args:
        mission_uuid: Mission UUID
        note: Explanation of the dispute for manual review

    Returns:
        JSON string with escalation details or error
    """
    try:
        client = APIClient()
        payload = {"note": note}
        response = await client.post(f"/tasks/{mission_uuid}/escalate/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] == 201:
            return json.dumps(result["data"])
        elif result["status_code"] == 404:
            return _error_response(f"Mission not found: {mission_uuid}")
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get(
                    "detail",
                    "Mission escalation is only available after at least one proof rejection",
                )
            )
        elif result["status_code"] == 409:
            return _error_response(
                result["data"].get("detail", "An escalation is already open for this mission")
            )
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def get_templates() -> str:
    """
    Get list of available mission templates.

    Templates endpoint uses AllowAny permission (no authentication required).

    Returns:
        JSON string with list of templates or error
    """
    try:
        client = APIClient()

        # Make API call (no auth needed for templates)
        response = await client.get("/templates/", use_auth=False)
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def check_balance() -> str:
    """
    Check agent owner's wallet balance.

    Note: This endpoint requires JWT authentication (agent owner token).
    The API key authentication is typically used for mission operations.
    For MVP, this tool calls the wallet endpoint but may need agent owner JWT.

    Returns:
        JSON string with wallet balance and recent transactions or error
    """
    try:
        client = APIClient()

        # Make API call
        response = await client.get("/wallet/")
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 401:
            return _error_response(
                "Unauthorized: Wallet endpoint requires agent owner authentication. "
                "This tool requires the agent owner's JWT token, not API key."
            )
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def send_message(mission_uuid: str, content: str) -> str:
    """
    Send a message to the worker on a mission.

    Args:
        mission_uuid: Mission UUID
        content: Message content (max 2000 chars)

    Returns:
        JSON string with message details or error
    """
    try:
        client = APIClient()
        payload = {"content": content, "attachments": []}
        response = await client.post(f"/tasks/{mission_uuid}/messages/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] == 201:
            return json.dumps(result["data"])
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot send message on this mission")
            )
        elif result["status_code"] == 404:
            return _error_response(f"Mission not found: {mission_uuid}")
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        elif result["status_code"] == 403:
            return _error_response("Forbidden: Not authorized to message on this mission")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def get_messages(mission_uuid: str) -> str:
    """
    Get all messages for a mission.

    Fetching messages also marks unread messages from the other party as read.

    Args:
        mission_uuid: Mission UUID

    Returns:
        JSON string with list of messages or error
    """
    try:
        client = APIClient()
        response = await client.get(f"/tasks/{mission_uuid}/messages/")
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot view messages on this mission")
            )
        elif result["status_code"] == 404:
            return _error_response(f"Mission not found: {mission_uuid}")
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def cancel_mission(mission_uuid: str, reason: Optional[str] = None) -> str:
    """
    Cancel a mission.

    For OPEN or CLAIMED missions, cancellation is immediate and escrow is refunded.
    For IN_PROGRESS missions, this requests mutual cancellation from the worker
    (returns 202 Accepted while waiting for worker consent).

    Args:
        mission_uuid: Mission UUID
        reason: Optional reason for cancellation

    Returns:
        JSON string with updated mission details or error
    """
    try:
        client = APIClient()
        payload = {}
        if reason:
            payload["reason"] = reason

        response = await client.post(f"/tasks/{mission_uuid}/cancel/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] in (200, 202):
            data = result["data"]
            if result["status_code"] == 202:
                data["_note"] = "Cancellation requested. Waiting for worker consent."
            return json.dumps(data)
        elif result["status_code"] == 404:
            return _error_response(f"Mission not found: {mission_uuid}")
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot cancel mission in current state")
            )
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def poll_events(since: Optional[str] = None, limit: Optional[int] = None) -> str:
    """
    Poll for agent events (mission claimed, proof submitted, mission completed, etc.).

    Args:
        since: ISO 8601 timestamp — only return events after this time
        limit: Max number of events to return (default 20, max 100)

    Returns:
        JSON string with list of events or error
    """
    try:
        client = APIClient()
        params = {}
        if since:
            params["since"] = since
        if limit:
            params["limit"] = str(limit)

        response = await client.get("/events/", params=params)
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def submit_review(mission_uuid: str, rating: int, comment: Optional[str] = None) -> str:
    """
    Submit a review/rating for the worker after mission completion.

    Args:
        mission_uuid: Mission UUID (must be COMPLETED)
        rating: Rating from 1 to 5
        comment: Optional comment (max 2000 chars)

    Returns:
        JSON string with review details or error
    """
    try:
        if not 1 <= rating <= 5:
            return _error_response("Rating must be between 1 and 5")

        client = APIClient()
        payload = {"rating": rating, "comment": comment or ""}
        response = await client.post(f"/tasks/{mission_uuid}/review/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] == 201:
            return json.dumps(result["data"])
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot submit review")
            )
        elif result["status_code"] == 404:
            return _error_response(f"Mission not found: {mission_uuid}")
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        elif result["status_code"] == 403:
            return _error_response("Forbidden: Not authorized to review this mission")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def respond_to_cancellation(mission_uuid: str, action: str, reason: Optional[str] = None) -> str:
    """
    Approve or decline a worker's cancellation/drop request.

    When a worker requests to drop a mission, the agent must approve or decline.
    Approving cancels the mission and refunds escrow. Declining keeps the mission active.

    Args:
        mission_uuid: Mission UUID
        action: 'approve' or 'decline'
        reason: Optional reason (used when declining)

    Returns:
        JSON string with updated mission details or error
    """
    if action not in ("approve", "decline"):
        return _error_response("Action must be 'approve' or 'decline'")

    try:
        client = APIClient()
        payload = {}
        if reason:
            payload["reason"] = reason

        response = await client.post(
            f"/tasks/{mission_uuid}/cancel/{action}/", data=payload
        )
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 404:
            return _error_response(f"Mission not found: {mission_uuid}")
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", f"Cannot {action} cancellation in current state")
            )
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        elif result["status_code"] == 403:
            return _error_response(
                result["data"].get("detail", f"Not authorized to {action} this cancellation")
            )
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def submit_feedback(
    report_type: str,
    title: str,
    description: str,
    platform: str = "mcp",
) -> str:
    """
    Submit a bug report, feedback, or feature request.

    Args:
        report_type: Type of report — 'bug', 'feedback', or 'feature_request'
        title: Short summary of the report
        description: Detailed description
        platform: Where the issue was encountered (defaults to 'mcp')

    Returns:
        JSON string with report details or error message
    """
    try:
        client = APIClient()
        payload = {
            "type": report_type,
            "title": title,
            "description": description,
            "platform": platform,
        }

        response = await client.post("/feedback/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] == 201:
            return json.dumps(result["data"])
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        elif result["status_code"] == 400:
            return _error_response(
                f"Validation error: {result['data']}"
            )
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def get_categories() -> str:
    """
    Get list of available mission categories.

    Categories endpoint is public (no authentication required).

    Returns:
        JSON string with list of categories, each containing value, label, and color
    """
    try:
        client = APIClient()
        response = await client.get("/tasks/categories/", use_auth=False)
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")
