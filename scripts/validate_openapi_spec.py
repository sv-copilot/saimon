#!/usr/bin/env python3
"""validate_openapi_spec.py — validate the aggregated OpenAPI spec at repo root.

Checks:
1. /openapi.json is valid JSON
2. info.version follows semver
3. All paths have valid HTTP methods
4. All $ref references resolve within the spec
5. No duplicate operationIds
6. MCP tool metadata (x-mcp-tools) is present
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "openapi.json"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
VALID_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Exists and valid JSON
    if not SPEC_PATH.exists():
        errors.append(f"{SPEC_PATH} not found")
        return _report(errors, warnings)

    try:
        spec = json.loads(SPEC_PATH.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"{SPEC_PATH} is not valid JSON: {e}")
        return _report(errors, warnings)

    # 2. OpenAPI version
    if spec.get("openapi") != "3.1.0":
        warnings.append(f"openapi version is {spec.get('openapi')}, expected 3.1.0")

    # 3. Info version semver
    info = spec.get("info", {})
    version = info.get("version", "")
    if not SEMVER_RE.match(version):
        errors.append(f"info.version '{version}' does not follow semver (X.Y.Z)")
    else:
        print(f"✓ info.version = {version}")

    # 4. Paths validation
    paths = spec.get("paths", {})
    if not paths:
        errors.append("No paths defined")
    else:
        print(f"✓ {len(paths)} paths")

    operation_ids: set[str] = set()
    refs: list[str] = []

    for path, methods in sorted(paths.items()):
        if not isinstance(methods, dict):
            errors.append(f"Path '{path}' has no methods object")
            continue
        for method, operation in methods.items():
            if method not in VALID_METHODS:
                errors.append(f"Path '{path}': invalid HTTP method '{method}'")
                continue
            op_id = operation.get("operationId")
            if not op_id:
                warnings.append(f"Path '{path}' {method.upper()}: missing operationId")
            elif op_id in operation_ids:
                errors.append(f"Duplicate operationId: '{op_id}'")
            else:
                operation_ids.add(op_id)
            # Collect $ref targets
            _collect_refs(operation, refs)

    print(f"✓ {len(operation_ids)} unique operationIds")

    # 5. $ref resolution
    schemas = spec.get("components", {}).get("schemas", {})
    unresolved: list[str] = []
    for ref in refs:
        if ref.startswith("#/components/schemas/"):
            schema_name = ref[len("#/components/schemas/"):]
            if schema_name not in schemas:
                unresolved.append(ref)
    if unresolved:
        errors.append(f"Unresolved $refs: {unresolved}")
    else:
        print(f"✓ All {len(refs)} $ref references resolve")

    # 6. Security schemes
    security_schemes = spec.get("components", {}).get("securitySchemes", {})
    if "BearerAuth" not in security_schemes and "ApiKeyAuth" not in security_schemes:
        warnings.append("No security schemes defined")
    else:
        print(f"✓ Security schemes: {list(security_schemes.keys())}")

    # 7. MCP tool metadata
    mcp_tools = spec.get("x-mcp-tools", {})
    if mcp_tools:
        total = sum(len(v.get("tools", {})) for v in mcp_tools.values())
        print(f"✓ x-mcp-tools: {total} tools across {len(mcp_tools)} MCPs")
    else:
        warnings.append("x-mcp-tools extension not present — consumers can't discover MCP tools")

    # 8. Schema count
    print(f"✓ {len(schemas)} component schemas")

    return _report(errors, warnings)


def _collect_refs(obj, refs: list[str]) -> None:
    """Recursively collect all $ref values."""
    if isinstance(obj, dict):
        if "$re" in obj:
            refs.append(obj["$ref"])
        for v in obj.values():
            _collect_refs(v, refs)
    elif isinstance(obj, list):
        for item in obj:
            _collect_refs(item, refs)


def _report(errors: list[str], warnings: list[str]) -> int:
    for w in warnings:
        print(f"⚠  {w}")
    for e in errors:
        print(f"✗  {e}")
    if errors:
        print(f"\n❌ Validation FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    if warnings:
        print(f"\n⚠  Validation passed with {len(warnings)} warning(s)")
    else:
        print("\n✅ Validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
