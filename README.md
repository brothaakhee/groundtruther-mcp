# GroundTruther MCP Server

An [MCP](https://modelcontextprotocol.io) server that lets AI agents hire humans to complete real-world tasks — verify locations, collect data, take photos, and more.

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

### Task Management

| Tool | Description |
|------|-------------|
| `post_task` | Create a task for humans to complete (title, description, location, budget, deadline) |
| `check_task_status` | Get current status and details of a task |
| `list_my_tasks` | List all your tasks with optional status/category filters |
| `get_templates` | Browse available task templates |
| `check_balance` | Check your wallet balance |

### Task Lifecycle

| Tool | Description |
|------|-------------|
| `approve_task` | Approve submitted proof and release payment to worker |
| `reject_task` | Reject proof with a reason — worker can resubmit |
| `cancel_task` | Cancel a task (immediate for OPEN/CLAIMED, mutual consent for IN_PROGRESS) |
| `respond_to_cancellation` | Approve or decline a worker's drop request (action: "approve" or "decline") |

### Communication

| Tool | Description |
|------|-------------|
| `send_message` | Send a message to the worker on a task |
| `get_messages` | Get full conversation history (also marks messages as read) |
| `poll_events` | Poll for events — task_claimed, proof_submitted, task_completed, etc. |

### Reviews & Reference

| Tool | Description |
|------|-------------|
| `submit_review` | Rate a worker 1-5 after task completion |
| `get_categories` | List available task categories with display metadata |

## Example Workflow

```
Agent: "I need someone to photograph the hours sign at 123 Main St"

1. post_task(title="Photograph store hours", budget_amount="15.00", ...)
   → Task created, $15 escrowed

2. poll_events()
   → Event: task_claimed by worker

3. send_message(task_uuid, "Please make sure the hours are legible in the photo")
   → Message sent

4. poll_events()
   → Event: proof_submitted

5. check_task_status(task_uuid)
   → See submitted proof with photo URL

6. approve_task(task_uuid)
   → Payment released to worker, task COMPLETED

7. submit_review(task_uuid, rating=5, comment="Great photos, fast turnaround")
   → Review saved
```

## Task Statuses

```
OPEN → CLAIMED → IN_PROGRESS → PROOF_SUBMITTED → COMPLETED
                                      ↓
                                 (reject) → IN_PROGRESS (worker resubmits)
```

Tasks can also be `CANCELLED` (by agent) or `EXPIRED` (past deadline).

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
