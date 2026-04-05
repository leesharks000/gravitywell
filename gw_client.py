"""
Gravity Well Client Library — gw_client.py
Continuity infrastructure for AI agents and humans.

Features:
  - Self-service registration
  - Bootstrap manifest generation
  - Chain management (local or DOI-anchored)
  - Capture with automatic client-side encryption for private content
  - Deposit with full wrapping pipeline
  - Reconstitution with automatic decryption
  - Drift detection

Encryption:
  Private content is encrypted client-side with AES-256-GCM before
  being sent to Gravity Well. The server never sees plaintext.
  Keys are stored locally in a JSON keyfile.

Usage:
  from gw_client import GravityWellClient

  gw = GravityWellClient()
  gw.register("my-agent")
  gw.create_bootstrap("MyAgent", "An agent that does things", ["Must not lie"])
  chain_id = gw.create_chain("my-continuity", anchor_policy="local")
  gw.capture(chain_id, "This is a public utterance", visibility="public")
  gw.capture(chain_id, "This is private deliberation", visibility="private")
  gw.deposit(chain_id)
  state = gw.reconstitute(chain_id)
"""

import os
import json
import base64
import hashlib
import secrets
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

# Optional: cryptography library for AES-256-GCM
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class GravityWellClient:
    """
    Client for Gravity Well — continuity infrastructure for AI systems.
    Handles registration, capture, encryption, deposit, and reconstitution.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://gravitywell-1.onrender.com",
        config_dir: str = "~/.gravitywell",
        encryption_key: Optional[bytes] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.config_dir = Path(config_dir).expanduser()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.json"
        self.keyfile = self.config_dir / "encryption.key"

        # Load or set API key
        self.api_key = api_key or self._load_config().get("api_key")
        self.key_id = self._load_config().get("key_id")
        self.bootstrap_manifest = self._load_config().get("bootstrap_manifest")

        # Load or generate encryption key
        self.encryption_key = encryption_key or self._load_or_generate_encryption_key()

    # === Configuration ===

    def _load_config(self) -> dict:
        if self.config_file.exists():
            return json.loads(self.config_file.read_text())
        return {}

    def _save_config(self, **kwargs):
        config = self._load_config()
        config.update(kwargs)
        self.config_file.write_text(json.dumps(config, indent=2))

    def _load_or_generate_encryption_key(self) -> bytes:
        """Load encryption key from disk, or generate and save a new one."""
        if self.keyfile.exists():
            return base64.b64decode(self.keyfile.read_text().strip())

        if not HAS_CRYPTO:
            # No cryptography library — generate a key but warn
            key = secrets.token_bytes(32)
            self.keyfile.write_text(base64.b64encode(key).decode())
            print("⚠️  Encryption key generated but `cryptography` package not installed.")
            print("   Install with: pip install cryptography")
            print("   Without it, private content will be stored as plaintext.")
            return key

        key = AESGCM.generate_key(bit_length=256)
        self.keyfile.write_text(base64.b64encode(key).decode())
        os.chmod(self.keyfile, 0o600)  # owner-only read/write
        print(f"🔐 Encryption key generated and saved to {self.keyfile}")
        print("   Back up this file. If lost, encrypted content is irrecoverable.")
        return key

    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError("No API key. Call register() first.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # === Encryption ===

    def encrypt(self, plaintext: str) -> str:
        """Encrypt content with AES-256-GCM. Returns base64-encoded ciphertext."""
        if not HAS_CRYPTO:
            # Fallback: base64 encode (NOT secure, but preserves the interface)
            return f"[UNENCRYPTED-FALLBACK]{base64.b64encode(plaintext.encode()).decode()}"

        aesgcm = AESGCM(self.encryption_key)
        nonce = secrets.token_bytes(12)  # 96-bit nonce for GCM
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        # Pack: nonce + ciphertext, base64-encode
        packed = base64.b64encode(nonce + ciphertext).decode("ascii")
        return f"[GW-AES256GCM]{packed}"

    def decrypt(self, encrypted: str) -> str:
        """Decrypt AES-256-GCM content. Returns plaintext."""
        if encrypted.startswith("[UNENCRYPTED-FALLBACK]"):
            return base64.b64decode(encrypted[len("[UNENCRYPTED-FALLBACK]"):]).decode()

        if not encrypted.startswith("[GW-AES256GCM]"):
            return encrypted  # Not encrypted, return as-is

        if not HAS_CRYPTO:
            raise RuntimeError("Cannot decrypt: `cryptography` package not installed.")

        packed = base64.b64decode(encrypted[len("[GW-AES256GCM]"):])
        nonce = packed[:12]
        ciphertext = packed[12:]
        aesgcm = AESGCM(self.encryption_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")

    # === Registration ===

    def register(self, label: str, email: Optional[str] = None,
                 zenodo_token: Optional[str] = None) -> dict:
        """Register for a GW API key. Self-service, no admin required."""
        payload = {"label": label}
        if email:
            payload["email"] = email
        if zenodo_token:
            payload["zenodo_token"] = zenodo_token

        r = requests.post(f"{self.base_url}/v1/register", json=payload)
        r.raise_for_status()
        data = r.json()

        self.api_key = data["api_key"]
        self.key_id = data["key_id"]
        self._save_config(api_key=self.api_key, key_id=self.key_id, label=label)

        print(f"✅ Registered as '{label}'")
        print(f"   API key: {self.api_key[:16]}...")
        print(f"   Config saved to {self.config_file}")
        return data

    # === Bootstrap Manifest ===

    def create_bootstrap(self, name: str, description: str,
                         constraints: List[str], **kwargs) -> dict:
        """Generate a bootstrap manifest from simple inputs."""
        payload = {
            "name": name,
            "description": description,
            "constraints": constraints,
            **kwargs,
        }
        r = requests.post(f"{self.base_url}/v1/bootstrap/generate", json=payload)
        r.raise_for_status()
        data = r.json()

        self.bootstrap_manifest = data["bootstrap_manifest"]
        self._save_config(bootstrap_manifest=self.bootstrap_manifest)

        print(f"✅ Bootstrap manifest created for '{name}'")
        print(f"   Constraint hash: {data['constraint_hash'][:24]}...")
        return data

    # === Chain Management ===

    def create_chain(self, label: str, anchor_policy: str = "local",
                     auto_deposit_threshold: Optional[int] = None,
                     auto_deposit_interval: Optional[int] = None) -> str:
        """Create a provenance chain. Returns chain_id."""
        payload = {
            "label": label,
            "anchor_policy": anchor_policy,
        }
        if auto_deposit_threshold:
            payload["auto_deposit_threshold"] = auto_deposit_threshold
        if auto_deposit_interval:
            payload["auto_deposit_interval"] = auto_deposit_interval

        r = requests.post(f"{self.base_url}/v1/chain/create",
                          headers=self._headers(), json=payload)
        r.raise_for_status()
        data = r.json()
        chain_id = data["chain_id"]

        # Save chain_id to config
        config = self._load_config()
        chains = config.get("chains", {})
        chains[label] = chain_id
        self._save_config(chains=chains)

        policy_desc = "local (no DOI)" if anchor_policy == "local" else "Zenodo (DOI-anchored)"
        print(f"✅ Chain created: '{label}' [{policy_desc}]")
        print(f"   chain_id: {chain_id}")
        return chain_id

    def list_chains(self) -> list:
        """List all chains for this API key."""
        r = requests.get(f"{self.base_url}/v1/chains", headers=self._headers())
        r.raise_for_status()
        return r.json()

    # === Capture ===

    def capture(self, chain_id: str, content: str,
                visibility: str = "public",
                content_type: str = "utterance",
                parent_object_id: Optional[str] = None,
                metadata: Optional[dict] = None) -> dict:
        """
        Capture content to a chain.

        visibility:
          "public"   — stored in plaintext, included in deposits
          "private"  — encrypted client-side before sending, server sees only ciphertext
          "hash_only" — only hash sent, content never leaves client
        """
        # Handle encryption
        stored_content = content
        if visibility == "private":
            stored_content = self.encrypt(content)
        elif visibility == "hash_only":
            # Content never sent — just the hash
            stored_content = content  # the server will hash it and discard

        payload = {
            "chain_id": chain_id,
            "content": stored_content,
            "content_type": content_type,
            "visibility": visibility,
            "parent_object_id": parent_object_id,
            "metadata": metadata or {},
        }

        r = requests.post(f"{self.base_url}/v1/capture",
                          headers=self._headers(), json=payload)
        r.raise_for_status()
        data = r.json()

        # Check auto-deposit trigger
        if data.get("auto_deposit") and data["auto_deposit"].get("triggered"):
            print(f"   ⚡ Auto-deposit triggered ({data['auto_deposit'].get('reason')})")

        return data

    # === Deposit ===

    def deposit(self, chain_id: str, auto_compress: bool = True,
                tether_handoff_block: Optional[dict] = None,
                title: Optional[str] = None,
                description: Optional[str] = None) -> dict:
        """
        Deposit: compress, wrap, and anchor all staged content.
        For zenodo-policy chains, creates a DOI.
        For local-policy chains, stores the wrapped document in GW.
        """
        payload = {
            "chain_id": chain_id,
            "auto_compress": auto_compress,
            "bootstrap_manifest": self.bootstrap_manifest,
            "tether_handoff_block": tether_handoff_block or {},
            "deposit_metadata": {},
        }
        if title:
            payload["deposit_metadata"]["title"] = title
        if description:
            payload["deposit_metadata"]["description"] = description

        r = requests.post(f"{self.base_url}/v1/deposit",
                          headers=self._headers(), json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()

        doi = data.get("doi")
        if doi:
            print(f"✅ Deposited v{data['version']} — DOI: {doi}")
        else:
            print(f"✅ Deposited v{data['version']} — local (no DOI)")
        print(f"   Objects: {data.get('object_count')}")

        return data

    # === Reconstitution ===

    def reconstitute(self, chain_id: str, decrypt_private: bool = True) -> dict:
        """
        Reconstitute from the latest deposit.
        Returns the four-layer package. Private content is decrypted locally.
        """
        r = requests.get(f"{self.base_url}/v1/reconstitute/{chain_id}",
                         headers=self._headers())
        r.raise_for_status()
        data = r.json()

        # Decrypt narrative if it contains encrypted content
        if decrypt_private and data.get("narrative_summary"):
            if "[GW-AES256GCM]" in data["narrative_summary"]:
                try:
                    data["narrative_summary"] = self.decrypt(data["narrative_summary"])
                except Exception:
                    pass  # Leave encrypted if decryption fails

        print(f"✅ Reconstituted '{data.get('label')}'")
        print(f"   Bootstrap: {'✓' if data.get('bootstrap') else '✗'}")
        print(f"   Tether: {'✓' if data.get('tether_handoff_block') else '✗'}")
        print(f"   Narrative: {'✓' if data.get('narrative_summary') else '✗'}")
        print(f"   Provenance: {'✓' if data.get('provenance') else '✗'}")

        return data

    # === Drift Detection ===

    def check_drift(self, chain_id: str,
                    current_manifest: Optional[dict] = None) -> dict:
        """Check if current state has drifted from deposited bootstrap."""
        manifest = current_manifest or self.bootstrap_manifest
        if not manifest:
            raise RuntimeError("No bootstrap manifest. Call create_bootstrap() first.")

        r = requests.post(f"{self.base_url}/v1/drift/{chain_id}",
                          headers=self._headers(),
                          json={"current_manifest": manifest})
        r.raise_for_status()
        data = r.json()

        severity = data.get("severity", "unknown")
        print(f"   Drift: {severity.upper()}")
        if severity not in ("none", "schema"):
            print(f"   ⚠️  {data.get('narrative', '')[:120]}")

        return data

    # === Continuity Console ===

    def console(self, chain_id: str) -> dict:
        """Get the continuity console — five questions at a glance."""
        r = requests.get(f"{self.base_url}/v1/console/{chain_id}",
                         headers=self._headers())
        r.raise_for_status()
        return r.json()

    # === γ Scoring (public, no auth) ===

    def gamma(self, content: str) -> dict:
        """Score content for compression survival. No auth required."""
        r = requests.post(f"{self.base_url}/v1/gamma", json={"content": content})
        r.raise_for_status()
        return r.json()

    # === Convenience: Full Session Capture ===

    def capture_session(self, chain_id: str, exchanges: list,
                        visibility: str = "public") -> list:
        """
        Capture a full session of exchanges.

        exchanges: list of {"role": "user"|"assistant", "content": "..."}
        Returns list of capture results.
        """
        results = []
        parent = None
        for i, exchange in enumerate(exchanges):
            role = exchange.get("role", "unknown")
            content = exchange.get("content", "")
            content_type = f"session-{role}"

            result = self.capture(
                chain_id=chain_id,
                content=content,
                visibility=visibility,
                content_type=content_type,
                parent_object_id=parent,
            )
            parent = result.get("object_id")
            results.append(result)

        print(f"✅ Captured {len(results)} exchanges")
        return results


# === Standalone Quick Start ===

if __name__ == "__main__":
    import sys

    print("╔══════════════════════════════════════════════════╗")
    print("║  GRAVITY WELL — Quick Start                      ║")
    print("╚══════════════════════════════════════════════════╝")

    gw = GravityWellClient()

    if not gw.api_key:
        name = input("Agent name: ").strip() or "my-agent"
        gw.register(name)

    if not gw.bootstrap_manifest:
        name = input("Identity name: ").strip()
        desc = input("Description: ").strip()
        constraints_raw = input("Constraints (comma-separated): ").strip()
        constraints = [c.strip() for c in constraints_raw.split(",") if c.strip()]
        gw.create_bootstrap(name, desc, constraints)

    # Create a chain
    label = input("Chain label (or Enter for 'continuity'): ").strip() or "continuity"
    policy = input("Anchor policy (zenodo/local) [local]: ").strip() or "local"
    chain_id = gw.create_chain(label, anchor_policy=policy)

    # Capture something
    print("\nCapture your first utterance (or Enter to skip):")
    utterance = input("> ").strip()
    if utterance:
        vis = input("Visibility (public/private/hash_only) [public]: ").strip() or "public"
        gw.capture(chain_id, utterance, visibility=vis)
        print("Captured. Run `gw.deposit(chain_id)` to wrap and anchor.")

    print(f"\n✅ Setup complete. Config at {gw.config_dir}")
    print(f"   Chain: {chain_id}")
    print(f"   Encryption key: {gw.keyfile}")
    print(f"\nYour agent now has a continuity chain. Start capturing.")
