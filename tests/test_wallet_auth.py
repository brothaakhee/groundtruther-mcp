"""Wallet-native auto-auth: anti-blind-signing validation, credential flow, 401 re-auth.

The client NEVER signs raw server bytes: it parses and validates the SIWS
challenge (expected domain == configured GT host, address == own pubkey,
ASCII-only, contains the nonce, not parseable as a transaction), then signs the
Anza off-chain preamble + message that IT constructs itself.
"""
import base64
import json
import os
import stat
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.keypair import Keypair

from groundtruther_mcp import wallet_auth
from groundtruther_mcp.config import Config
from groundtruther_mcp.solana_signer import SolanaSigner
from groundtruther_mcp.wallet_auth import (
    WalletAuthError,
    ensure_wallet_credentials,
    expected_domain,
    mint_fresh_credentials,
    offchain_message_bytes,
    validate_challenge,
)

API_URL = "http://localhost:8001/api/v1"
DOMAIN = "localhost:8001"


@pytest.fixture
def kp():
    return Keypair()


@pytest.fixture(autouse=True)
def wallet_env(tmp_path, kp):
    """Wallet-native env: payer key, NO GT_API_KEY, isolated credentials file."""
    os.environ.pop("GT_API_KEY", None)
    os.environ["GT_API_URL"] = API_URL
    os.environ["GT_SOLANA_PAYER_SK"] = json.dumps(list(bytes(kp)))
    os.environ["GT_CREDENTIALS_PATH"] = str(tmp_path / "credentials.json")
    saved_key = Config.API_KEY
    Config.API_KEY = None
    yield
    Config.API_KEY = saved_key
    for var in ("GT_API_KEY", "GT_API_URL", "GT_SOLANA_PAYER_SK", "GT_CREDENTIALS_PATH"):
        os.environ.pop(var, None)


def _message(domain=DOMAIN, address=None, nonce="test-nonce-123", kp_=None):
    address = address or str((kp_ or Keypair()).pubkey())
    return (
        f"{domain} wants you to sign in with your Solana account:\n"
        f"{address}\n\n"
        "Sign in to GroundTruther to provision or rotate your agent API key. "
        "This request will not trigger a blockchain transaction or cost any fees.\n\n"
        f"Nonce: {nonce}\n"
        "Issued At: 2026-09-01T00:00:00Z\n"
        "Expiration Time: 2026-09-01T00:05:00Z"
    )


# ---------------------------------------------------------------------------
# anti-blind-signing validation
# ---------------------------------------------------------------------------

class TestValidateChallenge:
    def test_valid_challenge_passes(self, kp):
        msg = _message(address=str(kp.pubkey()))
        validate_challenge(msg, "test-nonce-123", DOMAIN, str(kp.pubkey()))

    def test_domain_mismatch_rejected(self, kp):
        msg = _message(domain="evil.example.com", address=str(kp.pubkey()))
        with pytest.raises(WalletAuthError, match="domain"):
            validate_challenge(msg, "test-nonce-123", DOMAIN, str(kp.pubkey()))

    def test_address_mismatch_rejected(self, kp):
        msg = _message(address=str(Keypair().pubkey()))
        with pytest.raises(WalletAuthError, match="address|pubkey"):
            validate_challenge(msg, "test-nonce-123", DOMAIN, str(kp.pubkey()))

    def test_missing_nonce_rejected(self, kp):
        msg = _message(address=str(kp.pubkey()), nonce="some-other-nonce")
        with pytest.raises(WalletAuthError, match="[Nn]once"):
            validate_challenge(msg, "test-nonce-123", DOMAIN, str(kp.pubkey()))

    def test_non_ascii_rejected(self, kp):
        msg = _message(address=str(kp.pubkey())) + " ‮"
        with pytest.raises(WalletAuthError, match="ASCII"):
            validate_challenge(msg, "test-nonce-123", DOMAIN, str(kp.pubkey()))

    def test_empty_message_rejected(self, kp):
        with pytest.raises(WalletAuthError):
            validate_challenge("", "test-nonce-123", DOMAIN, str(kp.pubkey()))

    def test_transaction_shaped_challenge_rejected(self, kp):
        """A base64-encoded transaction masquerading as a challenge must be refused."""
        from solders.hash import Hash
        from solders.message import Message
        from solders.system_program import TransferParams, transfer
        from solders.transaction import Transaction

        ix = transfer(TransferParams(
            from_pubkey=kp.pubkey(), to_pubkey=Keypair().pubkey(), lamports=1))
        tx = Transaction.new_unsigned(Message.new_with_blockhash(
            [ix], kp.pubkey(), Hash.default()))
        tx_b64 = base64.b64encode(bytes(tx)).decode()
        assert wallet_auth._parses_as_transaction(tx_b64)
        with pytest.raises(WalletAuthError):
            validate_challenge(tx_b64, "test-nonce-123", DOMAIN, str(kp.pubkey()))

    def test_normal_challenge_is_not_transaction_shaped(self, kp):
        assert not wallet_auth._parses_as_transaction(_message(address=str(kp.pubkey())))


class TestOffchainLayout:
    def test_exact_anza_byte_layout(self):
        msg = "hello offchain"
        payload = offchain_message_bytes(msg)
        assert payload[:16] == b"\xffsolana offchain"
        assert payload[16] == 0  # header version
        assert payload[17] == 0  # format: restricted ASCII
        assert payload[18:20] == len(msg).to_bytes(2, "little")
        assert payload[20:] == msg.encode("ascii")

    def test_preamble_starts_with_0xff(self):
        # 0xff can never begin a valid transaction (message header/signature count).
        assert offchain_message_bytes("x")[0] == 0xFF

    def test_expected_domain_is_api_host_and_port(self):
        assert expected_domain(API_URL) == DOMAIN
        assert expected_domain("https://api.groundtruther.io/api/v1") == "api.groundtruther.io"


# ---------------------------------------------------------------------------
# auto-auth flow (mocked httpx)
# ---------------------------------------------------------------------------

def _mock_http_seq(method, responses):
    patcher = patch("httpx.AsyncClient")
    mock_client_class = patcher.start()
    mock_client = AsyncMock()
    side_effects = []
    for item in responses:
        if isinstance(item, Exception):
            side_effects.append(item)
            continue
        status_code, data = item
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = data
        side_effects.append(mock_response)
    getattr(mock_client, method).side_effect = side_effects
    mock_client_class.return_value.__aenter__.return_value = mock_client
    return patcher, mock_client


def _challenge_body(kp, nonce="nonce-abc"):
    return {
        "message": _message(address=str(kp.pubkey()), nonce=nonce),
        "nonce": nonce,
        "domain": DOMAIN,
        "address": str(kp.pubkey()),
    }


def _verify_body(created=True):
    # Mirrors the live contract: the API key is THE credential — no JWT.
    return {
        "api_key": "gt_sk_minted_key_1",
        "user_id": "u-1",
        "agent": {"id": "a-1", "name": "agent-AbCdEfGh", "escrow_enabled": True,
                  "default_payer_pubkey": "x"},
        "created": created,
        "rotated": not created,
    }


class TestEnsureWalletCredentials:
    async def test_happy_path_mints_and_persists_key(self, kp, tmp_path):
        patcher, mock_client = _mock_http_seq(
            "post", [(200, _challenge_body(kp)), (200, _verify_body())])
        try:
            note = await ensure_wallet_credentials()
        finally:
            patcher.stop()
        assert note is not None
        assert "agent-AbCdEfGh" in note
        assert Config.API_KEY == "gt_sk_minted_key_1"
        # Two POSTs: challenge then verify, with the signed off-chain payload.
        assert mock_client.post.call_count == 2
        verify_call = mock_client.post.call_args_list[1]
        assert verify_call.kwargs["json"]["pubkey"] == str(kp.pubkey())
        assert verify_call.kwargs["json"]["signature"]
        # Credential persisted, keyed by api_url + pubkey, file mode 0600.
        cred_file = tmp_path / "credentials.json"
        assert cred_file.exists()
        mode = stat.S_IMODE(cred_file.stat().st_mode)
        assert mode == 0o600
        stored = json.loads(cred_file.read_text())
        entry = stored[f"{API_URL}|{kp.pubkey()}"]
        assert entry["api_key"] == "gt_sk_minted_key_1"

    async def test_tampered_challenge_aborts_before_any_signature(self, kp):
        evil = _challenge_body(kp)
        evil["message"] = _message(domain="evil.example.com", address=str(kp.pubkey()),
                                   nonce="nonce-abc")
        patcher, mock_client = _mock_http_seq("post", [(200, evil)])
        try:
            with pytest.raises(WalletAuthError, match="domain"):
                await ensure_wallet_credentials()
        finally:
            patcher.stop()
        # verify was never called — nothing was signed or sent.
        assert mock_client.post.call_count == 1
        assert Config.API_KEY is None

    async def test_stored_credential_is_reused_without_network(self, kp, tmp_path):
        wallet_auth.store_api_key(API_URL, str(kp.pubkey()), "gt_sk_stored", "agent-X")
        patcher, mock_client = _mock_http_seq("post", [])
        try:
            note = await ensure_wallet_credentials()
        finally:
            patcher.stop()
        assert mock_client.post.call_count == 0
        assert Config.API_KEY == "gt_sk_stored"
        assert note is not None

    async def test_env_api_key_wins_no_wallet_auth(self, kp):
        os.environ["GT_API_KEY"] = "gt_sk_env_key"
        patcher, mock_client = _mock_http_seq("post", [])
        try:
            note = await ensure_wallet_credentials()
        finally:
            patcher.stop()
        assert note is None
        assert mock_client.post.call_count == 0

    async def test_no_payer_key_no_wallet_auth(self):
        os.environ.pop("GT_SOLANA_PAYER_SK", None)
        note = await ensure_wallet_credentials()
        assert note is None

    async def test_challenge_http_error_is_loud(self, kp):
        patcher, _ = _mock_http_seq("post", [(500, {"detail": "boom"})])
        try:
            with pytest.raises(WalletAuthError, match="challenge"):
                await ensure_wallet_credentials()
        finally:
            patcher.stop()

    async def test_verify_http_error_is_loud(self, kp):
        patcher, _ = _mock_http_seq(
            "post", [(200, _challenge_body(kp)), (409, {"detail": "worker wallet"})])
        try:
            with pytest.raises(WalletAuthError, match="verify"):
                await ensure_wallet_credentials()
        finally:
            patcher.stop()

    async def test_mint_fresh_credentials_rotates_and_restores(self, kp, tmp_path):
        wallet_auth.store_api_key(API_URL, str(kp.pubkey()), "gt_sk_old", "agent-X")
        body = _verify_body(created=False)
        body["api_key"] = "gt_sk_rotated"
        patcher, _ = _mock_http_seq("post", [(200, _challenge_body(kp)), (200, body)])
        try:
            new_key = await mint_fresh_credentials()
        finally:
            patcher.stop()
        assert new_key == "gt_sk_rotated"
        assert Config.API_KEY == "gt_sk_rotated"
        stored = json.loads((tmp_path / "credentials.json").read_text())
        assert stored[f"{API_URL}|{kp.pubkey()}"]["api_key"] == "gt_sk_rotated"


# ---------------------------------------------------------------------------
# 401 re-auth in APIClient
# ---------------------------------------------------------------------------

class TestClient401Reauth:
    async def test_401_triggers_one_reauth_and_retry(self, kp):
        from groundtruther_mcp.client import APIClient

        Config.API_KEY = "gt_sk_revoked"
        patcher, mock_client = _mock_http_seq("get", [(401, {"detail": "Invalid API key."}),
                                                      (200, {"ok": True})])

        async def fake_mint():
            Config.API_KEY = "gt_sk_fresh"
            return "gt_sk_fresh"

        try:
            with patch.object(wallet_auth, "mint_fresh_credentials", side_effect=fake_mint):
                resp = await APIClient().get("/tasks/")
        finally:
            patcher.stop()
        assert resp.status_code == 200
        assert mock_client.get.call_count == 2
        retry_headers = mock_client.get.call_args_list[1].kwargs["headers"]
        assert retry_headers["Authorization"] == "Bearer gt_sk_fresh"

    async def test_second_401_fails_loudly_without_loop(self, kp):
        from groundtruther_mcp.client import APIClient

        Config.API_KEY = "gt_sk_revoked"
        patcher, mock_client = _mock_http_seq(
            "get", [(401, {"detail": "no"}), (401, {"detail": "still no"})])

        async def fake_mint():
            Config.API_KEY = "gt_sk_fresh"
            return "gt_sk_fresh"

        try:
            with patch.object(wallet_auth, "mint_fresh_credentials", side_effect=fake_mint):
                resp = await APIClient().get("/tasks/")
        finally:
            patcher.stop()
        assert resp.status_code == 401
        assert mock_client.get.call_count == 2  # exactly one retry, no loop

    async def test_explicit_env_api_key_never_reauths(self, kp):
        from groundtruther_mcp.client import APIClient

        os.environ["GT_API_KEY"] = "gt_sk_pinned"
        Config.API_KEY = "gt_sk_pinned"
        patcher, mock_client = _mock_http_seq("get", [(401, {"detail": "no"})])
        mint = AsyncMock()
        try:
            with patch.object(wallet_auth, "mint_fresh_credentials", mint):
                resp = await APIClient().get("/tasks/")
        finally:
            patcher.stop()
        assert resp.status_code == 401
        mint.assert_not_called()
        assert mock_client.get.call_count == 1

    async def test_post_401_also_reauths(self, kp):
        from groundtruther_mcp.client import APIClient

        Config.API_KEY = "gt_sk_revoked"
        patcher, mock_client = _mock_http_seq("post", [(401, {"detail": "no"}),
                                                       (201, {"id": "t"})])

        async def fake_mint():
            Config.API_KEY = "gt_sk_fresh"
            return "gt_sk_fresh"

        try:
            with patch.object(wallet_auth, "mint_fresh_credentials", side_effect=fake_mint):
                resp = await APIClient().post("/tasks/", data={"x": 1})
        finally:
            patcher.stop()
        assert resp.status_code == 201
        assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# timeout re-auth in APIClient (outsider-e2e F1, client leg)
# ---------------------------------------------------------------------------

class TestClientTimeoutReauth:
    """A request timeout on an auth-carrying call may be a stale-key symptom
    (a server-side auth stall outrunning the client timeout), so wallet mode
    attempts the same one-shot re-auth as a 401 — and any surfaced timeout must
    carry a real message (str(httpx.ReadTimeout()) is empty by default)."""

    async def test_timeout_triggers_one_reauth_and_retry(self, kp):
        import httpx
        from groundtruther_mcp.client import APIClient

        Config.API_KEY = "gt_sk_stale"
        patcher, mock_client = _mock_http_seq(
            "get", [httpx.ReadTimeout(""), (200, {"ok": True})])

        async def fake_mint():
            Config.API_KEY = "gt_sk_fresh"
            return "gt_sk_fresh"

        try:
            with patch.object(wallet_auth, "mint_fresh_credentials", side_effect=fake_mint):
                resp = await APIClient().get("/tasks/")
        finally:
            patcher.stop()
        assert resp.status_code == 200
        assert mock_client.get.call_count == 2
        retry_headers = mock_client.get.call_args_list[1].kwargs["headers"]
        assert retry_headers["Authorization"] == "Bearer gt_sk_fresh"

    async def test_timeout_after_reauth_raises_descriptive_error(self, kp):
        import httpx
        from groundtruther_mcp.client import APIClient

        Config.API_KEY = "gt_sk_stale"
        patcher, mock_client = _mock_http_seq(
            "get", [httpx.ReadTimeout(""), httpx.ReadTimeout("")])

        async def fake_mint():
            Config.API_KEY = "gt_sk_fresh"
            return "gt_sk_fresh"

        try:
            with patch.object(wallet_auth, "mint_fresh_credentials", side_effect=fake_mint):
                with pytest.raises(httpx.TimeoutException) as exc_info:
                    await APIClient().get("/tasks/")
        finally:
            patcher.stop()
        assert mock_client.get.call_count == 2  # exactly one retry, no loop
        msg = str(exc_info.value)
        assert msg  # never the empty "Network error: " again
        assert "timed out" in msg
        assert "GT_HTTP_TIMEOUT" in msg

    async def test_pinned_env_key_timeout_never_reauths_but_message_is_descriptive(self, kp):
        import httpx
        from groundtruther_mcp.client import APIClient

        os.environ["GT_API_KEY"] = "gt_sk_pinned"
        Config.API_KEY = "gt_sk_pinned"
        patcher, mock_client = _mock_http_seq("get", [httpx.ReadTimeout("")])
        mint = AsyncMock()
        try:
            with patch.object(wallet_auth, "mint_fresh_credentials", mint):
                with pytest.raises(httpx.TimeoutException) as exc_info:
                    await APIClient().get("/tasks/")
        finally:
            patcher.stop()
        mint.assert_not_called()
        assert mock_client.get.call_count == 1
        assert "timed out" in str(exc_info.value)

    async def test_unauthenticated_call_timeout_never_reauths(self, kp):
        import httpx
        from groundtruther_mcp.client import APIClient

        patcher, mock_client = _mock_http_seq("get", [httpx.ReadTimeout("")])
        mint = AsyncMock()
        try:
            with patch.object(wallet_auth, "mint_fresh_credentials", mint):
                with pytest.raises(httpx.TimeoutException):
                    await APIClient().get("/public/", use_auth=False)
        finally:
            patcher.stop()
        mint.assert_not_called()
        assert mock_client.get.call_count == 1

    async def test_non_timeout_transport_errors_pass_straight_through(self, kp):
        import httpx
        from groundtruther_mcp.client import APIClient

        Config.API_KEY = "gt_sk_x"
        patcher, mock_client = _mock_http_seq("get", [httpx.ConnectError("refused")])
        mint = AsyncMock()
        try:
            with patch.object(wallet_auth, "mint_fresh_credentials", mint):
                with pytest.raises(httpx.ConnectError):
                    await APIClient().get("/tasks/")
        finally:
            patcher.stop()
        mint.assert_not_called()


# ---------------------------------------------------------------------------
# credential store
# ---------------------------------------------------------------------------

class TestCredentialStore:
    def test_store_and_load_roundtrip(self, kp, tmp_path):
        wallet_auth.store_api_key(API_URL, str(kp.pubkey()), "gt_sk_abc", "agent-1")
        assert wallet_auth.load_stored_api_key(API_URL, str(kp.pubkey())) == "gt_sk_abc"
        # Different URL or pubkey: no hit.
        assert wallet_auth.load_stored_api_key("http://other/api/v1", str(kp.pubkey())) is None
        assert wallet_auth.load_stored_api_key(API_URL, str(Keypair().pubkey())) is None

    def test_store_creates_0600_file_and_0700_dir(self, kp, tmp_path):
        nested = tmp_path / "deep" / "credentials.json"
        os.environ["GT_CREDENTIALS_PATH"] = str(nested)
        wallet_auth.store_api_key(API_URL, str(kp.pubkey()), "gt_sk_abc", "agent-1")
        assert stat.S_IMODE(nested.stat().st_mode) == 0o600
        assert stat.S_IMODE(nested.parent.stat().st_mode) == 0o700

    def test_corrupt_store_treated_as_empty(self, kp, tmp_path):
        (tmp_path / "credentials.json").write_text("{not json")
        assert wallet_auth.load_stored_api_key(API_URL, str(kp.pubkey())) is None
