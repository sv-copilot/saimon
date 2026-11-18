#!/usr/bin/env python3
"""Watch every Saimon service and speak when one goes quiet.

The failure this exists for: nine containers reported ``healthy`` for twenty
hours while five of them had no database, search answered every query with an
empty list, and nothing said so. Docker's health check watched the process; this
watches the claim the process makes about itself.

    python scripts/watchdog.py --once            # what cron runs
    python scripts/watchdog.py --once --strict   # exit 1 when anything is wrong

State is kept between runs so a service that has been degraded for a day is
announced once, not every five minutes. Recovery is announced too, because a
silent recovery teaches people to ignore the silence.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SERVICES: tuple[tuple[str, int], ...] = (
    ("search", 8101),
    ("generate", 8102),
    ("export", 8103),
    ("evaluate", 8104),
    ("verify", 8105),
    ("explore", 8106),
    ("api", 8107),
    ("domain", 8108),
    ("crew", 8109),
)

STATE_PATH = Path(os.environ.get("SAIMON_WATCHDOG_STATE", "~/.saimon-watchdog.json")).expanduser()
LOG_PATH = Path(os.environ.get("SAIMON_WATCHDOG_LOG", "~/.saimon-watchdog.log")).expanduser()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("saimon.watchdog")


FAILING_CHECKS = frozenset(
    {"unavailable", "error", "failed", "disconnected", "down", "unreachable", "degraded"}
)


def classify(payload: dict | None, error: str | None = None) -> str:
    """ok, degraded, or down — from what the service says about itself.

    Not every service has a database: export is stateless and evaluate reports
    its model connection. So the rule is "no check may be failing", not "every
    service must have the same check", and a service that reports
    ``status: ok`` beside ``database: unavailable`` is the case this catches.
    """
    if error or payload is None:
        return "down"
    if str(payload.get("status", "")).lower() != "ok":
        return "degraded"
    checks = payload.get("checks") or {}
    for value in checks.values():
        if str(value).lower() in FAILING_CHECKS:
            return "degraded"
    return "ok"


def transitions(previous: dict[str, str], current: dict[str, str]) -> list[tuple[str, str, str]]:
    """(service, from, to) for every state that changed, first run included."""
    changes: list[tuple[str, str, str]] = []
    for service, state in sorted(current.items()):
        before = previous.get(service)
        if before is None and state == "ok":
            continue  # a healthy first observation is not news
        if before != state:
            changes.append((service, before or "unknown", state))
    return changes


def probe(port: int, timeout: float = 6.0) -> tuple[str, str]:
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return "down", str(exc)[:120]
    return classify(payload), ""


def notify(text: str) -> bool:
    """Send to the operator when the credentials are present, else just log."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("SAIMON_ALERT_CHAT_ID", "").strip()
    if not token or not chat:
        return False
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15):
            return True
    except Exception as exc:  # noqa: BLE001 - an alert failure must not hide the finding
        logger.error("alert delivery failed: %s", str(exc)[:120])
        return False


def load_state() -> dict[str, str]:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, str]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="one pass (what cron runs)")
    parser.add_argument("--strict", action="store_true", help="exit 1 when anything is not ok")
    parser.add_argument("--base-port", type=int, default=8101)
    args = parser.parse_args()

    current: dict[str, str] = {}
    detail: dict[str, str] = {}
    for index, (name, port) in enumerate(SERVICES):
        state, error = probe(port + (args.base_port - 8101))
        current[name] = state
        if error:
            detail[name] = error

    previous = load_state()
    changes = transitions(previous, current)
    save_state(current)

    if changes:
        lines = [
            f"{service}: {before} -> {after}" + (f" ({detail[service]})" if service in detail else "")
            for service, before, after in changes
        ]
        message = "Saimon watchdog\n" + "\n".join(lines)
        logger.warning(message.replace("\n", " | "))
        with LOG_PATH.open("a") as handle:
            handle.write(f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}\n")
        notify(message)
    else:
        logger.info("no change: %s", ", ".join(f"{k}={v}" for k, v in sorted(current.items())))

    if args.strict and any(state != "ok" for state in current.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
