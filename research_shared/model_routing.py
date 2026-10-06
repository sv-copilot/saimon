"""Config-driven model routing for saimon services.

Reads the canonical `.docs/model_routing.json` (from the planning checkout,
falling back to a vendored copy, then built-in defaults) and resolves saimon
routes to tier parameters. Pure — no network and no import-time side effects
beyond a JSON read.

Saimon-side counterpart to the same routing logic used by the planning
workspace this platform was built in (DRAKE-MODEL-ROUTING-1).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_VENDORED_PATH = Path(__file__).resolve().parent / "model_routing.json"

_BUILT_IN_TIERS: dict = {
    "reasoning": {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "temperature": 0.2,
        "max_tokens": 12000,
    },
    "classification": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "temperature": 0.0,
        "max_tokens": 1024,
    },
    "mechanical": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "temperature": 0.1,
        "max_tokens": 4000,
    },
}
_BUILT_IN_ROUTES: dict = {
    "saimon.generate": "reasoning",
    "saimon.verify": "reasoning",
    "saimon.evaluate": "classification",
    "saimon.extract_claims": "mechanical",
}

DEFAULT_MODEL = "deepseek-v4-pro"


def canonical_config_path() -> Path | None:
    """Return the canonical config path in the planning checkout, if present."""
    root = os.getenv("PLANNING_CHECKOUT_PATH")
    if root:
        path = Path(root) / ".docs" / "model_routing.json"
        if path.exists():
            return path
    return None


def load_config() -> dict:
    """Load the model-routing config (canonical > vendored > built-in)."""
    canonical = canonical_config_path()
    candidates = ([canonical] if canonical else []) + [_VENDORED_PATH]
    for path in candidates:
        if path is not None and path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return {"version": 1, "tiers": _BUILT_IN_TIERS, "routes": _BUILT_IN_ROUTES}


def resolve_route(route_key: str) -> dict:
    """Resolve a route key to its full tier dict (KeyError if unknown)."""
    cfg = load_config()
    tier_name = cfg.get("routes", {}).get(route_key)
    if tier_name is None:
        raise KeyError(f"route {route_key!r} not declared in model routing config")
    tier = cfg.get("tiers", {}).get(tier_name)
    if tier is None:
        raise KeyError(f"tier {tier_name!r} not declared in model routing config")
    return tier


def model_for_route(route_key: str) -> str:
    """Return the model slug a route resolves to."""
    return resolve_route(route_key).get("model", DEFAULT_MODEL)


def route_params(route_key: str) -> dict:
    """Per-call generate() kwargs (model/temperature/max_tokens) for a route."""
    tier = resolve_route(route_key)
    return {
        "model": tier.get("model", DEFAULT_MODEL),
        "temperature": tier.get("temperature", 0.7),
        "max_tokens": tier.get("max_tokens", 4096),
    }


def declared_models() -> set[str]:
    """The allowlist: every model declared by any tier."""
    cfg = load_config()
    return {
        tier.get("model")
        for tier in cfg.get("tiers", {}).values()
        if isinstance(tier, dict) and tier.get("model")
    }


def validate_allowlist(used_models) -> list[str]:
    """Return problems for any used model not declared in the config tiers."""
    allowed = {model.lower() for model in declared_models()}
    problems = []
    for model in used_models:
        slug = (model or "").strip().lower()
        if slug and slug not in allowed:
            problems.append(f"{model!r} not in allowlist {sorted(allowed)}")
    return problems
