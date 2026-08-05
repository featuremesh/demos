"""
HTTP helpers for the local FeatureQL API server (BatchClient wrapper on :8101).

Shared SSE parsing and three call styles: static JSON, streaming (silent), and live streaming.

All three runners take ``url``, ``payload``, and ``timeout`` — use the full URL including path
(e.g. ``.../8101/sltest`` vs ``.../8101/sltest_stream``).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import requests

DEFAULT_API_BASE = "http://host.docker.internal:8101"


def build_test_payload(
    source: str,
    *,
    backend: str = "duckdb",
    halt_on_fail: bool = False,
    force_no_schema: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    """Body for ``POST /sltest`` and ``POST /sltest_stream`` (``source`` = custom SHOW DOCS query)."""
    payload: dict[str, Any] = {
        "backend": backend,
        "source": source,
        "halt_on_fail": halt_on_fail,
        "force_no_schema": force_no_schema,
    }
    payload.update(extra)
    return payload


def iter_test_stream_events(
    url: str,
    payload: dict[str, Any],
    timeout: int | float = 600,
    *,
    verify: bool = False,
) -> Iterator[dict[str, Any]]:
    """Yield each SSE ``data:`` JSON object from a ``POST /sltest_stream`` (chunk-safe)."""
    with requests.post(
        url,
        json=payload,
        stream=True,
        timeout=timeout,
        verify=verify,
    ) as r:
        r.raise_for_status()
        buf = ""
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            if not chunk:
                continue
            buf += chunk
            while "\n\n" in buf:
                raw_event, buf = buf.split("\n\n", 1)
                for event_line in raw_event.split("\n"):
                    line = event_line.strip()
                    if line.startswith("data:"):
                        yield json.loads(line[5:].strip())


def _default_live_handler(ev: dict[str, Any]) -> None:
    """Print one short line per event (Notebook-friendly with ``flush=True``)."""
    t = ev.get("type")
    if t == "snippet":
        print(t, ev.get("name"), ev.get("index"), flush=True)
    elif t == "fetch_done":
        print(t, ev.get("total_snippets"), "snippets", flush=True)
    elif t == "fetch_start":
        print(t, flush=True)
    elif t == "session":
        print(t, ev.get("backend"), flush=True)
    else:
        print(t, flush=True)


def run_static(
    url: str,
    payload: dict[str, Any],
    timeout: int | float = 600,
    *,
    verify: bool = False,
) -> dict[str, Any]:
    """``POST`` to a Batch API URL — return the JSON body (raises on non-2xx)."""
    response = requests.post(url, json=payload, timeout=timeout, verify=verify)
    response.raise_for_status()
    return response.json()


def run_tests_streaming(
    url: str,
    payload: dict[str, Any],
    timeout: int | float = 600,
    *,
    verify: bool = False,
) -> dict[str, Any]:
    """``POST`` to ``/sltest_stream`` URL — consume SSE in memory; return the ``complete`` summary."""
    for ev in iter_test_stream_events(url, payload, timeout, verify=verify):
        if ev.get("type") == "complete":
            return ev["result"]
    raise RuntimeError("no complete event in SSE stream")


def run_tests_streaming_live(
    url: str,
    payload: dict[str, Any],
    timeout: int | float = 600,
    *,
    verify: bool = False,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """``POST`` to ``/sltest_stream`` — call ``on_event`` for each event (default: print); return summary."""
    handler = on_event or _default_live_handler
    for ev in iter_test_stream_events(url, payload, timeout, verify=verify):
        handler(ev)
        if ev.get("type") == "complete":
            return ev["result"]
    raise RuntimeError("no complete event in SSE stream")
