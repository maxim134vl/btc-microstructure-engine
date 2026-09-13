"""Binance SIGNED payload helpers. Secrets never appear in returned strings."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from typing import Any

from .constants import RECV_WINDOW_MS


class SigningError(ValueError):
    """Cannot sign the request."""


def encode_params(params: Mapping[str, Any]) -> str:
    """Stable query string. `signature` is never included here."""
    parts: list[str] = []
    for key in sorted(params):
        if key == "signature":
            continue
        value = params[key]
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return "&".join(parts)


def hmac_sha256_hex(secret: str, payload: str) -> str:
    if not secret:
        raise SigningError("hmac secret missing")
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def ed25519_signature_b64(private_key_pem: bytes, payload: str) -> str:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as exc:  # pragma: no cover
        raise SigningError("cryptography is required for Ed25519 keys") from exc
    if not private_key_pem:
        raise SigningError("ed25519 private key missing")
    key = load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningError("private key is not Ed25519")
    signed = key.sign(payload.encode("ascii"))
    return base64.b64encode(signed).decode("ascii")


def signed_query(
    params: Mapping[str, Any],
    *,
    timestamp_ms: int,
    recv_window_ms: int = RECV_WINDOW_MS,
    hmac_secret: str | None = None,
    ed25519_pem: bytes | None = None,
) -> str:
    payload_params = dict(params)
    payload_params["timestamp"] = int(timestamp_ms)
    payload_params["recvWindow"] = int(recv_window_ms)
    total = encode_params(payload_params)
    if ed25519_pem is not None:
        signature = ed25519_signature_b64(ed25519_pem, total)
    elif hmac_secret is not None:
        signature = hmac_sha256_hex(hmac_secret, total)
    else:
        raise SigningError("no signing material")
    return f"{total}&signature={signature}"
