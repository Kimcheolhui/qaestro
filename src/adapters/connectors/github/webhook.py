"""Webhook signature verification.

GitHub signs webhook deliveries with HMAC-SHA256 over the **raw** request body
using the shared webhook secret, sending the digest as
``X-Hub-Signature-256: sha256=<hex>``. Verification MUST use the raw bytes
exactly as received — re-encoding parsed JSON would change byte ordering and
produce a different digest.
"""

from __future__ import annotations

import hashlib
import hmac

_PREFIX = "sha256="


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Return ``True`` iff *signature_header* matches HMAC-SHA256(*secret*, *body*).

    Args:
        secret: Shared secret configured in the GitHub webhook settings.
        body: Raw request body bytes (do **not** pass parsed JSON — the byte
            representation must match what GitHub signed).
        signature_header: Value of the ``X-Hub-Signature-256`` header
            (``"sha256=<hex>"`` form). ``None`` or malformed values return
            ``False``.

    The comparison uses :func:`hmac.compare_digest` to avoid leaking timing
    information about how many leading bytes matched.
    """
    if not secret or not signature_header:
        return False
    if not signature_header.startswith(_PREFIX):
        return False

    provided_hex = signature_header[len(_PREFIX) :].strip()
    expected_hex = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    # compare_digest is constant-time on equal-length inputs; differing
    # lengths short-circuit but that's fine — the hex output is always 64
    # chars, so a length mismatch implies a malformed header.
    return hmac.compare_digest(provided_hex, expected_hex)
