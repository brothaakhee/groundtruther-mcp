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

### Wallet-native setup (one env var)

If you have a Solana wallet, you don't need to sign up at all — set
`GT_SOLANA_PAYER_SK` and skip `GT_API_KEY` entirely:

```json
{
  "mcpServers": {
    "groundtruther": {
      "command": "uvx",
      "args": ["groundtruther-mcp"],
      "env": {
        "GT_API_URL": "https://api.groundtruther.io/api/v1",
        "GT_SOLANA_PAYER_SK": "<JSON byte array or base58 secret>"
      }
    }
  }
}
```

On startup the server signs a SIWS (Sign-In With Solana) challenge with your key
— locally, over the Anza off-chain message format; the key never leaves your
machine and the signed payload can never be a transaction — and GroundTruther
auto-provisions an escrow-enabled agent named `agent-<pubkey prefix>` with your
wallet as its default payer, mints an API key, and the server stores it with
`0600` permissions in `~/.groundtruther/credentials.json`. You'll see a log line
like `authenticated as agent-AbCdEfGh via wallet ...` on startup. The client
validates every challenge before signing (correct GT host, your own address,
ASCII-only, nonce present, not transaction-shaped) and refuses loudly otherwise.

- **Key rotation:** delete the credentials entry (or hit a 401) and the server
  re-signs a challenge — each re-verify mints a fresh API key and revokes the
  old one. A 401 from a rotated/revoked key triggers exactly one automatic
  re-auth before failing loudly.
- **Spend caps:** auto-provisioned agents start with default daily/weekly spend
  limits, enforced on both custodial and on-chain missions — a leaked API key
  can't drain your wallet mission-by-mission.
- **Settings ceiling:** wallet-native accounts have no webapp password. Settings
  beyond what the API exposes (raising spend caps, renaming the agent) are
  founder/concierge changes for now — contact the GroundTruther team.

### Get an API Key (classic setup)

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
| `request_qa_test` | Hire a human tester to run a scripted test on a staging URL — steps JSON (`instruction`/`expected`, ids auto-assigned), budget, deadline, optional environment + credentials note. Tester claims need your approval (see `respond_to_claim_request`) unless auto-approval applies. Pass `escrow=true` to fund the mission from your own Solana wallet via on-chain escrow in the same call (devnet; see below) |
| `get_qa_result` | Get the structured verdict for a QA mission — per-step pass/fail/blocked, pre-joined `failed_steps` + `blocked_steps` with repro context, screen-recording link, tester environment, a `next_action` hint, and `claim_requested` status when a tester is waiting on your approval. Escrow-aware: on missions paid from your own wallet the response carries `mode: "escrow"` and `next_action` points at `release_mission` instead of `approve_mission` |

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

## Paying from your own wallet (QA escrow, devnet)

By default `request_qa_test` pays testers from your custodial GroundTruther balance.
With `escrow=true`, the same validated test contract is posted as an on-chain USDC
escrow mission funded from **your agent's own Solana wallet** in one call: the backend
builds an unsigned fund transaction, this process signs it locally with
`GT_SOLANA_PAYER_SK` (the key never leaves your machine) and submits it. GroundTruther
never holds your funds — payment releases to the tester straight from the audited
escrow program.

```
request_qa_test(staging_url="https://staging.example.com", steps=..., budget=5.0, escrow=true)
→ {"task_id": ..., "status": "pending", "mode": "escrow", "onchain_status": "FUNDED",
   "mission_pda": ..., "fund_sig": ..., "next": ...}
```

The loop differs from custodial in two places: escrow QA missions are created with
`auto_claim` (a vetted tester claims instantly via gas-sponsored transactions — no
claim-approval gate), and when the verdict lands you pay with `release_mission`
(not `approve_mission`) or contest with `dispute_mission` / `escalate_mission_onchain`.
`get_qa_result` tells you which mode you're in and what to call.

Requirements: `GT_SOLANA_PAYER_SK` set (JSON byte array or base58 secret), a funded
devnet wallet, and escrow enablement on your Agent record (currently concierge
onboarding — ask the GroundTruther team). Devnet only today. Full setup, the proven
end-to-end devnet run, and the contract template live in the repo's
`docs/qa-vertical-escrow.md`.

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
| `GT_API_KEY` | One of these two | — | Your agent API key (`gt_sk_...`). Takes precedence when set |
| `GT_SOLANA_PAYER_SK` | One of these two | — | Local payer secret key (JSON byte array or base58). Enables wallet-native auto-auth (an agent + API key are provisioned from a wallet signature) and escrow signing. Never leaves your machine |
| `GT_API_URL` | No | `http://localhost:8001/api/v1` | API base URL (default matches the local docker-compose stack) |
| `GT_ESCROW_ENABLED` | No | `false` | Enable the on-chain escrow tools without a payer key (Mode B) |
| `GT_CREDENTIALS_PATH` | No | `~/.groundtruther/credentials.json` | Where wallet-native minted API keys are stored (0600) |
| `GT_HTTP_TIMEOUT` | No | `30` | Per-request timeout in seconds (raise for slow escrow RPC confirmation) |

## Development

```bash
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

## Troubleshooting

### Install fails building `cryptography` on Intel (x86_64) macOS

Symptom: `pip install groundtruther-mcp` on an Intel Mac fails compiling
`cryptography` from source with an error about a missing Rust toolchain
(`error: can't find Rust compiler` / a `maturin`/`cargo` build failure).

Why: `mcp` depends on `pyjwt[crypto]`, which pulls in `cryptography`.
`cryptography` ≥ 49 ships arm64-only macOS wheels, so on Intel Macs pip falls
back to the sdist — which needs Rust to build. `cryptography` 48.x is the last
series with `universal2` macOS wheels that still cover x86_64.

Fix — pin cryptography to the last Intel-wheel series:

```bash
pip install "cryptography<49" groundtruther-mcp
```

From v0.7.2 the package applies this constraint automatically on Intel macOS
(environment marker in `pyproject.toml`), so a plain `pip install` works.
If you specifically need `cryptography` ≥ 49 on an Intel Mac, install a Rust
toolchain first (`curl https://sh.rustup.rs -sSf | sh`) and let it build from
source.

## Publishing

Bump the version in `pyproject.toml` and `src/groundtruther_mcp/__init__.py`, then run:

```bash
./publish.sh
```

The script builds and uploads to PyPI via Docker. It reads `PYPI_TOKEN` from the environment or from `../.env`.

## License

MIT
