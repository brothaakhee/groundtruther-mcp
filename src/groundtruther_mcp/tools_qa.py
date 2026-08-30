"""MCP tool implementations for the QA vertical (request_qa_test / get_qa_result).

QA missions are ordinary DIGITAL_REMOTE tasks whose acceptance contract carries a
`qa_script` (staging URL + ordered test steps) and requires a `screen_recording`
URL as evidence. The tester's verdict comes back as a `structured_data` proof with
`structured_data.qa_result` — validated server-side against the script.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import httpx
from .client import APIClient
from .tools import _error_response

MAX_QA_STEPS = 30
RECORDING_URL_KEY = "screen_recording"
MAX_CONTRACT_NOTES_CHARS = 2000

# Task status -> agent-facing QA status. IN_PROGRESS is special-cased: with a
# proof already on file it means the last submission was rejected (rejection
# returns the mission to IN_PROGRESS for resubmission). An OPEN/CLAIMED task
# with pending claim requests is additionally escalated to "claim_requested"
# (the approval gate needs the requesting agent's action).
_STATUS_MAP = {
    "OPEN": "pending",
    "CLAIMED": "claimed",
    "IN_PROGRESS": "in_progress",
    "PROOF_SUBMITTED": "awaiting_review",
    "COMPLETED": "completed",
    "DISPUTED": "disputed",
    "CANCELLED": "cancelled",
    "EXPIRED": "expired",
}


def _agent_status(raw_status: Optional[str]) -> str:
    """Map a raw task status to the lowercase agent-facing QA status."""
    return _STATUS_MAP.get(raw_status, (raw_status or "unknown").lower())


def _validate_staging_url(staging_url: str) -> Optional[str]:
    """Return an error message if staging_url is not a usable http(s) URL."""
    if not isinstance(staging_url, str) or not staging_url.strip():
        return "staging_url is required — the http(s) URL of the app the tester should exercise."
    parsed = urlparse(staging_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return (
            f"staging_url '{staging_url}' is not a valid http(s) URL. "
            "Provide a full URL like 'https://staging.example.com'."
        )
    return None


def _parse_steps(steps: str) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    """
    Parse and validate the steps JSON string.

    Returns (normalized_steps, error). Steps missing an 'id' get positional ids
    "s1".."sN"; explicit ids are preserved and checked for duplicates.
    """
    try:
        parsed = json.loads(steps)
    except (json.JSONDecodeError, TypeError):
        return None, (
            "steps must be valid JSON — a list of objects like "
            '[{"instruction": "Log in", "expected": "Dashboard loads"}].'
        )

    if not isinstance(parsed, list) or not parsed:
        return None, (
            "steps must be a non-empty JSON list of "
            '{"instruction", "expected"} objects (optionally with "id").'
        )
    if len(parsed) > MAX_QA_STEPS:
        return None, (
            f"steps supports at most {MAX_QA_STEPS} steps (got {len(parsed)}). "
            "Split the run into multiple QA missions."
        )

    normalized: List[Dict[str, str]] = []
    seen_ids = set()
    for i, step in enumerate(parsed):
        if not isinstance(step, dict):
            return None, f"steps[{i}] must be an object with 'instruction' and 'expected'."

        unknown = set(step.keys()) - {"id", "instruction", "expected"}
        if unknown:
            return None, (
                f"steps[{i}] has unknown keys: {', '.join(sorted(unknown))}. "
                "Each step may only have 'id', 'instruction', and 'expected'."
            )

        for key in ("instruction", "expected"):
            value = step.get(key)
            if not isinstance(value, str) or not value.strip():
                return None, f"steps[{i}] is missing a non-empty '{key}'."

        step_id = step.get("id")
        if step_id is None or (isinstance(step_id, str) and not step_id.strip()):
            step_id = f"s{i + 1}"
        elif not isinstance(step_id, str):
            return None, f"steps[{i}].id must be a string."

        if step_id in seen_ids:
            return None, (
                f"steps[{i}].id '{step_id}' is duplicated — step ids must be unique. "
                "Omit ids entirely to have them auto-assigned."
            )
        seen_ids.add(step_id)

        normalized.append({
            "id": step_id,
            "instruction": step["instruction"],
            "expected": step["expected"],
        })

    return normalized, None


def _compose_tester_notes(
    staging_url: str,
    step_count: int,
    environment: Optional[str],
    credentials_note: Optional[str],
) -> str:
    """Compose the contract 'notes' — the human tester's briefing."""
    lines = [
        f"QA test run: perform the {step_count}-step test script below on {staging_url}, "
        "in order, comparing what you actually see against each step's 'expected' result.",
        "RECORDING (required): record your ENTIRE test run as a screen recording "
        "(Loom, QuickTime, OBS, or similar), upload it anywhere link-shareable, and "
        "submit the link as the 'screen_recording' URL.",
        "VERDICTS: report pass, fail, or blocked for every step. Whenever a step does "
        "not pass, an 'observed' note describing what actually happened is REQUIRED.",
        "Also report the browser and OS you tested on (tester environment).",
    ]
    if environment:
        lines.append(f"Test environment requested: {environment}.")
    if credentials_note:
        lines.append(f"Access/credentials: {credentials_note}")
    return "\n".join(lines)


async def request_qa_test(
    staging_url: str,
    steps: str,
    budget: float = 15.0,
    deadline_hours: int = 24,
    environment: Optional[str] = None,
    credentials_note: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """
    Request a human QA test run of a staging URL.

    Creates a DIGITAL_REMOTE mission whose acceptance contract carries the test
    script (qa_script) and requires a screen-recording URL as proof.

    Args:
        staging_url: http(s) URL of the app under test
        steps: JSON string — list of {instruction, expected} objects, optionally
               with explicit unique 'id's ("s1".."sN" auto-assigned when missing)
        budget: USD reserved for the tester (default 15.0)
        deadline_hours: Hours from now until the mission expires (default 24)
        environment: Optional browser/device ask (e.g. "Chrome desktop")
        credentials_note: Optional test-account/access instructions for the tester
        title: Optional mission title (auto-generated when omitted)

    Returns:
        JSON string with task_id, status, and a one-line 'next' hint, or an error.
    """
    try:
        url_error = _validate_staging_url(staging_url)
        if url_error:
            return _error_response(url_error)

        normalized_steps, steps_error = _parse_steps(steps)
        if steps_error:
            return _error_response(steps_error)

        if budget is None or budget <= 0:
            return _error_response("budget must be a positive USD amount (e.g. 15.0).")
        if deadline_hours is None or deadline_hours <= 0:
            return _error_response("deadline_hours must be a positive number of hours (e.g. 24).")

        qa_script: Dict[str, Any] = {
            "staging_url": staging_url,
            "steps": normalized_steps,
        }
        if environment:
            qa_script["environment"] = environment
        if credentials_note:
            qa_script["credentials_note"] = credentials_note

        notes = _compose_tester_notes(
            staging_url, len(normalized_steps), environment, credentials_note
        )
        if len(notes) > MAX_CONTRACT_NOTES_CHARS:
            return _error_response(
                "credentials_note is too long — the composed tester briefing exceeds "
                f"{MAX_CONTRACT_NOTES_CHARS} characters. Shorten it (link to a doc if needed)."
            )

        acceptance_contract = {
            "notes": notes,
            "qa_script": qa_script,
            "required_urls": [
                {
                    "key": RECORDING_URL_KEY,
                    "label": "Screen recording of the full test run",
                    "required": True,
                }
            ],
        }

        host = urlparse(staging_url).netloc
        step_count = len(normalized_steps)
        deadline = (
            datetime.now(timezone.utc) + timedelta(hours=deadline_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        description_parts = [
            f"Scripted QA test of {staging_url}: follow the {step_count}-step checklist, "
            "screen-record the whole run, and report a pass/fail/blocked verdict per step.",
        ]
        if environment:
            description_parts.append(f"Requested environment: {environment}.")
        description_parts.append(
            "Full instructions, the step-by-step script, and any access notes are in "
            "the mission's acceptance criteria."
        )

        payload = {
            "title": title or f"QA web test — {host} ({step_count} steps)",
            "description": " ".join(description_parts),
            "deadline": deadline,
            "budget_amount": budget,
            "category": "DIGITAL_REMOTE",
            "acceptance_contract": acceptance_contract,
        }

        client = APIClient()
        response = await client.post("/tasks/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] == 201:
            data = result["data"]
            return json.dumps({
                "task_id": data.get("id"),
                # Same lowercase status vocabulary as get_qa_result ("pending", …).
                "status": _agent_status(data.get("status")),
                "next": (
                    "A human tester will request to claim the mission; unless "
                    "auto-approval applies you must approve their claim request "
                    "(watch for status=claim_requested from get_qa_result, or a "
                    "claim_request_received event from poll_events, then call "
                    "respond_to_claim_request). The tester then runs the script "
                    "and submits a screen recording plus per-step verdicts — poll "
                    "get_qa_result(task_id) for the outcome."
                ),
            })
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


def _latest_proof(proofs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the most recently submitted proof (by submitted_at), or None."""
    if not proofs:
        return None
    return max(proofs, key=lambda p: p.get("submitted_at") or "")


def _recording_url(proof: Dict[str, Any]) -> Optional[str]:
    """Extract the screen_recording URL from a proof's proof_urls."""
    for entry in proof.get("proof_urls") or []:
        if isinstance(entry, dict) and entry.get("key") == RECORDING_URL_KEY:
            return entry.get("url")
    return None


def _join_steps(
    qa_script: Dict[str, Any], qa_result: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Join the script's steps (instruction/expected) with the tester's result steps
    (verdict/observed). Returns (all_steps, failed_steps, blocked_steps) —
    failed_steps stays fail-only (its name is a compat contract); blocked steps
    get their own mirror list so the blocker context is directly consumable.
    """
    script_by_id = {
        s.get("id"): s for s in qa_script.get("steps", []) if isinstance(s, dict)
    }
    joined: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    for result_step in qa_result.get("steps", []):
        if not isinstance(result_step, dict):
            continue
        step_id = result_step.get("id")
        script_step = script_by_id.get(step_id, {})
        entry: Dict[str, Any] = {
            "id": step_id,
            "instruction": script_step.get("instruction"),
            "expected": script_step.get("expected"),
            "verdict": result_step.get("verdict"),
        }
        if result_step.get("observed") is not None:
            entry["observed"] = result_step["observed"]
        joined.append(entry)
        if entry["verdict"] in ("fail", "blocked"):
            detail = {
                "id": entry["id"],
                "instruction": entry["instruction"],
                "expected": entry["expected"],
                "observed": result_step.get("observed"),
            }
            (failed if entry["verdict"] == "fail" else blocked).append(detail)
    return joined, failed, blocked


async def _pending_claim_requests(client: APIClient, task_id: str) -> List[Dict[str, Any]]:
    """Best-effort fetch of pending claim requests on a mission (empty on any failure).

    Used to surface the approval gate: an OPEN mission with a pending request is
    waiting on the REQUESTING AGENT, not on a tester.
    """
    try:
        response = await client.get(
            "/agent/claim-requests/", params={"mission_uuid": task_id}
        )
        result = APIClient.handle_response(response)
        if result["status_code"] != 200:
            return []
        data = result["data"]
        rows = data.get("results") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict) and r.get("status") == "pending"]
    except Exception:  # noqa: BLE001 — never fail the status read on the CR lookup
        return []


def _next_action(status: str, verdict: Optional[str]) -> str:
    """Compose the one-line 'what to do now' hint for the requesting agent."""
    if status == "pending":
        return (
            "waiting for a tester to request the mission — check back later or use "
            "poll_events (a claim_request_received event means a tester wants in "
            "and is waiting for YOUR approval)"
        )
    if status == "claim_requested":
        return (
            "a tester has requested to claim this mission and is waiting for YOUR "
            "approval — review with list_pending_claim_requests(mission_uuid) and "
            "respond via respond_to_claim_request(mission_uuid, request_id, "
            "'approve' or 'decline'); the test cannot start until you respond"
        )
    if status == "claimed":
        return "a tester has claimed the mission — the test run should begin shortly"
    if status == "in_progress":
        return "the tester is running the script — check back soon"
    if status == "rejected":
        return (
            "the last submission was rejected — the tester may resubmit; "
            "use send_message to clarify expectations if needed"
        )
    if status == "awaiting_review":
        if verdict == "fail":
            return (
                "verdict=fail — awaiting human review: verify the recording backs the "
                "verdicts, approve via approve_mission (a documented fail is completed "
                "work), then fix the failed steps and consider re-requesting a test"
            )
        if verdict == "blocked":
            return (
                "verdict=blocked — the tester could not complete the run; read the "
                "observed notes, resolve the blocker (access, environment, outage), "
                "then approve via approve_mission or reject with a reason"
            )
        if verdict == "pass":
            return (
                "verdict=pass — awaiting human review: approve via approve_mission "
                "to release payment"
            )
        return "awaiting human review — approve via approve_mission or reject with a reason"
    if status == "completed":
        if verdict == "fail":
            return "verdict=fail — fix the failed steps and consider re-requesting a test"
        if verdict == "blocked":
            return (
                "verdict=blocked — resolve the blocker the tester reported and "
                "consider re-requesting a test"
            )
        return "verdict=pass — the test run passed; no further action needed"
    if status == "disputed":
        return "the mission is under dispute review — wait for the GroundTruther team's decision"
    if status == "cancelled":
        return "the mission was cancelled — re-request the test if you still need it"
    if status == "expired":
        return (
            "the mission expired before completion — re-request the test "
            "(consider a longer deadline or higher budget)"
        )
    return "check_mission_status for full mission details"


async def get_qa_result(task_id: str) -> str:
    """
    Get the structured result of a QA test mission.

    Fetches the mission and its latest proof, and returns an agent-consumable
    summary: status, overall_verdict, joined per-step results, failed_steps and
    blocked_steps (pre-joined with instruction/expected/observed for repro
    context), recording_url, tester_environment, notes, and a next_action hint.

    While the mission is unclaimed/claimed, pending tester claim requests are
    surfaced as status "claim_requested" with a pending_claim_requests list —
    the approval gate is on the requesting agent, not the tester.

    Args:
        task_id: UUID of a mission created via request_qa_test

    Returns:
        JSON string with the QA result summary or an error.
    """
    try:
        client = APIClient()
        response = await client.get(f"/tasks/{task_id}/")
        result = APIClient.handle_response(response)

        if result["status_code"] == 404:
            return _error_response(f"Mission not found: {task_id}")
        elif result["status_code"] == 401:
            return _error_response("Unauthorized: Invalid API key")
        elif result["status_code"] != 200:
            return _error_response(
                f"API error (HTTP {result['status_code']}): {result['data']}"
            )

        task = result["data"]
        contract = task.get("acceptance_contract") or {}
        qa_script = contract.get("qa_script")
        if not isinstance(qa_script, dict):
            return _error_response(
                f"Task {task_id} is not a QA mission (its acceptance contract has no "
                "qa_script). Use check_mission_status for general missions."
            )

        proofs = task.get("proofs") or []
        latest = _latest_proof(proofs)

        raw_status = task.get("status")
        if raw_status == "IN_PROGRESS" and latest is not None:
            # Rejection returns the mission to IN_PROGRESS with the proof on file.
            status = "rejected"
        else:
            status = _agent_status(raw_status)

        output: Dict[str, Any] = {
            "task_id": task.get("id"),
            "status": status,
            "failed_steps": [],
            "blocked_steps": [],
        }

        # Approval gate: an OPEN/CLAIMED mission with pending claim requests is
        # waiting on the requesting agent's approve/decline, not on a tester.
        if raw_status in ("OPEN", "CLAIMED"):
            pending = await _pending_claim_requests(client, task_id)
            if pending:
                status = "claim_requested"
                output["status"] = status
                output["pending_claim_requests"] = [
                    {
                        "request_id": r.get("id"),
                        "created_at": r.get("created_at"),
                    }
                    for r in pending
                ]

        qa_result = None
        if latest is not None:
            qa_result = (latest.get("structured_data") or {}).get("qa_result")

        verdict = None
        if isinstance(qa_result, dict):
            verdict = qa_result.get("overall_verdict")
            output["overall_verdict"] = verdict
            joined, failed, blocked = _join_steps(qa_script, qa_result)
            output["steps"] = joined
            output["failed_steps"] = failed
            output["blocked_steps"] = blocked
            if qa_result.get("tester_environment"):
                output["tester_environment"] = qa_result["tester_environment"]
            if qa_result.get("notes"):
                output["notes"] = qa_result["notes"]
            recording = _recording_url(latest)
            if recording:
                output["recording_url"] = recording

        output["next_action"] = _next_action(status, verdict)
        return json.dumps(output)

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")
