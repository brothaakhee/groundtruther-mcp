"""Wallet-native auto-auth (SIWS) — mint the GroundTruther API key from a wallet signature.

When GT_API_KEY is absent and GT_SOLANA_PAYER_SK is present, the MCP server
authenticates by signing a server-issued SIWS challenge with the local payer key
(which never leaves this process) and exchanging it for an API key at
POST /auth/wallet/verify. The minted key is persisted 0600 in
~/.groundtruther/credentials.json, keyed by (GT_API_URL, pubkey).

ANTI-BLIND-SIGNING: this client NEVER signs raw server bytes. The challenge is
parsed and validated first —
  * the domain line must name the configured GT host (from GT_API_URL),
  * the address line must be our own pubkey,
  * the text must be pure ASCII and contain the server-reported nonce,
  * it must not be parseable as a Solana transaction (defense in depth; the
    b"\xffsolana offchain" preamble we prepend OURSELVES already guarantees the
    signed payload can never be a valid transaction — 0xff is an impossible
    first byte for one).
Anything unexpected raises a loud WalletAuthError and nothing is signed.
"""
import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from .config import Config
from .solana_signer import SolanaSigner

logger = logging.getLogger(__name__)

OFFCHAIN_SIGNING_DOMAIN = b"\xffsolana offchain"
OFFCHAIN_HEADER_VERSION = 0
OFFCHAIN_FORMAT_RESTRICTED_ASCII = 0
OFFCHAIN_MAX_PAYLOAD = 1212  # Anza spec: version-0 payload must fit in a transaction

DEFAULT_CREDENTIALS_PATH = "~/.groundtruther/credentials.json"


class WalletAuthError(Exception):
    """Wallet auth failed — the message says exactly why, loudly."""


# ---------------------------------------------------------------------------
# environment / configuration
# ---------------------------------------------------------------------------

def _api_url() -> str:
    return (os.getenv("GT_API_URL") or Config.API_BASE_URL).rstrip("/")


def wallet_auth_available() -> bool:
    """True when auto-auth should drive credentials: payer key set, no explicit API key."""
    return bool(os.getenv("GT_SOLANA_PAYER_SK")) and not os.getenv("GT_API_KEY")


def expected_domain(api_base_url: str) -> str:
    """The SIWS domain we insist the challenge is bound to: the GT host[:port]."""
    netloc = urlparse(api_base_url).netloc
    if not netloc:
        raise WalletAuthError(
            f"GT_API_URL '{api_base_url}' has no host — cannot derive the expected "
            "sign-in domain.")
    return netloc


# ---------------------------------------------------------------------------
# anti-blind-signing challenge validation
# ---------------------------------------------------------------------------

def _parses_as_transaction(message: str) -> bool:
    """Defense in depth: does the 'challenge' decode into a Solana transaction/message?"""
    try:
        from solders.message import Message, MessageV0
        from solders.transaction import Transaction, VersionedTransaction
    except ImportError:  # pragma: no cover — solders is required for wallet auth anyway
        return False

    candidates = []
    try:
        candidates.append(message.encode("ascii"))
    except UnicodeEncodeError:
        pass
    stripped = message.strip()
    try:
        candidates.append(base64.b64decode(stripped, validate=True))
    except Exception:  # noqa: BLE001 — not base64: nothing to add
        pass
    for raw in candidates:
        for cls in (Transaction, VersionedTransaction, Message, MessageV0):
            try:
                cls.from_bytes(raw)
                return True
            except Exception:  # noqa: BLE001 — not this shape; keep probing
                continue
    return False


def validate_challenge(message: str, nonce: str, expected: str, own_pubkey: str) -> None:
    """Refuse to sign anything that isn't exactly the SIWS challenge we asked for."""
    refuse = "REFUSING TO SIGN wallet-auth challenge: "
    if not isinstance(message, str) or not message.strip():
        raise WalletAuthError(refuse + "the server returned an empty/non-text message.")
    if not message.isascii():
        raise WalletAuthError(
            refuse + "the message contains non-ASCII characters (possible homoglyph "
            "or hidden-content attack).")
    if len(message.encode("ascii")) > OFFCHAIN_MAX_PAYLOAD - 20:
        raise WalletAuthError(refuse + "the message is implausibly large for a SIWS challenge.")
    if _parses_as_transaction(message):
        raise WalletAuthError(
            refuse + "the 'challenge' parses as a Solana TRANSACTION — signing it could "
            "move funds. This server is not to be trusted.")

    lines = message.split("\n")
    expected_first = f"{expected} wants you to sign in with your Solana account:"
    if lines[0] != expected_first:
        raise WalletAuthError(
            refuse + f"sign-in domain mismatch. Expected the challenge to start with "
            f"'{expected_first}' (from GT_API_URL) but got: '{lines[0][:120]}'.")
    if len(lines) < 2 or lines[1] != own_pubkey:
        got = lines[1][:120] if len(lines) > 1 else "<missing>"
        raise WalletAuthError(
            refuse + f"the challenge address is not our wallet pubkey. Expected "
            f"'{own_pubkey}', got '{got}'.")
    if not nonce or f"Nonce: {nonce}" not in lines:
        raise WalletAuthError(
            refuse + "the challenge does not contain the server-reported nonce — "
            "the message and metadata disagree.")


def offchain_message_bytes(message: str) -> bytes:
    """Wrap the validated challenge in the Anza off-chain layout WE construct.

    Prepending b"\xffsolana offchain" ourselves guarantees the signed payload can
    never be a valid transaction, whatever the server sent.
    """
    msg = message.encode("ascii")
    payload = (
        OFFCHAIN_SIGNING_DOMAIN
        + bytes([OFFCHAIN_HEADER_VERSION])
        + bytes([OFFCHAIN_FORMAT_RESTRICTED_ASCII])
        + len(msg).to_bytes(2, "little")
        + msg
    )
    if len(payload) > OFFCHAIN_MAX_PAYLOAD:
        raise WalletAuthError("off-chain payload exceeds the 1212-byte Anza limit.")
    return payload


# ---------------------------------------------------------------------------
# credential store (0600 file, 0700 dir; keyed by api_url + pubkey)
# ---------------------------------------------------------------------------

def credentials_path() -> Path:
    return Path(os.getenv("GT_CREDENTIALS_PATH", DEFAULT_CREDENTIALS_PATH)).expanduser()


def _cred_key(api_url: str, pubkey: str) -> str:
    return f"{api_url}|{pubkey}"


def _read_store() -> dict:
    path = credentials_path()
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        logger.warning("credentials file %s is unreadable/corrupt; treating as empty", path)
        return {}


def load_stored_api_key(api_url: str, pubkey: str) -> Optional[str]:
    entry = _read_store().get(_cred_key(api_url, pubkey))
    if isinstance(entry, dict) and isinstance(entry.get("api_key"), str):
        return entry["api_key"]
    return None


def store_api_key(api_url: str, pubkey: str, api_key: str,
                  agent_name: Optional[str] = None) -> None:
    from datetime import datetime, timezone

    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:  # pragma: no cover — best effort on exotic filesystems
        pass
    store = _read_store()
    store[_cred_key(api_url, pubkey)] = {
        "api_key": api_key,
        "agent_name": agent_name,
        "minted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # 0600 from the first byte: open with restrictive mode, then atomic replace.
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, path)
    path.chmod(0o600)


# ---------------------------------------------------------------------------
# the auth flow
# ---------------------------------------------------------------------------

async def _challenge_and_verify(signer: SolanaSigner, api_url: str) -> dict:
    """challenge -> validate -> sign(preamble+message) -> verify. Returns the verify body."""
    pubkey = signer.payer_pubkey
    domain = expected_domain(api_url)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{api_url}/auth/wallet/challenge/",
                                 json={"pubkey": pubkey})
        if resp.status_code != 200:
            raise WalletAuthError(
                f"wallet-auth challenge failed (HTTP {resp.status_code}): "
                f"{_detail(resp)}")
        body = resp.json()
        message, nonce = body.get("message"), body.get("nonce")

        # THE anti-blind-signing gate: nothing is signed unless this passes.
        validate_challenge(message, nonce, domain, pubkey)

        signature = signer.sign_message_bytes(offchain_message_bytes(message))
        resp2 = await client.post(f"{api_url}/auth/wallet/verify/",
                                  json={"pubkey": pubkey, "signature": signature})
        if resp2.status_code != 200:
            raise WalletAuthError(
                f"wallet-auth verify failed (HTTP {resp2.status_code}): "
                f"{_detail(resp2)}")
        return resp2.json()


def _detail(resp) -> str:
    try:
        data = resp.json()
        return str(data.get("detail", data))[:300]
    except Exception:  # noqa: BLE001 — non-JSON error body
        return getattr(resp, "text", "")[:300]


def _signer_or_none() -> Optional[SolanaSigner]:
    signer = SolanaSigner()
    if not signer.configured:
        return None
    return signer


async def ensure_wallet_credentials() -> Optional[str]:
    """Startup bootstrap. Returns a human-readable status line, or None when
    wallet auth does not apply (explicit GT_API_KEY, or no payer key).

    Order: explicit GT_API_KEY always wins; otherwise a stored credential for
    (GT_API_URL, pubkey) is reused; otherwise a fresh key is minted via
    challenge/verify and persisted 0600.
    """
    if os.getenv("GT_API_KEY"):
        return None
    signer = _signer_or_none()
    if signer is None:
        return None
    api_url = _api_url()

    stored = load_stored_api_key(api_url, signer.payer_pubkey)
    if stored:
        Config.API_KEY = stored
        return (f"wallet auth: using stored API key for wallet "
                f"{signer.payer_pubkey[:8]}… ({credentials_path()}); if it was "
                "rotated elsewhere, a 401 will trigger one automatic re-auth")

    data = await _challenge_and_verify(signer, api_url)
    api_key = data.get("api_key")
    if not api_key:
        raise WalletAuthError("wallet-auth verify succeeded but returned no api_key.")
    Config.API_KEY = api_key
    agent_name = (data.get("agent") or {}).get("name") or "unknown-agent"
    store_api_key(api_url, signer.payer_pubkey, api_key, agent_name)
    action = "provisioned new agent" if data.get("created") else "rotated API key for agent"
    return (f"authenticated as {agent_name} via wallet {signer.payer_pubkey[:8]}… "
            f"({action}; key stored 0600 at {credentials_path()})")


async def mint_fresh_credentials() -> Optional[str]:
    """Force a fresh challenge/verify (key ROTATION). Used by the client's one-shot
    401 re-auth. Returns the new API key, or None when wallet auth does not apply."""
    if not wallet_auth_available():
        return None
    signer = _signer_or_none()
    if signer is None:
        return None
    api_url = _api_url()
    data = await _challenge_and_verify(signer, api_url)
    api_key = data.get("api_key")
    if not api_key:
        raise WalletAuthError("wallet-auth verify succeeded but returned no api_key.")
    Config.API_KEY = api_key
    agent_name = (data.get("agent") or {}).get("name")
    store_api_key(api_url, signer.payer_pubkey, api_key, agent_name)
    print(f"groundtruther-mcp: API key was rejected (rotated elsewhere?) — re-authenticated "
          f"via wallet as {agent_name or 'agent'} and stored the fresh key.", file=sys.stderr)
    return api_key
