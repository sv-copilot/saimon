"""download.py — shared full-text download helper for shadow adapters.

Adapters use :func:`download_bytes` to fetch raw bytes with a per-source
size cap and timeout.  Fail-closed: returns None on any error or oversize
response, never raises.
"""

from __future__ import annotations

from typing import Any

from research_shared.fulltext import DEFAULT_FULLTEXT_TIMEOUT, MAX_FULLTEXT_BYTES


async def download_bytes(
    client: Any,
    url: str,
    *,
    max_bytes: int = MAX_FULLTEXT_BYTES,
    timeout: float = DEFAULT_FULLTEXT_TIMEOUT,
) -> bytes | None:
    """GET *url* and return its body, capped at *max_bytes*.  Returns None on
    any failure (network, non-200, or oversize response)."""
    import httpx

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        close_client = True

    try:
        try:
            resp = await client.get(url, timeout=timeout)
        except Exception:  # noqa: BLE001 — network failures fail closed
            return None
        if getattr(resp, "status_code", None) != 200:
            return None
        body = getattr(resp, "content", None)
        if body is None:
            body = await resp.aread()
        data = bytes(body)
        if len(data) > max_bytes:
            return None
        return data
    except Exception:  # noqa: BLE001 — any download error fails closed
        return None
    finally:
        if close_client:
            await client.aclose()
