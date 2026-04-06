"""
Gravity Well — Supabase Key Storage

Stores encryption keys and glyphic context keys per-chain.
The server never holds plaintext content-encryption keys (CEKs).
CEKs are encrypted with a key-encryption-key (KEK) derived from the API key.

Architecture:
  API key (user holds)
    → PBKDF2-SHA256 (100,000 iterations, random salt)
    → KEK (key-encryption-key)
    → AES-256-GCM encrypt the chain's CEK
    → Store encrypted CEK + salt + nonce in Supabase
    → On reconstitute: derive KEK from API key, decrypt CEK locally

Tables:
  gw_encryption_keys — per-chain encrypted CEKs
  gw_context_keys    — per-chain glyphic context anchors
"""

import os
import json
import base64
import hashlib
import httpx
from typing import Optional

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))


def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _url(table: str):
    return f"{SUPABASE_URL}/rest/v1/{table}"


# === KEK Derivation ===

def derive_kek(api_key: str, salt: bytes) -> bytes:
    """Derive key-encryption-key from API key using PBKDF2."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        api_key.encode('utf-8'),
        salt,
        iterations=100_000,
        dklen=32,
    )


def encrypt_cek(api_key: str, cek: bytes) -> dict:
    """Encrypt a content-encryption-key with KEK derived from API key."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(16)
    kek = derive_kek(api_key, salt)
    nonce = os.urandom(12)
    encrypted = AESGCM(kek).encrypt(nonce, cek, None)

    return {
        "encrypted_cek": base64.b64encode(encrypted).decode(),
        "cek_nonce": base64.b64encode(nonce).decode(),
        "cek_salt": base64.b64encode(salt).decode(),
    }


def decrypt_cek(api_key: str, encrypted_cek: str, cek_nonce: str, cek_salt: str) -> bytes:
    """Decrypt a content-encryption-key using KEK derived from API key."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = base64.b64decode(cek_salt)
    kek = derive_kek(api_key, salt)
    nonce = base64.b64decode(cek_nonce)
    ciphertext = base64.b64decode(encrypted_cek)

    return AESGCM(kek).decrypt(nonce, ciphertext, None)


# === Encryption Key Storage ===

async def store_encryption_key(chain_id: str, api_key: str, cek: bytes) -> bool:
    """
    Encrypt and store a content-encryption-key for a chain.
    The CEK is encrypted with a KEK derived from the API key.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False

    encrypted = encrypt_cek(api_key, cek)

    async with httpx.AsyncClient(timeout=15) as client:
        # Upsert (insert or update)
        r = await client.post(
            _url("gw_encryption_keys"),
            headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=representation"},
            json={
                "chain_id": chain_id,
                "encrypted_cek": encrypted["encrypted_cek"],
                "cek_nonce": encrypted["cek_nonce"],
                "cek_salt": encrypted["cek_salt"],
            },
        )
        return r.status_code < 300


async def retrieve_encryption_key(chain_id: str, api_key: str) -> Optional[bytes]:
    """
    Retrieve and decrypt the content-encryption-key for a chain.
    Returns None if not found or decryption fails.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            _url("gw_encryption_keys") + f"?chain_id=eq.{chain_id}&select=*",
            headers=_headers(),
        )
        if r.status_code != 200:
            return None

        rows = r.json()
        if not rows:
            return None

        row = rows[0]
        try:
            return decrypt_cek(
                api_key,
                row["encrypted_cek"],
                row["cek_nonce"],
                row["cek_salt"],
            )
        except Exception:
            return None


# === Context Key Storage ===

async def store_context_key(chain_id: str, context_data: dict, deposit_version: int = 0) -> bool:
    """Store glyphic context anchors for a chain."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            _url("gw_context_keys"),
            headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=representation"},
            json={
                "chain_id": chain_id,
                "context_data": context_data,
                "deposit_version": deposit_version,
            },
        )
        return r.status_code < 300


async def retrieve_context_key(chain_id: str) -> Optional[dict]:
    """Retrieve glyphic context anchors for a chain."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            _url("gw_context_keys") + f"?chain_id=eq.{chain_id}&select=*",
            headers=_headers(),
        )
        if r.status_code != 200:
            return None

        rows = r.json()
        if not rows:
            return None

        return rows[0].get("context_data")
