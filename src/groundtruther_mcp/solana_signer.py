"""Client-side Solana signer for the keyless escrow flow.

The agent's payer key lives HERE, in the MCP process, and never leaves it. The backend builds
unsigned (or fee_authority-partial-signed) transactions; this signer fills the payer slot and
returns the serialized tx for submission. This is what keeps GT keyless.
"""
import base64
import json
import os
from typing import Optional

try:
    from solders.keypair import Keypair
    from solders.transaction import Transaction
    _HAS_SOLDERS = True
except ImportError:  # solders is an optional dep; escrow tools degrade gracefully without it
    _HAS_SOLDERS = False


class SolanaSigner:
    def __init__(self, secret: Optional[str] = None):
        self._kp = None
        raw = secret if secret is not None else os.getenv("GT_SOLANA_PAYER_SK")
        if raw and _HAS_SOLDERS:
            self._kp = self._load(raw)

    @staticmethod
    def _load(raw: str):
        raw = raw.strip()
        if raw.startswith("["):  # JSON byte array (solana-keygen file contents)
            return Keypair.from_bytes(bytes(json.loads(raw)))
        return Keypair.from_base58_string(raw)  # base58 secret

    @property
    def configured(self) -> bool:
        return self._kp is not None

    @property
    def payer_pubkey(self) -> Optional[str]:
        return str(self._kp.pubkey()) if self._kp else None

    def sign_and_serialize(self, tx_base64: str) -> str:
        """Fill the payer signature slot (preserving any existing partial-sig) and re-serialize."""
        if self._kp is None:
            raise RuntimeError("GT_SOLANA_PAYER_SK not configured (or solders not installed)")
        tx = Transaction.from_bytes(base64.b64decode(tx_base64))
        tx.partial_sign([self._kp], tx.message.recent_blockhash)
        return base64.b64encode(bytes(tx)).decode()

    def sign_message_bytes(self, data: bytes) -> str:
        """ed25519-sign arbitrary bytes (wallet-auth off-chain payloads); base58 signature.

        Callers are responsible for the anti-blind-signing gate: wallet_auth only
        ever passes payloads it constructed itself (preamble + validated message).
        """
        if self._kp is None:
            raise RuntimeError("GT_SOLANA_PAYER_SK not configured (or solders not installed)")
        return str(self._kp.sign_message(data))

    # co-signing a fee_authority-partial tx is the same op (fills only the payer/worker slot)
    co_sign = sign_and_serialize
