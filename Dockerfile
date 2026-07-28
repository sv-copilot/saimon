# Saimon — single Docker image, CMD override per MCP
#
# Build:  docker build -t saimon .
# Run:    docker run --rm saimon search-mcp
#
# Each MCP runs as a long-running uvicorn process on the port assigned
# in docker-compose.yml or via the PORT environment variable.

# Pinned to specific digest for reproducible builds.
# Update digest with: docker pull python:3.11-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.11-slim
FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

LABEL org.opencontainers.image.title="Saimon Platform"
LABEL org.opencontainers.image.description="6 atomic MCP services sharing one PostgreSQL knowledge graph"

# ---------------------------------------------------------------------------
# system dependencies
# ---------------------------------------------------------------------------

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# create non-root 'saimon' user
# ---------------------------------------------------------------------------

RUN groupadd -r saimon && useradd -r -g saimon -d /app -s /sbin/nologin saimon

# ---------------------------------------------------------------------------
# application
# ---------------------------------------------------------------------------

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY research_shared/ research_shared/
COPY mcp/ mcp/

# ---------------------------------------------------------------------------
# set ownership to non-root user
# ---------------------------------------------------------------------------

RUN chown -R saimon:saimon /app

# ---------------------------------------------------------------------------
# entrypoint — maps MCP name to uvicorn invocation
# ---------------------------------------------------------------------------

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Run as non-root
USER saimon

ENTRYPOINT ["/docker-entrypoint.sh"]
