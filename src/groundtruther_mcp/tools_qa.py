"""MCP tool implementations for the QA vertical (request_qa_test / get_qa_result).

QA missions are ordinary DIGITAL_REMOTE tasks whose acceptance contract carries a
`qa_script` (staging URL + ordered test steps) and requires a `screen_recording`
URL as evidence. The tester's verdict comes back as a `structured_data` proof with
`structured_data.qa_result` — validated server-side against the script.
"""
import ipaddress
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import httpx
from .client import APIClient
from .solana_signer import SolanaSigner
from .tools import _error_response
from .tools_escrow import create_and_fund_escrow_mission, unfunded_mission_note

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


# Hostname suffixes that never resolve on the public internet (mDNS / internal zones).
_UNREACHABLE_HOST_SUFFIXES = (".local", ".internal", ".localhost")


def _staging_host_unreachable(host: Optional[str]) -> bool:
    """Pure address classification (no network I/O): can an external tester reach `host`?

    Mirrors the server's contract validator: loopback (localhost, 127.0.0.0/8, ::1),
    private (RFC 1918 & friends), link-local, and .local/.internal/.localhost hosts
    are unreachable from a tester's machine.
    """
    if not host:
        return False
    host = host.strip().lower().rstrip(".")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return ip.is_loopback or ip.is_private or ip.is_link_local
    if host == "localhost":
        return True
    return any(host.endswith(suffix) for suffix in _UNREACHABLE_HOST_SUFFIXES)


def _staging_url_reachability_warning(staging_url: str) -> Optional[str]:
    """A warning (not a block) for staging URLs human testers can't reach.

    The client can't know the server's environment (dev servers allow private
    URLs for dogfooding), so this warns that the server may reject the mission
    rather than refusing to send it.
    """
    host = urlparse(staging_url).hostname
    if not _staging_host_unreachable(host):
        return None
    return (
        f"Testers can't reach {host} — it's a loopback/private/internal address, "
        "and the server may reject this mission. Expose your staging via a tunnel "
        "(e.g. `cloudflared tunnel --url http://localhost:PORT` or ngrok) and use "
        "that URL."
    )


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


_MISSING_PAYER_KEY_ERROR = (
    "escrow mode pays from your own wallet; set GT_SOLANA_PAYER_SK (your Solana payer "
    "secret key — it never leaves this machine) — see docs/qa-vertical-escrow.md. "
    "For external-wallet signing use post_mission_onchain instead (Mode B), or drop "
    "escrow=True to pay from your custodial GroundTruther balance."
)


def _escrow_create_error_message(err: Dict[str, Any]) -> str:
    """Compose an instructive error for a failed escrow create/fund from tools_escrow's
    error info ({"stage", "status_code", "data"})."""
    status_code = err["status_code"]
    data = err["data"]
    detail = data.get("detail") if isinstance(data, dict) else data
    if err["stage"] == "create" and status_code == 403:
        return (
            f"Escrow is not enabled for your agent yet ({detail}). Enablement is "
            "currently concierge onboarding: ask the GroundTruther team to set "
            "escrow_enabled=True (and optionally default_payer_pubkey) on your agent "
            "— see docs/qa-vertical-escrow.md. Meanwhile, request_qa_test without "
            "escrow=True pays from your custodial balance and works today."
        )
    if err["stage"] == "create" and status_code == 404:
        return (
            "Escrow endpoints are not available on this deployment (HTTP 404) — "
            "on-chain escrow may be globally disabled (GT_ESCROW_ENABLED on the "
            "server). Use request_qa_test without escrow=True, or ask the "
            "GroundTruther team about escrow availability."
        )
    message = f"escrow {err['stage']} failed (HTTP {status_code}): {data}"
    if err.get("task_id"):
        # The create succeeded before funding failed: never leave a silent
        # dangling OPEN mission (e2e F4). The backend detail already explains
        # WHY (balance diagnosis on unfunded wallets); this explains the state.
        message += unfunded_mission_note(err["task_id"])
    return message


def _escrow_next_hint() -> str:
    """The 'what happens now' hint for a freshly funded escrow QA mission."""
    return (
        "Mission funded from your own wallet — the USDC now sits in the on-chain "
        "escrow, not with GroundTruther. A vetted human tester can claim instantly "
        "(auto_claim, gas-sponsored), run the script, and submit a screen recording "
        "plus per-step verdicts — poll get_qa_result(task_id) for the outcome. When "
        "the verdict is in, verify the recording and pay the tester with "
        "release_mission(task_id) (NOT approve_mission — this is an escrow "
        "mission); use dispute_mission if the evidence doesn't back the verdicts. "
        "If you go silent, the escrow auto-releases to the tester after the review "
        "window."
    )


def _escrow_configured() -> bool:
    """Whether this MCP process is escrow-aware (payer key or escrow flag set)."""
    if os.getenv("GT_SOLANA_PAYER_SK"):
        return True
    return os.getenv("GT_ESCROW_ENABLED", "").strip().lower() in ("1", "true", "yes")


async def request_qa_test(
    staging_url: str,
    steps: str,
    budget: float = 15.0,
    deadline_hours: int = 24,
    environment: Optional[str] = None,
    credentials_note: Optional[str] = None,
    title: Optional[str] = None,
    escrow: bool = False,
) -> str:
    """
    Request a human QA test run of a staging URL.

    Creates a DIGITAL_REMOTE mission whose acceptance contract carries the test
    script (qa_script) and requires a screen-recording URL as proof.

    Two payment modes:
    - escrow=False (default, custodial): the budget is reserved from your
      GroundTruther platform balance and released on approve_mission.
    - escrow=True (self-custody, devnet today): the SAME validated contract is
      posted as an on-chain USDC escrow mission funded from YOUR wallet. The
      backend builds an unsigned fund transaction, this process signs it locally
      with GT_SOLANA_PAYER_SK (the key never leaves your machine) and submits
      it. Payment is released with release_mission, not approve_mission.
      Requires GT_SOLANA_PAYER_SK and an escrow-enabled agent — see
      docs/qa-vertical-escrow.md.

    Args:
        staging_url: http(s) URL of the app under test. Must be reachable by an
                     external human tester — localhost/private/.local addresses
                     draw a warning and production servers reject them; tunnel
                     local apps first (e.g. `cloudflared tunnel --url
                     http://localhost:PORT` or ngrok) and pass the tunnel URL
        steps: JSON string — list of {instruction, expected} objects, optionally
               with explicit unique 'id's ("s1".."sN" auto-assigned when missing)
        budget: USD reserved for the tester (default 15.0). Escrow missions are
                bounded server-side (~$1-$100 on devnet)
        deadline_hours: Hours from now until the mission expires (default 24)
        environment: Optional browser/device ask (e.g. "Chrome desktop")
        credentials_note: Optional test-account/access instructions for the tester
        title: Optional mission title (auto-generated when omitted)
        escrow: Pay from your own Solana wallet via on-chain escrow (see above)

    Returns:
        JSON string with task_id, status, and a one-line 'next' hint, or an error.
        Escrow mode adds mode="escrow", onchain_status, mission_pda and fund_sig.
    """
    try:
        signer: Optional[SolanaSigner] = None
        if escrow:
            signer = SolanaSigner()
            if not signer.configured:
                return _error_response(_MISSING_PAYER_KEY_ERROR)

        url_error = _validate_staging_url(staging_url)
        if url_error:
            return _error_response(url_error)
        # Warn (don't block) on hosts human testers can't reach — the server may
        # reject the mission outright unless it's a dev stack.
        reachability_warning = _staging_url_reachability_warning(staging_url)

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

        if escrow:
            # Same validated contract, self-custody rails: POST /escrow/missions/
            # with the agent's own payer, then sign + submit the fund tx locally
            # (the create→sign→submit-fund sequence is shared with
            # post_mission_onchain via create_and_fund_escrow_mission).
            payload["payer_pubkey"] = signer.payer_pubkey
            # The proven QA-escrow flow (docs/qa-vertical-escrow.md): vetted
            # testers claim instantly via gas-sponsored transactions instead of
            # the custodial claim-approval gate.
            payload["auto_claim"] = True
            result, err = await create_and_fund_escrow_mission(client, signer, payload)
            if err:
                return _error_response(_escrow_create_error_message(err))
            # The signer is configured (checked above), so the helper always took
            # the Mode-A path: result carries the submit-fund response fields.
            mission = result.get("mission") or {}
            output = {
                "task_id": mission.get("task_id"),
                # Same lowercase status vocabulary as get_qa_result.
                "status": _agent_status("OPEN"),
                "mode": "escrow",
                "onchain_status": result.get("onchain_status"),
                "mission_pda": mission.get("mission_pda"),
                "fund_sig": result.get("fund_sig"),
                "next": _escrow_next_hint(),
            }
            if reachability_warning:
                output["warning"] = reachability_warning
            return json.dumps(output)

        response = await client.post("/tasks/", data=payload)
        result = APIClient.handle_response(response)

        if result["status_code"] == 201:
            data = result["data"]
            output = {
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
            }
            if reachability_warning:
                output["warning"] = reachability_warning
            return json.dumps(output)
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


async def _escrow_mission_lookup(client: APIClient, task_id: str) -> Optional[Dict[str, Any]]:
    """Best-effort escrow-mission probe (None on any failure or for custodial missions).

    The task detail (GET /tasks/{id}/) carries no escrow marker, so mode is
    detected by asking the escrow surface directly: 200 means this task is an
    on-chain mission; 403/404 (agent not escrow-enabled / escrow off / custodial
    task) means custodial. Only called when this process is escrow-configured,
    so pure-custodial setups keep their single-call reads.
    """
    if not _escrow_configured():
        return None
    try:
        result = APIClient.handle_response(
            await client.get(f"/escrow/missions/{task_id}/")
        )
        if result["status_code"] == 200 and isinstance(result["data"], dict):
            return result["data"]
    except Exception:  # noqa: BLE001 — never fail the status read on the probe
        return None
    return None


def _escrow_next_action(status: str, verdict: Optional[str],
                        auto_claim: bool = False) -> Optional[str]:
    """Escrow-mode override for _next_action (None = fall through to the shared text).

    On escrow missions payment moves on-chain: approval is release_mission (signs
    a release tx with your payer key), rejection is dispute_mission, and
    arbitration is escalate_mission_onchain. Covers ALL states (e2e F3): the
    pre-verdict states must never advise the custodial claim-approval gate on an
    auto-claim mission — auto-claim has no approval step by design.
    """
    _release_reminder = (
        "when the verdict lands, review and pay from escrow via "
        "release_mission(task_id) — approve_mission does not apply to escrow"
    )
    if status == "pending":
        if auto_claim:
            return (
                "waiting for a tester — vetted testers claim this ESCROW mission "
                "instantly (auto-claim, gas-sponsored; there is NO approval step "
                "for you). Poll get_qa_result(task_id) for the outcome; "
                + _release_reminder + ". If you go silent after the verdict, the "
                "escrow auto-releases to the tester after the review window."
            )
        return (
            "waiting for a tester to request this ESCROW mission — approve a "
            "claim via list_pending_claim_requests / respond_to_claim_request; "
            + _release_reminder + "."
        )
    if status == "claimed":
        return ("a tester has claimed this ESCROW mission — the test run should "
                "begin shortly; " + _release_reminder + ".")
    if status == "in_progress":
        return ("the tester is running the script on this ESCROW mission — check "
                "back soon; " + _release_reminder + ".")
    if status == "completed":
        base = ("this ESCROW mission is complete — payment moved on-chain "
                "(released from escrow); no payment action left")
        if verdict == "fail":
            return base + ". verdict=fail: fix the failed steps and consider re-requesting a test."
        if verdict == "blocked":
            return base + ". verdict=blocked: resolve the reported blocker and consider re-requesting a test."
        return base + "."
    if status == "awaiting_review":
        if verdict == "fail":
            return (
                "verdict=fail — awaiting your review on an ESCROW mission: verify the "
                "recording backs the verdicts, then pay the tester from escrow via "
                "release_mission(task_id) (a documented fail is completed work; "
                "approve_mission does not apply to escrow). Then fix the failed steps "
                "and consider re-requesting a test. Use dispute_mission if the "
                "evidence doesn't back the verdicts."
            )
        if verdict == "blocked":
            return (
                "verdict=blocked — the tester could not complete the run on this "
                "ESCROW mission; read the observed notes and resolve the blocker "
                "(access, environment, outage), then pay via release_mission(task_id) "
                "or contest via dispute_mission (approve_mission does not apply to "
                "escrow)."
            )
        if verdict == "pass":
            return (
                "verdict=pass — awaiting your review on an ESCROW mission: verify the "
                "recording, then release payment from escrow via "
                "release_mission(task_id) (approve_mission does not apply to escrow). "
                "If you go silent, the escrow auto-releases after the review window."
            )
        return (
            "awaiting your review on an ESCROW mission — pay via "
            "release_mission(task_id) or contest via dispute_mission "
            "(approve_mission does not apply to escrow)."
        )
    if status == "disputed":
        return (
            "the ESCROW mission is disputed — release_mission(task_id) withdraws the "
            "dispute and pays the tester ('we worked it out'), or "
            "escalate_mission_onchain(task_id) requests GroundTruther arbitration."
        )
    return None


def _next_action(status: str, verdict: Optional[str], escrow: bool = False,
                 auto_claim: bool = False) -> str:
    """Compose the one-line 'what to do now' hint for the requesting agent."""
    if escrow:
        override = _escrow_next_action(status, verdict, auto_claim=auto_claim)
        if override:
            return override
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

    Works for both payment modes. On a mission created with escrow=True (paid
    from the agent's own wallet), the response carries mode="escrow",
    onchain_status and mission_pda in EVERY state, and next_action points at
    release_mission / dispute_mission instead of approve_mission /
    reject_mission. Auto-claim escrow missions are never described as waiting
    for claim approval (there is no approval gate).

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

        # Escrow awareness in ALL states (e2e F3): on an escrow mission payment
        # moves on-chain, so every next_action must say release_mission — and an
        # auto-claim mission must never be described as waiting for claim
        # approval. Probed only when this process is escrow-configured (see
        # _escrow_mission_lookup), so pure-custodial setups keep single-call reads.
        escrow_mission = await _escrow_mission_lookup(client, task_id)
        auto_claim = bool(escrow_mission.get("auto_claim")) if escrow_mission else False
        if escrow_mission is not None:
            output["mode"] = "escrow"
            if escrow_mission.get("onchain_status"):
                output["onchain_status"] = escrow_mission["onchain_status"]
            if escrow_mission.get("mission_pda"):
                output["mission_pda"] = escrow_mission["mission_pda"]

        # Approval gate: an OPEN/CLAIMED mission with pending claim requests is
        # waiting on the requesting agent's approve/decline, not on a tester.
        # Auto-claim escrow missions have NO approval gate — skip the lookup.
        if raw_status in ("OPEN", "CLAIMED") and not (escrow_mission is not None and auto_claim):
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

        output["next_action"] = _next_action(
            status, verdict, escrow=escrow_mission is not None, auto_claim=auto_claim
        )
        return json.dumps(output)

    except httpx.RequestError as e:
        return _error_response(f"Network error: {str(e)}")
    except Exception as e:
        return _error_response(f"Unexpected error: {str(e)}")
