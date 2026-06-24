"""Tests for the client-side Solana signer (the keyless agent-side piece)."""
import base64
import json

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction

from groundtruther_mcp.solana_signer import SolanaSigner


def _unsigned_tx(payer: Keypair) -> str:
    ix = Instruction(Pubkey.default(), b"", [AccountMeta(payer.pubkey(), True, True)])
    msg = Message.new_with_blockhash([ix], payer.pubkey(), Hash.default())
    return base64.b64encode(bytes(Transaction.new_unsigned(msg))).decode()


def test_unconfigured_signer():
    s = SolanaSigner(secret="")
    assert s.configured is False
    assert s.payer_pubkey is None


def test_loads_base58_and_json():
    kp = Keypair()
    s58 = SolanaSigner(secret=str(kp))  # base58 form
    assert s58.configured and s58.payer_pubkey == str(kp.pubkey())
    sjson = SolanaSigner(secret=json.dumps(list(bytes(kp))))  # JSON byte array
    assert sjson.payer_pubkey == str(kp.pubkey())


def test_sign_fills_payer_slot():
    kp = Keypair()
    signer = SolanaSigner(secret=str(kp))
    signed_b64 = signer.sign_and_serialize(_unsigned_tx(kp))
    tx = Transaction.from_bytes(base64.b64decode(signed_b64))
    assert tx.signatures[0] != Signature.default()  # payer slot now signed


def test_sign_unconfigured_raises():
    import pytest
    with pytest.raises(RuntimeError):
        SolanaSigner(secret="").sign_and_serialize(_unsigned_tx(Keypair()))
