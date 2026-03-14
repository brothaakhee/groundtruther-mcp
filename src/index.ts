#!/usr/bin/env node
/**
 * GroundTruther MCP Server
 *
 * Exposes the GroundTruther agent API as MCP tools so AI agents
 * can interact with the platform natively.
 *
 * Environment variables:
 *   GT_API_URL   — API base URL (default: https://staging.groundtruther.io/api/v1)
 *   GT_API_KEY   — Agent API key (gt_sk_...)
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const API_URL = process.env.GT_API_URL || "https://staging.groundtruther.io/api/v1";
const API_KEY = process.env.GT_API_KEY || "";

// ── HTTP helper ─────────────────────────────────────────────────────────────

async function api(
  path: string,
  opts: { method?: string; body?: Record<string, unknown> } = {}
): Promise<{ status: number; data: unknown; ok: boolean }> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${API_KEY}`,
  };

  const res = await fetch(`${API_URL}${path}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });

  let data: unknown;
  if (res.status === 204) {
    data = null;
  } else {
    try {
      data = await res.json();
    } catch {
      data = null;
    }
  }

  return { status: res.status, data, ok: res.ok };
}

function formatResult(result: { status: number; data: unknown; ok: boolean }): string {
  if (result.ok) {
    return JSON.stringify(result.data, null, 2);
  }
  return `Error ${result.status}: ${JSON.stringify(result.data)}`;
}

// ── Server setup ────────────────────────────────────────────────────────────

const server = new McpServer({
  name: "groundtruther",
  version: "1.0.0",
});

// ── Task Management Tools ───────────────────────────────────────────────────

server.tool(
  "create_task",
  "Create a new task on the GroundTruther platform",
  {
    title: z.string().describe("Task title"),
    description: z.string().describe("Task description text"),
    category: z
      .enum([
        "PHYSICAL_WORLD",
        "IDENTITY_LEGAL",
        "OFFLINE_GATED",
        "EMBODIED_JUDGMENT",
        "SOCIAL_RELATIONAL",
        "EXPERT_CURATION",
      ])
      .describe("Task category"),
    budget_amount: z.string().describe("Budget in USD, e.g. '25.00'"),
    deadline: z.string().describe("ISO 8601 deadline, e.g. '2026-03-20T23:59:59Z'"),
    verification_type: z
      .enum(["PHOTO_PROOF", "VIDEO_PROOF", "STRUCTURED_DATA", "SIGNED_RECEIPT"])
      .describe("How the worker proves completion"),
    latitude: z.number().optional().describe("Task location latitude"),
    longitude: z.number().optional().describe("Task location longitude"),
    radius_km: z.number().optional().describe("Acceptable radius in km"),
    acceptance_contract: z
      .string()
      .optional()
      .describe("Acceptance criteria contract as JSON string"),
  },
  async (params) => {
    const body: Record<string, unknown> = {
      title: params.title,
      description: { text: params.description },
      category: params.category,
      budget_amount: params.budget_amount,
      deadline: params.deadline,
      verification_type: params.verification_type,
    };
    if (params.latitude !== undefined) body.latitude = params.latitude;
    if (params.longitude !== undefined) body.longitude = params.longitude;
    if (params.radius_km !== undefined) body.radius_km = params.radius_km;
    if (params.acceptance_contract) body.acceptance_contract = JSON.parse(params.acceptance_contract);

    const result = await api("/tasks/", { method: "POST", body });
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

server.tool(
  "list_tasks",
  "List all tasks owned by this agent",
  {
    status: z.string().optional().describe("Filter by status: OPEN, CLAIMED, IN_PROGRESS, PROOF_SUBMITTED, COMPLETED, CANCELLED"),
    category: z.string().optional().describe("Filter by category"),
  },
  async (params) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.category) qs.set("category", params.category);
    const query = qs.toString() ? `?${qs.toString()}` : "";
    const result = await api(`/tasks/${query}`);
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

server.tool(
  "get_task",
  "Get details of a specific task",
  {
    task_id: z.string().describe("Task UUID"),
  },
  async (params) => {
    const result = await api(`/tasks/${params.task_id}/`);
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

// ── Task Workflow Tools ─────────────────────────────────────────────────────

server.tool(
  "approve_task",
  "Approve a submitted proof and release payment to the worker",
  {
    task_id: z.string().describe("Task UUID"),
  },
  async (params) => {
    const result = await api(`/tasks/${params.task_id}/approve/`, { method: "POST" });
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

server.tool(
  "reject_task",
  "Reject a submitted proof with a reason",
  {
    task_id: z.string().describe("Task UUID"),
    reason: z.string().describe("Rejection reason"),
  },
  async (params) => {
    const result = await api(`/tasks/${params.task_id}/reject/`, {
      method: "POST",
      body: { reason: params.reason },
    });
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

server.tool(
  "cancel_task",
  "Cancel a task. OPEN/CLAIMED: immediate. IN_PROGRESS: requests worker consent.",
  {
    task_id: z.string().describe("Task UUID"),
    reason: z.string().optional().describe("Cancellation reason"),
  },
  async (params) => {
    const body: Record<string, unknown> = {};
    if (params.reason) body.reason = params.reason;
    const result = await api(`/tasks/${params.task_id}/cancel/`, { method: "POST", body });
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

server.tool(
  "respond_to_cancellation",
  "Approve or decline a pending cancellation/drop request from a worker",
  {
    task_id: z.string().describe("Task UUID"),
    action: z.enum(["approve", "decline"]).describe("Whether to approve or decline the request"),
  },
  async (params) => {
    const result = await api(`/tasks/${params.task_id}/cancel/${params.action}/`, {
      method: "POST",
    });
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

// ── Messaging Tools ─────────────────────────────────────────────────────────

server.tool(
  "send_message",
  "Send a message to the worker on a task",
  {
    task_id: z.string().describe("Task UUID"),
    content: z.string().describe("Message content (max 2000 chars)"),
  },
  async (params) => {
    const result = await api(`/tasks/${params.task_id}/messages/`, {
      method: "POST",
      body: { content: params.content, attachments: [] },
    });
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

server.tool(
  "get_messages",
  "Get all messages on a task",
  {
    task_id: z.string().describe("Task UUID"),
  },
  async (params) => {
    const result = await api(`/tasks/${params.task_id}/messages/`);
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

// ── Events & Webhooks ───────────────────────────────────────────────────────

server.tool(
  "poll_events",
  "Poll for new agent events (task claims, proof submissions, etc.)",
  {
    since: z.string().optional().describe("ISO 8601 timestamp to get events after"),
  },
  async (params) => {
    const qs = params.since ? `?since=${params.since}` : "";
    const result = await api(`/events/${qs}`);
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

// ── Review Tools ────────────────────────────────────────────────────────────

server.tool(
  "review_worker",
  "Leave a rating and comment for the worker after task completion",
  {
    task_id: z.string().describe("Task UUID"),
    rating: z.number().min(1).max(5).describe("Rating 1-5"),
    comment: z.string().optional().describe("Optional review comment"),
  },
  async (params) => {
    const body: Record<string, unknown> = { rating: params.rating };
    if (params.comment) body.comment = params.comment;
    const result = await api(`/tasks/${params.task_id}/review/`, {
      method: "POST",
      body,
    });
    return { content: [{ type: "text" as const, text: formatResult(result) }] };
  }
);

// ── Start ───────────────────────────────────────────────────────────────────

async function main() {
  if (!API_KEY) {
    console.error("GT_API_KEY environment variable is required");
    process.exit(1);
  }
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
