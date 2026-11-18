# Staging

Host `cockpit` (95.216.208.183), compose project at `/data/planning/saimon`, images tagged
`ghcr.io/sv-copilot/saimon:rc`. The deploy job reads the path from the repository variable
`SAIMON_STAGING_PATH`; it is set to that directory.

## The bootstrap a fresh staging host needs

Three things, and missing any one produces the same symptom: containers report `healthy` while
every service is failing inside.

1. **`.env` in the compose directory.** Compose interpolates `${POSTGRES_PASSWORD}`,
   `${DEEPSEEK_API_KEY}`, `${SAIMON_JWT_SECRET}` and one `<ROLE>_DB_PASSWORD` per service. With no
   file, every value is empty and every service fails authentication with an empty password. The
   directory is root-owned; write the file through a container (`docker run --rm -v
   /data/planning/saimon:/t alpine sh -c 'cat > /t/.env'`) and `chown` it to the deploy user.
2. **The per-service roles.** `db/init-roles.sh` only runs on first database init. A Postgres that
   was initialised before that script existed has only the `saimon` role, and no restart will
   create the others. Create them explicitly, with the same passwords as `.env`, and grant
   `CONNECT`, `USAGE`/`CREATE` on `public`, and DML on tables.
3. **Table ownership for `api_mcp`.** The API's startup migration alters existing tables, which
   requires ownership, not merely DML grants. `ALTER TABLE public.<table> OWNER TO api_mcp` for
   `users`, `refresh_tokens`, `chat_sessions`, `chat_messages`, `documents`.

## How to tell it is actually working

`GET /health` on ports 8101–8109. `status: ok` is not enough on its own; check that
`checks.database` says `connected` where a database check exists. Nine `ok` lines with
`database: unavailable` is exactly the state staging sat in for a week.

## What staging is for

The rc gate: a build that passed CI, reachable before production. It carries a small seed corpus
(`kg_nodes: 200`), not the production data, so retrieval quality is not measured here — the
release A/B runs against production endpoints.
