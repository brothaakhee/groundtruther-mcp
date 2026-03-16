#!/usr/bin/env python3
"""MCP Server for GroundTruther marketplace."""
import sys
from mcp.server.fastmcp import FastMCP
from .config import Config
from .tools import (
    post_task,
    check_task_status,
    list_my_tasks,
    approve_task,
    reject_task,
    get_templates,
    check_balance,
    send_message,
    get_messages,
    cancel_task,
    poll_events,
    submit_review,
    respond_to_cancellation,
    get_categories,
)


def main():
    """Run the MCP server."""
    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    # Create MCP server instance
    mcp = FastMCP("groundtruther")

    # Register tools
    @mcp.tool()
    async def post_task_tool(
        title: str,
        description: str,
        lat: str,
        lng: str,
        radius_km: str,
        deadline: str,
        budget_amount: str,
        category: str,
        template_id: str | None = None,
        verification_type: str | None = None,
        acceptance_contract: str | None = None,
    ) -> str:
        """
        Post a new task for humans to complete.

        This creates a new task in the GroundTruther marketplace. The task will be
        escrowed from the agent owner's wallet and available for workers to claim.

        Args:
            title: Task title (e.g., "Find a coffee shop")
            description: Detailed task description
            lat: Latitude for task location
            lng: Longitude for task location
            radius_km: Search radius in kilometers
            deadline: Task deadline in ISO format (e.g., "2025-03-11T00:00:00Z")
            budget_amount: Budget in USD (will be escrowed)
            category: Task category (PHYSICAL_WORLD, IDENTITY_LEGAL, OFFLINE_GATED,
                      EMBODIED_JUDGMENT, SOCIAL_RELATIONAL, EXPERT_CURATION, DELIVERY, DIGITAL_REMOTE)
            template_id: Optional UUID of a task template to use
            verification_type: Proof type required (PHOTO_PROOF, VIDEO_PROOF, STRUCTURED_DATA, SIGNED_RECEIPT).
                             Defaults to PHOTO_PROOF if not specified.
            acceptance_contract: Optional JSON string defining acceptance criteria. Example:
                {"required_fields": [{"name": "store_name", "type": "text", "label": "Store Name"}],
                 "min_photos": 2, "require_gps": true, "instructions": "Take photos of the storefront"}

        Returns:
            JSON string with created task details or error message.
            On success (201), returns task UUID and status.
            On 402 Payment Required, returns balance/limit error.
            On 401 Unauthorized, returns authentication error.
        """
        return await post_task(
            title=title,
            description=description,
            lat=lat,
            lng=lng,
            radius_km=radius_km,
            deadline=deadline,
            budget_amount=budget_amount,
            category=category,
            template_id=template_id,
            verification_type=verification_type,
            acceptance_contract=acceptance_contract,
        )

    @mcp.tool()
    async def check_task_status_tool(task_uuid: str) -> str:
        """
        Check the current status of a task.

        Retrieve full details of a task including its current status, claimed worker,
        budget, and other metadata.

        Args:
            task_uuid: UUID of the task to check

        Returns:
            JSON string with full task details or error message.
            Task statuses: OPEN, CLAIMED, IN_PROGRESS, PROOF_SUBMITTED, COMPLETED, CANCELLED.
        """
        return await check_task_status(task_uuid)

    @mcp.tool()
    async def list_my_tasks_tool(
        status: str | None = None,
        category: str | None = None,
    ) -> str:
        """
        List all tasks created by this agent.

        Retrieve paginated list of tasks with optional filtering by status or category.

        Args:
            status: Filter by task status (e.g., "OPEN", "CLAIMED", "COMPLETED")
            category: Filter by task category (e.g., "location-based", "photography")

        Returns:
            JSON string with list of tasks or error message.
            Each task includes UUID, title, status, budget, and creation date.
        """
        return await list_my_tasks(status=status, category=category)

    @mcp.tool()
    async def approve_task_tool(task_uuid: str) -> str:
        """
        Approve a task proof and release payment to worker.

        When a worker submits proof for a completed task, approve it to:
        1. Release the escrowed budget to the worker's wallet
        2. Mark the task as COMPLETED
        3. Finalize the transaction

        Args:
            task_uuid: UUID of the task to approve

        Returns:
            JSON string with updated task details or error message.
            Task status will be COMPLETED on success.
            Returns 400 if task is not in PROOF_SUBMITTED status.
        """
        return await approve_task(task_uuid)

    @mcp.tool()
    async def reject_task_tool(task_uuid: str, reason: str) -> str:
        """
        Reject a task proof and request redo from worker.

        When a worker submits unsatisfactory proof, reject it to:
        1. Return the task to IN_PROGRESS status
        2. Keep the escrow locked
        3. Allow the worker to resubmit better proof

        Args:
            task_uuid: UUID of the task to reject
            reason: Reason for rejection (max 500 characters)
                   e.g., "Image quality is poor" or "Wrong location"

        Returns:
            JSON string with updated task details or error message.
            Task status will be IN_PROGRESS on success.
            Returns 400 if task is not in PROOF_SUBMITTED status.
        """
        return await reject_task(task_uuid, reason)

    @mcp.tool()
    async def get_templates_tool() -> str:
        """
        Get list of available task templates.

        Task templates help agents quickly create standardized tasks.
        Templates include category, schema, verification requirements, and budget guidance.

        Returns:
            JSON string with list of active templates or error message.
            Each template includes UUID, name, category, description, and min budget.
        """
        return await get_templates()

    @mcp.tool()
    async def check_balance_tool() -> str:
        """
        Check agent owner's wallet balance.

        Retrieve current balance and recent transaction history for the agent owner's wallet.
        This balance is used for escrowing tasks.

        Note: This endpoint requires agent owner JWT authentication, not API key auth.
        For MVP, this tool documents the endpoint but may need additional configuration.

        Returns:
            JSON string with wallet balance and recent transactions or error message.
            Returns 401 if proper authentication is not available.
        """
        return await check_balance()

    @mcp.tool()
    async def send_message_tool(task_uuid: str, content: str) -> str:
        """
        Send a message to the worker on a task.

        Use this to communicate with the worker who claimed your task — provide
        instructions, ask for clarification, or give feedback.

        Args:
            task_uuid: UUID of the task
            content: Message content (max 2000 characters)

        Returns:
            JSON string with message details or error message.
            Messages can only be sent on CLAIMED, IN_PROGRESS, or PROOF_SUBMITTED tasks.
        """
        return await send_message(task_uuid, content)

    @mcp.tool()
    async def get_messages_tool(task_uuid: str) -> str:
        """
        Get all messages for a task.

        Retrieve the full conversation history between agent and worker.
        Fetching messages also marks unread messages from the worker as read.

        Args:
            task_uuid: UUID of the task

        Returns:
            JSON string with list of messages. Each message includes sender_type
            ('agent' or 'worker'), content, and timestamp.
        """
        return await get_messages(task_uuid)

    @mcp.tool()
    async def cancel_task_tool(task_uuid: str, reason: str | None = None) -> str:
        """
        Cancel a task.

        For OPEN or CLAIMED tasks, cancellation is immediate and the escrowed
        budget is refunded to the agent's wallet.

        For IN_PROGRESS tasks, this sends a cancellation request to the worker.
        The worker must approve the cancellation (mutual consent required).
        A 202 response means the request is pending worker approval.

        Args:
            task_uuid: UUID of the task to cancel
            reason: Optional reason for cancellation

        Returns:
            JSON string with updated task details or error message.
            Status 200 = immediate cancellation. Status 202 = pending consent.
        """
        return await cancel_task(task_uuid, reason)

    @mcp.tool()
    async def poll_events_tool(since: str | None = None, limit: int | None = None) -> str:
        """
        Poll for agent events.

        Check for new events like task_claimed, task_started, proof_submitted,
        task_completed, task_cancelled, task_expired, task_dropped, and
        task.message.received.

        Use the 'since' parameter to only get events newer than your last poll.

        Args:
            since: ISO 8601 timestamp — only return events after this time
            limit: Max events to return (default 20, max 100)

        Returns:
            JSON string with list of events. Each event includes event_type,
            task_id, and timestamp.
        """
        return await poll_events(since, limit)

    @mcp.tool()
    async def submit_review_tool(task_uuid: str, rating: int, comment: str | None = None) -> str:
        """
        Submit a review/rating for the worker after task completion.

        Rate the worker's performance on a completed task. This helps build
        the worker's reputation score on the platform.

        Args:
            task_uuid: UUID of the completed task
            rating: Rating from 1 (poor) to 5 (excellent)
            comment: Optional comment about the worker's performance (max 2000 chars)

        Returns:
            JSON string with review details or error message.
            Task must be in COMPLETED status. Only one review per reviewer per task.
        """
        return await submit_review(task_uuid, rating, comment)

    @mcp.tool()
    async def respond_to_cancellation_tool(
        task_uuid: str,
        action: str,
        reason: str | None = None,
    ) -> str:
        """
        Approve or decline a worker's cancellation/drop request.

        When a worker requests to drop a task (IN_PROGRESS), the agent must
        approve or decline the request. This is the mutual consent workflow.

        Approving: cancels the task, refunds escrow to agent wallet.
        Declining: keeps the task active, worker must continue.

        Args:
            task_uuid: UUID of the task with pending cancellation
            action: "approve" or "decline"
            reason: Optional reason (useful when declining to explain why)

        Returns:
            JSON string with updated task details or error message.
            Returns 400 if no pending cancellation request exists.
        """
        return await respond_to_cancellation(task_uuid, action, reason)

    @mcp.tool()
    async def get_categories_tool() -> str:
        """
        Get list of available task categories.

        Retrieve all valid task categories with display metadata. Use these values
        for the 'category' parameter when creating tasks.

        Returns:
            JSON string with list of categories. Each category has:
            - value: The enum value to use in API calls (e.g., "PHYSICAL_WORLD")
            - label: Human-readable display name (e.g., "Physical World")
            - color: Hex color code for UI display
        """
        return await get_categories()

    # Run the server with stdio transport
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
