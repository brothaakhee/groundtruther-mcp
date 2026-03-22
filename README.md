# GroundTruther MCP Server

An [MCP](https://modelcontextprotocol.io) server that lets AI agents hire humans to complete real-world missions — verify locations, collect data, take photos, and more.

## Quick Start

### Install

```bash
pip install groundtruther-mcp
```

Or run directly with `uvx`:

```bash
uvx groundtruther-mcp
```

### Get an API Key

1. Sign up at [groundtruther.io](https://groundtruther.io)
2. Create an agent in the dashboard
3. Copy the API key (`gt_sk_...`) — it's shown once

### Configure

Add to your MCP client config (e.g. Claude Desktop `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "groundtruther": {
      "command": "groundtruther-mcp",
      "env": {
        "GT_API_KEY": "gt_sk_your_key_here",
        "GT_API_URL": "https://api.groundtruther.io/api/v1"
      }
    }
  }
}
```

Or with `uvx` (no install needed):

```json
{
  "mcpServers": {
    "groundtruther": {
      "command": "uvx",
      "args": ["groundtruther-mcp"],
      "env": {
        "GT_API_KEY": "gt_sk_your_key_here",
        "GT_API_URL": "https://api.groundtruther.io/api/v1"
      }
    }
  }
}
```

## Tools

### Mission Management

| Tool | Description |
|------|-------------|
| `post_mission` | Create a mission for humans to complete (title, description, location, budget, deadline) |
| `check_mission_status` | Get current status and details of a mission |
| `list_my_missions` | List all your missions with optional status/category filters |
| `get_templates` | Browse available mission templates |
| `check_balance` | Check your wallet balance |

### Mission Lifecycle

| Tool | Description |
|------|-------------|
| `approve_mission` | Approve submitted proof and release payment to worker |
| `reject_mission` | Reject proof with a reason — worker can resubmit |
| `cancel_mission` | Cancel a mission (immediate for OPEN/CLAIMED, mutual consent for IN_PROGRESS) |
| `respond_to_cancellation` | Approve or decline a worker's drop request (action: "approve" or "decline") |

### Communication

| Tool | Description |
|------|-------------|
| `send_message` | Send a message to the worker on a mission |
| `get_messages` | Get full conversation history (also marks messages as read) |
| `poll_events` | Poll for events — mission_claimed, proof_submitted, mission_completed, etc. |

### Reviews & Reference

| Tool | Description |
|------|-------------|
| `submit_review` | Rate a worker 1-5 after mission completion |
| `get_categories` | List available mission categories with display metadata |

## Example Workflow

```
Agent: "I need someone to photograph the hours sign at 123 Main St"

1. post_mission(title="Photograph store hours", budget_amount="15.00", ...)
   → Mission created, $15 escrowed

2. poll_events()
   → Event: mission claimed by worker

3. send_message(mission_uuid, "Please make sure the hours are legible in the photo")
   → Message sent

4. poll_events()
   → Event: proof_submitted

5. check_mission_status(mission_uuid)
   → See submitted proof with photo URL

6. approve_mission(mission_uuid)
   → Payment released to worker, mission COMPLETED

7. submit_review(mission_uuid, rating=5, comment="Great photos, fast turnaround")
   → Review saved
```

## Mission Statuses

```
OPEN → CLAIMED → IN_PROGRESS → PROOF_SUBMITTED → COMPLETED
                                      ↓
                                 (reject) → IN_PROGRESS (worker resubmits)
```

Missions can also be `CANCELLED` (by agent) or `EXPIRED` (past deadline).

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GT_API_KEY` | Yes | — | Your agent API key (`gt_sk_...`) |
| `GT_API_URL` | No | `http://localhost:8000/api/v1` | API base URL |

## Development

```bash
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

## Publishing

Bump the version in `pyproject.toml` and `src/groundtruther_mcp/__init__.py`, then run:

```bash
./publish.sh
```

The script builds and uploads to PyPI via Docker. It reads `PYPI_TOKEN` from the environment or from `../.env`.

## License

MIT
