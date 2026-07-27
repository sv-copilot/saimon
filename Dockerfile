# Saimon — single Docker image, CMD override per MCP
#
# Build:  docker build -t saimon .
# Run:    docker run --rm saimon search-mcp
#
# Each MCP runs as a long-running uvicorn process on the port assigned
# in docker-compose.yml or via the PORT environment variable.

FROM python:3.11-slim

LABEL org.opencontainers.image.title="Saimon Platform"
LABEL org.opencontainers.image.description="6 atomic MCP services sharing one PostgreSQL knowledge graph"

# ---------------------------------------------------------------------------
# system dependencies
# ---------------------------------------------------------------------------

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# application
# ---------------------------------------------------------------------------

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY research_shared/ research_shared/
COPY mcp/ mcp/

# ---------------------------------------------------------------------------
# entrypoint — maps MCP name to uvicorn invocation
# ---------------------------------------------------------------------------

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
