"""MCP tool implementations for GroundTruther."""
import json
from datetime import datetime
from typing import Optional, Dict, Any
import httpx
from .client import APIClient


def _error_response(message: str) -> str:
    """Create an error response JSON string."""
    return json.dumps({"error": message})


async def post_task(
    title: str,
    description: str,
    lat: str,
    lng: str,
    radius_km: str,
    deadline: str,
    budget_amount: str,
    category: str,
    template_id: Optional[str] = None,
    verification_type: Optional[str] = None,
    acceptance_contract: Optional[str] = None,
) -> str:
    """
    Create a new task.

    Args:
        title: Task title
        description: Task description
        lat: Latitude for task location
        lng: Longitude for task location
        radius_km: Search radius in kilometers
        deadline: Task deadline (ISO format)
        budget_amount: Budget in USD
        category: Task category (PHYSICAL_WORLD, IDENTITY_LEGAL, OFFLINE_GATED,
                  EMBODIED_JUDGMENT, SOCIAL_RELATIONAL, EXPERT_CURATION, DELIVERY, DIGITAL_REMOTE)
        template_id: Optional task template UUID
        verification_type: Proof type required (PHOTO_PROOF, VIDEO_PROOF, STRUCTURED_DATA, SIGNED_RECEIPT)
        acceptance_contract: JSON string defining acceptance criteria (required fields, min photos, GPS requirement)

    Returns:
        JSON string with task details or error
    """
    try:
        client = APIClient()

        # Build request payload
        payload = {
            "title": title,
            "description": description,
            "latitude": lat,
            "longitude": lng,
            "radius_km": radius_km,
            "deadline": deadline,
            "budget_amount": budget_amount,
            "category": category,
        }

        if template_id:
            payload["template"] = template_id
        if verification_type:
            payload["verification_type"] = verification_type
        if acceptance_contract:
            try:
                payload["acceptance_contract"] = json.loads(acceptance_contract)
            except json.JSONDecodeError:
                return _error_response("acceptance_contract must be valid JSON")

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


async def check_task_status(task_uuid: str) -> str:
    """
    Get task details and current status.

    Args:
        task_uuid: Task UUID

    Returns:
        JSON string with task details or error
    """
    try:
        client = APIClient()

        # Make API call
        response = await client.get(f"/tasks/{task_uuid}/")
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 404:
            return _error_response(f"Task not found: {task_uuid}")
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


async def list_my_tasks(
    status: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """
    List agent's tasks with optional filtering.

    Args:
        status: Filter by status (e.g., 'OPEN', 'CLAIMED', 'COMPLETED')
        category: Filter by category (e.g., 'location-based')

    Returns:
        JSON string with list of tasks or error
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


async def approve_task(task_uuid: str) -> str:
    """
    Approve a task proof and release payment.

    Args:
        task_uuid: Task UUID

    Returns:
        JSON string with updated task details or error
    """
    try:
        client = APIClient()

        # Make API call (POST with no body)
        response = await client.post(f"/tasks/{task_uuid}/approve/", data={})
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 404:
            return _error_response(f"Task not found: {task_uuid}")
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot approve task in current state")
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


async def reject_task(task_uuid: str, reason: str) -> str:
    """
    Reject a task proof and return task to IN_PROGRESS.

    Args:
        task_uuid: Task UUID
        reason: Reason for rejection (max 500 chars)

    Returns:
        JSON string with updated task details or error
    """
    try:
        client = APIClient()

        # Build request payload
        payload = {"reason": reason}

        # Make API call
        response = await client.post(
            f"/tasks/{task_uuid}/reject/", data=payload
        )
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 404:
            return _error_response(f"Task not found: {task_uuid}")
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot reject task in current state")
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
    Get list of available task templates.

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
    The API key authentication is typically used for task operations.
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


async def send_message(task_uuid: str, content: str) -> str:
    """
    Send a message to the worker on a task.

    Args:
        task_uuid: Task UUID
        content: Message content (max 2000 chars)

    Returns:
        JSON string with message details or error
    """
    try:
        client = APIClient()
        payload = {"content": content, "attachments": []}
        response = await client.post(f"/tasks/{task_uuid}/messages/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] == 201:
            return json.dumps(result["data"])
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot send message on this task")
            )
        elif result["status_code"] == 404:
            return _error_response(f"Task not found: {task_uuid}")
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        elif result["status_code"] == 403:
            return _error_response("Forbidden: Not authorized to message on this task")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def get_messages(task_uuid: str) -> str:
    """
    Get all messages for a task.

    Fetching messages also marks unread messages from the other party as read.

    Args:
        task_uuid: Task UUID

    Returns:
        JSON string with list of messages or error
    """
    try:
        client = APIClient()
        response = await client.get(f"/tasks/{task_uuid}/messages/")
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot view messages on this task")
            )
        elif result["status_code"] == 404:
            return _error_response(f"Task not found: {task_uuid}")
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


async def cancel_task(task_uuid: str, reason: Optional[str] = None) -> str:
    """
    Cancel a task.

    For OPEN or CLAIMED tasks, cancellation is immediate and escrow is refunded.
    For IN_PROGRESS tasks, this requests mutual cancellation from the worker
    (returns 202 Accepted while waiting for worker consent).

    Args:
        task_uuid: Task UUID
        reason: Optional reason for cancellation

    Returns:
        JSON string with updated task details or error
    """
    try:
        client = APIClient()
        payload = {}
        if reason:
            payload["reason"] = reason

        response = await client.post(f"/tasks/{task_uuid}/cancel/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] in (200, 202):
            data = result["data"]
            if result["status_code"] == 202:
                data["_note"] = "Cancellation requested. Waiting for worker consent."
            return json.dumps(data)
        elif result["status_code"] == 404:
            return _error_response(f"Task not found: {task_uuid}")
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot cancel task in current state")
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
    Poll for agent events (task claimed, proof submitted, task completed, etc.).

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


async def submit_review(task_uuid: str, rating: int, comment: Optional[str] = None) -> str:
    """
    Submit a review/rating for the worker after task completion.

    Args:
        task_uuid: Task UUID (must be COMPLETED)
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
        response = await client.post(f"/tasks/{task_uuid}/review/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] == 201:
            return json.dumps(result["data"])
        elif result["status_code"] == 400:
            return _error_response(
                result["data"].get("detail", "Cannot submit review")
            )
        elif result["status_code"] == 404:
            return _error_response(f"Task not found: {task_uuid}")
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        elif result["status_code"] == 403:
            return _error_response("Forbidden: Not authorized to review this task")
        else:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")


async def respond_to_cancellation(task_uuid: str, action: str, reason: Optional[str] = None) -> str:
    """
    Approve or decline a worker's cancellation/drop request.

    When a worker requests to drop a task, the agent must approve or decline.
    Approving cancels the task and refunds escrow. Declining keeps the task active.

    Args:
        task_uuid: Task UUID
        action: 'approve' or 'decline'
        reason: Optional reason (used when declining)

    Returns:
        JSON string with updated task details or error
    """
    if action not in ("approve", "decline"):
        return _error_response("Action must be 'approve' or 'decline'")

    try:
        client = APIClient()
        payload = {}
        if reason:
            payload["reason"] = reason

        response = await client.post(
            f"/tasks/{task_uuid}/cancel/{action}/", data=payload
        )
        result = APIClient.handle_response(response)

        if result["status_code"] == 200:
            return json.dumps(result["data"])
        elif result["status_code"] == 404:
            return _error_response(f"Task not found: {task_uuid}")
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


async def get_categories() -> str:
    """
    Get list of available task categories.

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
