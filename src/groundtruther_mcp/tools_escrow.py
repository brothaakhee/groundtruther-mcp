"""On-chain escrow MCP tools (keyless).

The backend builds unsigned/partial-signed transactions; these tools sign them locally with the
agent's payer key (SolanaSigner, never sent to the backend) and submit the signed bytes. When no
payer key is configured (Mode B), the unsigned transaction is returned for an external wallet.
"""
import json
from typing import Optional

import httpx

from .client import APIClient
from .solana_signer import SolanaSigner
from .tools import _error_response


def _signer() -> SolanaSigner:
    return SolanaSigner()


async def post_mission_onchain(
    title: str, description: str, deadline: str, budget_amount: float, category: str,
    acceptance_contract: str, lat: Optional[float] = None, lng: Optional[float] = None,
    radius_mi: Optional[float] = None, template_id: Optional[str] = None,
    payer_pubkey: Optional[str] = None, auto_claim: bool = False,
    claim_window_secs: Optional[int] = None, idempotency_key: Optional[str] = None,
) -> str:
    """Create an on-chain escrow mission. Mode A (payer key configured) funds it in one call;
    Mode B returns the unsigned fund transaction for an external wallet to sign + submit."""
    try:
        try:
            contract = json.loads(acceptance_contract) if isinstance(acceptance_contract, str) else acceptance_contract
        except json.JSONDecodeError:
            return _error_response("acceptance_contract must be valid JSON")

        signer = _signer()
        payload = {"title": title, "description": description, "deadline": deadline,
                   "budget_amount": budget_amount, "category": category,
                   "acceptance_contract": contract, "auto_claim": auto_claim}
        pk = payer_pubkey or signer.payer_pubkey
        if pk:
            payload["payer_pubkey"] = pk
        for k, v in (("latitude", lat), ("longitude", lng), ("radius_mi", radius_mi),
                     ("template_id", template_id), ("claim_window_secs", claim_window_secs),
                     ("idempotency_key", idempotency_key)):
            if v is not None:
                payload[k] = v

        client = APIClient()
        res = APIClient.handle_response(await client.post("/escrow/missions/", data=payload))
        if res["status_code"] not in (200, 201):
            return _error_response(f"create failed (HTTP {res['status_code']}): {res['data']}")
        data = res["data"]
        task_id = data["mission"]["task_id"]
        fund = data.get("fund_transaction") or {}

        if not signer.configured:
            return json.dumps({"mode": "unsigned", "mission": data["mission"],
                               "quote": data.get("quote"), "fund_transaction": fund})

        signed = signer.sign_and_serialize(fund["tx_base64"])
        sub = APIClient.handle_response(
            await client.post(f"/escrow/missions/{task_id}/submit-fund/", data={"signed_tx_base64": signed}))
        if sub["status_code"] != 200:
            return _error_response(f"submit-fund failed (HTTP {sub['status_code']}): {sub['data']}")
        return json.dumps({"mode": "funded", "mission": data["mission"], "quote": data.get("quote"),
                           **sub["data"]})
    except httpx.RequestError as e:
        return _error_response(f"Network error: {e}")
    except Exception as e:  # noqa: BLE001
        return _error_response(f"Unexpected error: {e}")


async def get_mission_status(task_id: str, refresh: bool = False) -> str:
    try:
        client = APIClient()
        ep = f"/escrow/missions/{task_id}/" + ("?refresh=1" if refresh else "")
        res = APIClient.handle_response(await client.get(ep))
        if res["status_code"] != 200:
            return _error_response(f"HTTP {res['status_code']}: {res['data']}")
        return json.dumps(res["data"])
    except Exception as e:  # noqa: BLE001
        return _error_response(f"Unexpected error: {e}")


async def _build_sign_submit(task_id: str, build_path: str, kind: str) -> str:
    try:
        signer = _signer()
        if not signer.configured:
            return _error_response("GT_SOLANA_PAYER_SK required to sign this action")
        client = APIClient()
        b = APIClient.handle_response(await client.post(f"/escrow/missions/{task_id}/{build_path}/", data={}))
        if b["status_code"] != 200:
            return _error_response(f"build {kind} failed (HTTP {b['status_code']}): {b['data']}")
        env = b["data"]["transaction"]
        signed = signer.sign_and_serialize(env["tx_base64"])
        s = APIClient.handle_response(
            await client.post(f"/escrow/missions/{task_id}/submit-tx/",
                              data={"signed_tx_base64": signed, "kind": kind}))
        if s["status_code"] != 200:
            return _error_response(f"submit {kind} failed (HTTP {s['status_code']}): {s['data']}")
        return json.dumps(s["data"])
    except Exception as e:  # noqa: BLE001
        return _error_response(f"Unexpected error: {e}")


async def release_mission(task_id: str) -> str:
    return await _build_sign_submit(task_id, "release", "release")


async def dispute_mission(task_id: str) -> str:
    return await _build_sign_submit(task_id, "dispute", "dispute")


async def cancel_escrow_mission(task_id: str) -> str:
    return await _build_sign_submit(task_id, "cancel", "cancel")


async def assign_worker(task_id: str, worker_user_id: str, worker_pubkey: str,
                        worker_payout_owner: str, claim_request_id: Optional[str] = None) -> str:
    try:
        signer = _signer()
        if not signer.configured:
            return _error_response("GT_SOLANA_PAYER_SK required to co-sign assignment")
        client = APIClient()
        body = {"worker_user_id": worker_user_id, "worker_pubkey": worker_pubkey,
                "worker_payout_owner": worker_payout_owner}
        if claim_request_id:
            body["claim_request_id"] = claim_request_id
        b = APIClient.handle_response(await client.post(f"/escrow/missions/{task_id}/assign/", data=body))
        if b["status_code"] != 200:
            return _error_response(f"assign build failed (HTTP {b['status_code']}): {b['data']}")
        signed = signer.co_sign(b["data"]["assign_transaction"]["tx_base64"])
        s = APIClient.handle_response(await client.post(
            f"/escrow/missions/{task_id}/submit-assign/",
            data={"signed_tx_base64": signed, "worker_user_id": worker_user_id,
                  "worker_payout_owner": worker_payout_owner}))
        if s["status_code"] != 200:
            return _error_response(f"submit-assign failed (HTTP {s['status_code']}): {s['data']}")
        return json.dumps(s["data"])
    except Exception as e:  # noqa: BLE001
        return _error_response(f"Unexpected error: {e}")


async def submit_signed_mission(task_id: str, signed_tx_base64: str) -> str:
    """Mode-B completion: submit a fund transaction signed by an external wallet."""
    try:
        client = APIClient()
        s = APIClient.handle_response(await client.post(
            f"/escrow/missions/{task_id}/submit-fund/", data={"signed_tx_base64": signed_tx_base64}))
        if s["status_code"] != 200:
            return _error_response(f"submit-fund failed (HTTP {s['status_code']}): {s['data']}")
        return json.dumps(s["data"])
    except Exception as e:  # noqa: BLE001
        return _error_response(f"Unexpected error: {e}")
