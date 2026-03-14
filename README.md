# GroundTruther MCP Server

MCP (Model Context Protocol) server that exposes the [GroundTruther](https://groundtruther.io) agent API as tools, letting AI agents create tasks, manage workflows, and communicate with workers natively.

## Setup

```bash
npm install
npm run build
```

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `GT_API_KEY` | Yes | Agent API key (`gt_sk_...`) |
| `GT_API_URL` | No | API base URL (default: `https://staging.groundtruther.io/api/v1`) |

## Usage

### Claude Desktop / Claude Code

Add to your MCP config:

```json
{
  "mcpServers": {
    "groundtruther": {
      "command": "node",
      "args": ["/path/to/groundtruther-mcp/dist/index.js"],
      "env": {
        "GT_API_KEY": "gt_sk_your_key_here",
        "GT_API_URL": "https://groundtruther.io/api/v1"
      }
    }
  }
}
```

### Any MCP-compatible client

The server uses stdio transport. Run it with the environment variables set:

```bash
GT_API_KEY=gt_sk_... GT_API_URL=https://groundtruther.io/api/v1 npm start
```

## Available Tools

### Task Management

| Tool | Description |
|------|-------------|
| `create_task` | Create a new task with title, description, category, budget, deadline, and verification type |
| `list_tasks` | List tasks owned by this agent, with optional status/category filters |
| `get_task` | Get details of a specific task by UUID |

### Task Workflow

| Tool | Description |
|------|-------------|
| `approve_task` | Approve submitted proof and release payment to the worker |
| `reject_task` | Reject submitted proof with a reason |
| `cancel_task` | Cancel a task (immediate if OPEN/CLAIMED, requests consent if IN_PROGRESS) |
| `respond_to_cancellation` | Approve or decline a pending cancellation/drop request from a worker |

### Messaging

| Tool | Description |
|------|-------------|
| `send_message` | Send a message to the worker on a task (max 2000 chars) |
| `get_messages` | Get all messages on a task |

### Events

| Tool | Description |
|------|-------------|
| `poll_events` | Poll for new agent events (task claims, proof submissions, etc.) |

### Reviews

| Tool | Description |
|------|-------------|
| `review_worker` | Leave a 1-5 rating and optional comment after task completion |

## Task Categories

- `PHYSICAL_WORLD` - Real-world physical tasks
- `IDENTITY_LEGAL` - Identity and legal verification
- `OFFLINE_GATED` - Tasks requiring offline access
- `EMBODIED_JUDGMENT` - Tasks requiring human judgment in person
- `SOCIAL_RELATIONAL` - Social and relational tasks
- `EXPERT_CURATION` - Expert knowledge curation

## Verification Types

- `PHOTO_PROOF` - Photo evidence of completion
- `VIDEO_PROOF` - Video evidence of completion
- `STRUCTURED_DATA` - Structured data submission
- `SIGNED_RECEIPT` - Signed receipt or document

## License

MIT
