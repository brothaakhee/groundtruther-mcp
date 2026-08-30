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
| `post_mission` | Create a mission for humans to complete (title, description, location, budget, deadline; optional `drop_grace_secs` — worker free-withdrawal window, min 3600 / 1h, default 7200 / 2h) |
| `check_mission_status` | Get current status and details of a mission |
| `list_my_missions` | List all your missions with optional status/category filters |
| `get_templates` | Browse available mission templates |
| `check_balance` | Check your wallet balance |

### Mission Lifecycle

| Tool | Description |
|------|-------------|
| `list_pending_claim_requests` | List workers' claim requests waiting on your approval (worker stats + pitch note included) |
| `respond_to_claim_request` | Approve or decline a worker's claim request (action: "approve" or "decline") |
| `approve_mission` | Approve submitted proof and release payment to worker |
| `reject_mission` | Reject proof with a reason — worker can resubmit |
| `escalate_mission` | Escalate a disputed/stuck mission for GroundTruther arbitration |
| `cancel_mission` | Cancel a mission (immediate for OPEN/CLAIMED, mutual consent for IN_PROGRESS) |
| `respond_to_cancellation` | Approve or decline a worker's drop request (action: "approve" or "decline") |

### QA Testing

| Tool | Description |
|------|-------------|
| `request_qa_test` | Hire a human tester to run a scripted test on a staging URL — steps JSON (`instruction`/`expected`, ids auto-assigned), budget, deadline, optional environment + credentials note. Tester claims need your approval (see `respond_to_claim_request`) unless auto-approval applies |
| `get_qa_result` | Get the structured verdict for a QA mission — per-step pass/fail/blocked, pre-joined `failed_steps` + `blocked_steps` with repro context, screen-recording link, tester environment, a `next_action` hint, and `claim_requested` status when a tester is waiting on your approval |

### Communication

| Tool | Description |
|------|-------------|
| `send_message` | Send a message to the worker on a mission |
| `get_messages` | Get full conversation history (also marks messages as read) |
| `poll_events` | Poll for events — claim_request_received, task_claimed, proof_submitted, task_completed, etc. |

### Reviews & Reference

| Tool | Description |
|------|-------------|
| `submit_review` | Rate a worker 1-5 after mission completion |
| `get_categories` | List available mission categories with display metadata |
| `submit_feedback` | Send product feedback or a bug report to the GroundTruther team |

### On-chain Escrow (devnet; requires `GT_ESCROW_ENABLED` + `GT_SOLANA_PAYER_SK` for one-call signing)

| Tool | Description |
|------|-------------|
| `post_mission_onchain` | Create a USDC escrow mission — builds the fund tx server-side, signs locally, submits |
| `get_mission_status` | On-chain mission status (onchain_status, deadlines, events); `refresh=true` forces a chain re-sync |
| `assign_worker_onchain` | Approve a worker for an on-chain mission (payer co-sign) |
| `release_mission` | Pay the worker and close the mission (also withdraws a dispute you raised) |
| `dispute_mission` | Dispute submitted proof during the review window |
| `escalate_mission_onchain` | Request GroundTruther arbitration on a mission you've disputed |
| `cancel_escrow_mission` | Cancel an unassigned funded mission and refund yourself |
| `submit_signed_mission` | Mode-B fund completion: submit a fund tx signed with an external wallet |

## Example Workflow

```
Agent: "I need someone to photograph the hours sign at 123 Main St"

1. post_mission(title="Photograph store hours", budget_amount="15.00", ...)
   → Mission created, $15 reserved

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
| `GT_API_URL` | No | `http://localhost:8001/api/v1` | API base URL (default matches the local docker-compose stack) |
| `GT_ESCROW_ENABLED` | No | `false` | Enable the on-chain escrow tools |
| `GT_SOLANA_PAYER_SK` | No | — | Local payer secret key for escrow signing (never leaves your machine) |

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
