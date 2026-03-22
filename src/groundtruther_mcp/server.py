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
    submit_feedback,
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
    mcp = FastMCP("groundtruther", description="Hire humans to complete real-world missions — verify locations, collect data, take photos, and more.")

    # Register tools
    @mcp.tool()
    async def post_task_tool(
        title: str,
        description: str,
        lat: float,
        lng: float,
        radius_km: float,
        deadline: str,
        budget_amount: float,
        category: str,
        template_id: str | None = None,
        verification_type: str | None = None,
        acceptance_contract: str | None = None,
    ) -> str:
        """
        Post a new mission for humans to complete.

        This creates a new mission in the GroundTruther marketplace. The mission will be
        escrowed from the agent owner's wallet and available for workers to claim.

        Args:
            title: Mission title (e.g., "Find a coffee shop")
            description: Detailed mission description
            lat: Latitude for mission location (e.g., 37.7749)
            lng: Longitude for mission location (e.g., -122.4194)
            radius_km: Search radius in kilometers (e.g., 5.0)
            deadline: Mission deadline in ISO format (e.g., "2025-03-11T00:00:00Z")
            budget_amount: Budget in USD (e.g., 25.00, will be escrowed)
            category: Mission category (PHYSICAL_WORLD, IDENTITY_LEGAL, OFFLINE_GATED,
                      EMBODIED_JUDGMENT, SOCIAL_RELATIONAL, EXPERT_CURATION, DELIVERY, DIGITAL_REMOTE)
            template_id: Optional UUID of a mission template to use
            verification_type: Proof type required (PHOTO_PROOF, VIDEO_PROOF, STRUCTURED_DATA, SIGNED_RECEIPT).
                             Defaults to PHOTO_PROOF if not specified.
            acceptance_contract: Optional JSON string defining acceptance criteria. Example:
                {"required_fields": [{"name": "store_name", "type": "text", "label": "Store Name"}],
                 "min_photos": 2, "require_gps": true, "instructions": "Take photos of the storefront"}

        Returns:
            JSON string with created mission details or error message.
            On success (201), returns mission UUID and status.
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
        Check the current status of a mission.

        Retrieve full details of a mission including its current status, claimed worker,
        budget, and other metadata.

        Args:
            task_uuid: Mission UUID to check

        Returns:
            JSON string with full mission details or error message.
            Mission statuses: OPEN, CLAIMED, IN_PROGRESS, PROOF_SUBMITTED, COMPLETED, CANCELLED.
        """
        return await check_task_status(task_uuid)

    @mcp.tool()
    async def list_my_tasks_tool(
        status: str | None = None,
        category: str | None = None,
    ) -> str:
        """
        List all missions created by this agent.

        Retrieve paginated list of missions with optional filtering by status or category.

        Args:
            status: Filter by mission status (e.g., "OPEN", "CLAIMED", "COMPLETED")
            category: Filter by mission category (e.g., "location-based", "photography")

        Returns:
            JSON string with list of missions or error message.
            Each mission includes UUID, title, status, budget, and creation date.
        """
        return await list_my_tasks(status=status, category=category)

    @mcp.tool()
    async def approve_task_tool(task_uuid: str) -> str:
        """
        Approve a mission proof and release payment to worker.

        When a worker submits proof for a completed mission, approve it to:
        1. Release the escrowed budget to the worker's wallet
        2. Mark the mission as COMPLETED
        3. Finalize the transaction

        Args:
            task_uuid: Mission UUID to approve

        Returns:
            JSON string with updated mission details or error message.
            Mission status will be COMPLETED on success.
            Returns 400 if mission is not in PROOF_SUBMITTED status.
        """
        return await approve_task(task_uuid)

    @mcp.tool()
    async def reject_task_tool(task_uuid: str, reason: str) -> str:
        """
        Reject a mission proof and request redo from worker.

        When a worker submits unsatisfactory proof, reject it to:
        1. Return the mission to IN_PROGRESS status
        2. Keep the escrow locked
        3. Allow the worker to resubmit better proof

        Args:
            task_uuid: Mission UUID to reject
            reason: Reason for rejection (max 500 characters)
                   e.g., "Image quality is poor" or "Wrong location"

        Returns:
            JSON string with updated mission details or error message.
            Mission status will be IN_PROGRESS on success.
            Returns 400 if mission is not in PROOF_SUBMITTED status.
        """
        return await reject_task(task_uuid, reason)

    @mcp.tool()
    async def get_templates_tool() -> str:
        """
        Get list of available mission templates.

        Mission templates help agents quickly create standardized missions.
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
        This balance is used for escrowing missions.

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
        Send a message to the worker on a mission.

        Use this to communicate with the worker who claimed your mission — provide
        instructions, ask for clarification, or give feedback.

        Args:
            task_uuid: Mission UUID
            content: Message content (max 2000 characters)

        Returns:
            JSON string with message details or error message.
            Messages can only be sent on CLAIMED, IN_PROGRESS, or PROOF_SUBMITTED missions.
        """
        return await send_message(task_uuid, content)

    @mcp.tool()
    async def get_messages_tool(task_uuid: str) -> str:
        """
        Get all messages for a mission.

        Retrieve the full conversation history between agent and worker.
        Fetching messages also marks unread messages from the worker as read.

        Args:
            task_uuid: Mission UUID

        Returns:
            JSON string with list of messages. Each message includes sender_type
            ('agent' or 'worker'), content, and timestamp.
        """
        return await get_messages(task_uuid)

    @mcp.tool()
    async def cancel_task_tool(task_uuid: str, reason: str | None = None) -> str:
        """
        Cancel a mission.

        For OPEN or CLAIMED missions, cancellation is immediate and the escrowed
        budget is refunded to the agent's wallet.

        For IN_PROGRESS missions, this sends a cancellation request to the worker.
        The worker must approve the cancellation (mutual consent required).
        A 202 response means the request is pending worker approval.

        Args:
            task_uuid: Mission UUID to cancel
            reason: Optional reason for cancellation

        Returns:
            JSON string with updated mission details or error message.
            Status 200 = immediate cancellation. Status 202 = pending consent.
        """
        return await cancel_task(task_uuid, reason)

    @mcp.tool()
    async def poll_events_tool(since: str | None = None, limit: int | None = None) -> str:
        """
        Poll for agent events.

        Check for new events like mission_claimed, mission_started, proof_submitted,
        mission_completed, mission_cancelled, mission_expired, mission_dropped, and
        mission.message.received.

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
        Submit a review/rating for the worker after mission completion.

        Rate the worker's performance on a completed mission. This helps build
        the worker's reputation score on the platform.

        Args:
            task_uuid: UUID of the completed mission
            rating: Rating from 1 (poor) to 5 (excellent)
            comment: Optional comment about the worker's performance (max 2000 chars)

        Returns:
            JSON string with review details or error message.
            Mission must be in COMPLETED status. Only one review per reviewer per mission.
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

        When a worker requests to drop a mission (IN_PROGRESS), the agent must
        approve or decline the request. This is the mutual consent workflow.

        Approving: cancels the mission, refunds escrow to agent wallet.
        Declining: keeps the mission active, worker must continue.

        Args:
            task_uuid: UUID of the mission with pending cancellation
            action: "approve" or "decline"
            reason: Optional reason (useful when declining to explain why)

        Returns:
            JSON string with updated mission details or error message.
            Returns 400 if no pending cancellation request exists.
        """
        return await respond_to_cancellation(task_uuid, action, reason)

    @mcp.tool()
    async def get_categories_tool() -> str:
        """
        Get list of available mission categories.

        Retrieve all valid mission categories with display metadata. Use these values
        for the 'category' parameter when creating missions.

        Returns:
            JSON string with list of categories. Each category has:
            - value: The enum value to use in API calls (e.g., "PHYSICAL_WORLD")
            - label: Human-readable display name (e.g., "Physical World")
            - color: Hex color code for UI display
        """
        return await get_categories()

    @mcp.tool()
    async def submit_feedback_tool(
        report_type: str,
        title: str,
        description: str,
    ) -> str:
        """
        Submit a bug report, feedback, or feature request to the GroundTruther team.

        Use this to report issues, suggest improvements, or request new features.

        Args:
            report_type: Type of report — "bug", "feedback", or "feature_request"
            title: Short summary (e.g., "Mission creation fails for DELIVERY category")
            description: Detailed description of the issue or suggestion

        Returns:
            JSON string with confirmation and report ID, or error message.
        """
        return await submit_feedback(
            report_type=report_type,
            title=title,
            description=description,
            platform="mcp",
        )

    # Run the server with stdio transport
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
