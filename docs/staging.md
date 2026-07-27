# Staging Deployment

Saimon staging runs on a Hetzner CX22 VPS in Nuremberg (hel1).

## Access

| What | Value |
|---|---|
| IP | `95.216.208.183` |
| SSH | `ssh spencer@95.216.208.183` (alias `staging-rs`) |
| Caddy | `https://mcp-staging.spencervaradi.com` |
| Deployment | `/data/planning/saimon` |

## Services

| Service | Internal Port | Caddy Path |
|---|---|---|
| search-mcp | 8101 | `/saimon/search/*` |
| generate-mcp | 8102 | `/saimon/generate/*` |
| export-mcp | 8103 | `/saimon/export/*` |
| evaluate-mcp | 8104 | `/saimon/evaluate/*` |
| verify-mcp | 8105 | `/saimon/verify/*` |
| explore-mcp | 8106 | `/saimon/explore/*` |
| PostgreSQL | 5433 | (internal only) |

## Deploy

```bash
# From local:
cd /Users/simon/saimon
tar czf /tmp/saimon.tar.gz --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' .
scp /tmp/saimon.tar.gz staging-rs:/tmp/

# On VPS:
cd /data/planning/saimon
sudo tar xzf /tmp/saimon.tar.gz
docker compose -f docker-compose.yml -f docker-compose.staging.yml build --no-cache
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --force-recreate
```

## Health Checks

```bash
ssh staging-rs
for port in 8101 8102 8103 8104 8105 8106; do
  curl -s http://127.0.0.1:$port/health
done
```

## Secrets

DeepSeek API key configured in `docker-compose.staging.yml` environment.
PostgreSQL credentials via Docker Compose defaults (dev only).
For production, use `docker-compose.prod.yml` with `.env` file.

## Caddy

Caddyfile at `/opt/caddy/Caddyfile`. Saimon routes under `mcp-staging.spencervaradi.com`.
Reload: `docker restart caddy`

## Monitoring

```bash
# Container status
docker compose -f docker-compose.yml -f docker-compose.staging.yml ps

# Logs
docker compose -f docker-compose.yml -f docker-compose.staging.yml logs -f search-mcp

# Database
docker exec saimon-postgres psql -U saimon -d saimon \
  -c "SELECT count(*) FROM audit_log; SELECT count(*) FROM knowledge_graph_nodes;"
```
