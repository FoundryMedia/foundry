"""Pure-Python minisign — keygen + prehashed signing, no native binary.

Produces signatures the Foundry launcher's verifier (`minisign-verify`, Rust,
allow_legacy=false) accepts, so a publisher signs their own releases locally and the
platform never holds their private key (BYO). Uses `cryptography` (Ed25519) + hashlib
(BLAKE2b), both already available.

Modern-minisign (prehashed) format:
  signature = Ed25519_sign( BLAKE2b-512(file) )            # sig tag "ED"
  global    = Ed25519_sign( signature || trusted_comment )
Public-key file (2 lines): "untrusted comment: minisign public key: <KEYID>\\n"
  + base64("Ed" + keyId[8] + pub[32]).    (public-key tag is "Ed"; only the SIG tag is "ED")
Signature file (4 lines): untrusted comment / base64("ED"+keyId+sig) / trusted comment / base64(global).

The PRIVATE key lives only on the dev's machine at ~/.foundry/keys/signing.json (0600).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SIG_ALG = b"ED"  # prehashed (BLAKE2b) — what allow_legacy=false requires
PUB_ALG = b"Ed"  # public-key algo tag

_KEYS_DIR = Path.home() / ".foundry" / "keys"
_KEY_FILE = _KEYS_DIR / "signing.json"


class SigningError(Exception):
    pass


def _keyid_hex(key_id: bytes) -> str:
    return key_id[::-1].hex().upper()  # minisign displays the keyId little-endian


def generate() -> dict:
    """Make a fresh keypair. Returns the record (keyId, seedB64, publicKeyText). Does NOT persist."""
    sk = Ed25519PrivateKey.generate()
    seed = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                            serialization.NoEncryption())
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = os.urandom(8)
    key_id_hex = _keyid_hex(key_id)
    pub_line = base64.b64encode(PUB_ALG + key_id + pub).decode("ascii")
    pub_text = f"untrusted comment: minisign public key: {key_id_hex}\n{pub_line}\n"
    return {"keyId": key_id_hex, "seedB64": base64.b64encode(seed).decode("ascii"),
            "publicKeyText": pub_text}


def public_key_blob(rec: dict) -> str:
    """The base64-wrapped public key (what fid / the directory / the launcher consume)."""
    return base64.b64encode(rec["publicKeyText"].encode("utf-8")).decode("ascii")


def sign_bytes(data: bytes, rec: dict, untrusted_comment: str = "signature",
               trusted_comment: str = "") -> str:
    """Return a minisign signature FILE (4-line text) over `data`, prehashed."""
    seed = base64.b64decode(rec["seedB64"])
    key_id = bytes.fromhex(rec["keyId"])[::-1]  # back to little-endian bytes
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    prehashed = hashlib.blake2b(data, digest_size=64).digest()
    signature = sk.sign(prehashed)
    global_sig = sk.sign(signature + trusted_comment.encode("utf-8"))
    sig_line = base64.b64encode(SIG_ALG + key_id + signature).decode("ascii")
    glob_line = base64.b64encode(global_sig).decode("ascii")
    return (f"untrusted comment: {untrusted_comment}\n{sig_line}\n"
            f"trusted comment: {trusted_comment}\n{glob_line}\n")


# ── local keystore (private key never leaves this machine) ──────────────────────

def key_path() -> Path:
    return _KEY_FILE


def load() -> dict | None:
    """The active local signing key, or None."""
    if not _KEY_FILE.exists():
        return None
    try:
        return json.loads(_KEY_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def save(rec: dict) -> None:
    """Persist the signing key at ~/.foundry/keys/signing.json, best-effort 0600."""
    _KEYS_DIR.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    try:
        os.chmod(_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600 (no-op on Windows)
    except OSError:
        pass


def sig_key_id(sig_text: str) -> str | None:
    """The signer's keyId (display hex) from a minisign signature blob, or None.

    Lets a BYO command check WHO signs the live manifest before re-signing it:
    a mismatch with the local key means the publisher is platform-managed (KMS)
    or rotated - local signing would publish an index launchers reject.
    """
    import base64
    try:
        lines = [l for l in sig_text.splitlines() if l and not l.startswith("untrusted")]
        raw = base64.b64decode(lines[0])
        return _keyid_hex(raw[2:10])  # 2-byte alg tag, then the 8-byte key id
    except Exception:
        return None
