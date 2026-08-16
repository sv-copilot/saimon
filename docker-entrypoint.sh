#!/usr/bin/env bash
# docker-entrypoint.sh — CMD override dispatch for Saimon MCPs
#
# Usage: docker run --rm saimon <mcp-name>
#   search-mcp    → uvicorn mcp.search.server:app --host 0.0.0.0 --port ${PORT:-8001}
#   generate-mcp  → uvicorn mcp.generate.server:app --host 0.0.0.0 --port ${PORT:-8002}
#   export-mcp    → uvicorn mcp.export.server:app --host 0.0.0.0 --port ${PORT:-8003}
#   evaluate-mcp  → uvicorn mcp.evaluate.server:app --host 0.0.0.0 --port ${PORT:-8004}
#   verify-mcp    → uvicorn mcp.verify.server:app --host 0.0.0.0 --port ${PORT:-8005}
#   explore-mcp   → uvicorn mcp.explore.server:app --host 0.0.0.0 --port ${PORT:-8006}
#   api-mcp       → uvicorn mcp.api.server:app --host 0.0.0.0 --port ${PORT:-8007}
#   domain-mcp    → uvicorn mcp.domain.server:app --host 0.0.0.0 --port ${PORT:-8008}

set -euo pipefail

MCP="${1:-}"

if [ -z "$MCP" ]; then
    echo "Usage: docker run --rm saimon <mcp-name>" >&2
    echo "Available MCPs: search-mcp generate-mcp export-mcp evaluate-mcp verify-mcp explore-mcp api-mcp domain-mcp" >&2
    exit 1
fi

# Map MCP name → module path + default port
case "$MCP" in
    search-mcp)
        MODULE="mcp.search.server:app"
        DEFAULT_PORT=8001
        ;;
    generate-mcp)
        MODULE="mcp.generate.server:app"
        DEFAULT_PORT=8002
        ;;
    export-mcp)
        MODULE="mcp.export.server:app"
        DEFAULT_PORT=8003
        ;;
    evaluate-mcp)
        MODULE="mcp.evaluate.server:app"
        DEFAULT_PORT=8004
        ;;
    verify-mcp)
        MODULE="mcp.verify.server:app"
        DEFAULT_PORT=8005
        ;;
    explore-mcp)
        MODULE="mcp.explore.server:app"
        DEFAULT_PORT=8006
        ;;
    api-mcp)
        MODULE="mcp.api.server:app"
        DEFAULT_PORT=8007
        ;;
    domain-mcp)
        MODULE="mcp.domain.server:app"
        DEFAULT_PORT=8008
        ;;
    *)
        echo "Unknown MCP: $MCP" >&2
        echo "Available: search-mcp generate-mcp export-mcp evaluate-mcp verify-mcp explore-mcp api-mcp domain-mcp" >&2
        exit 1
        ;;
esac

PORT="${PORT:-$DEFAULT_PORT}"

echo "Starting $MCP on 0.0.0.0:$PORT"
exec uvicorn "$MODULE" --host 0.0.0.0 --port "$PORT" --timeout-graceful-shutdown 10
