#!/usr/bin/env python3
"""Fetch open reference articles across five fields for the retrieval corpus.

Project Gutenberg refused connections from this host (503), so the sources are
Wikipedia's plain-text extracts, CC BY-SA 4.0. Each file keeps its attribution
header so a citation can point at the article rather than at the corpus.

    python fetch_reference.py --out ~/reference
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

FIELDS: dict[str, list[str]] = {
    "cooking": [
        "Maillard reaction", "Sous vide", "Sourdough", "Braising", "Emulsion",
        "Knife sharpening", "Mise en place", "Stock (food)",
        "Fermentation in food processing", "Smoking (cooking)",
    ],
    "outdoors": [
        "Crop rotation", "Companion planting", "Soil pH", "Compost",
        "Raised-bed gardening", "Archery", "Fly fishing", "Hunting", "Camping",
        "Foraging",
    ],
    "data": [
        "Data visualization", "Choropleth map", "Box plot",
        "Principal component analysis", "Simpson's paradox",
        "Regression toward the mean", "Effect size", "Confidence interval",
    ],
    "delivery": [
        "Critical path method", "Theory of constraints", "Kanban (development)",
        "Scrum (software development)", "Earned value management", "Risk register",
    ],
    "finance": [
        "Cash flow", "Gross margin", "Accounts receivable", "Opportunity cost",
        "Break-even (economics)",
    ],
}

API = "https://en.wikipedia.org/w/api.php"


def fetch(title: str) -> str:
    params = {"action": "query", "prop": "extracts", "explaintext": "1",
              "titles": title, "format": "json", "redirects": "1"}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "saimon-corpus/1.0 (contact: operator@localhost)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    pages = (payload.get("query") or {}).get("pages") or {}
    for page in pages.values():
        return page.get("extract") or ""
    return ""


def slug(title: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/home/hermes/reference")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    written = 0
    for field, titles in FIELDS.items():
        for title in titles:
            path = out / f"{field}-{slug(title)}.txt"
            if path.exists():
                continue
            text = ""
            for attempt in range(4):
                try:
                    text = fetch(title)
                    break
                except Exception as exc:  # noqa: BLE001 - one article failing is not fatal
                    wait = 5 * (attempt + 1)
                    print(f"  retry {title} in {wait}s: {str(exc)[:60]}")
                    time.sleep(wait)
            else:
                print(f"  skip {title}")
                continue
            time.sleep(1.5)
            if len(text) < 800:
                print(f"  skip {title}: {len(text)} chars")
                continue
            header = (f"# {title}\n\nSource: Wikipedia, \"{title}\", CC BY-SA 4.0.\n"
                      f"Field: {field}\n\n")
            path.write_text(header + text, encoding="utf-8")
            written += 1
            print(f"  {path.name}: {len(text)} chars")
    print(f"written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
