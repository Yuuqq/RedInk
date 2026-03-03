"""
URL normalization helpers.

This project commonly accepts OpenAI-compatible `base_url` values with or without
the trailing `/v1`. Using `str.rstrip('/v1')` is incorrect for suffix removal
because `rstrip()` removes *any* of the specified characters, which can corrupt
URLs like `/v11`.
"""

from __future__ import annotations


def normalize_openai_base_url(base_url: str | None, default: str | None = None) -> str:
    """
    Normalize an OpenAI-compatible base URL.

    - Strips surrounding whitespace
    - Removes trailing slashes
    - Removes exactly one trailing `/v1` (not `/v11`)

    If `base_url` is empty/None after stripping, returns a normalized `default`
    when provided; otherwise returns an empty string.
    """

    base = (base_url or "").strip()
    if not base and default is not None:
        base = str(default).strip()

    base = base.rstrip("/")
    if base.endswith("/v1"):
        base = base.removesuffix("/v1").rstrip("/")

    return base

