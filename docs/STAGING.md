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

## Seeding the corpus

Staging starts with a 200-node seed. The portfolio corpus is loaded with the same tool as
production:

```bash
# on the source host: package the trees (the ingest skips binaries and audio)
tar -czf src.tgz --exclude='.git' --exclude='node_modules' --exclude='audio' \
  --exclude='piper-venv' --exclude='*.pdf' drake-governance/.docs drake-public drake-pmo \
  spencervaradi-site/src/content spencervaradi-site/src/pages spencervaradi-site/src/data \
  vaults/workspace writing work/needle work/hand-recovery saimon/docs saimon/fixtures saimon/reports

# on staging: unpack, then run the writer and the embedder
docker run --rm --user 1002:1002 --network saimon_default --env-file ingest.env \
  -v $S/ingest:/app/scripts:ro -v $S/drake-governance/.docs:/src/governance:ro ... \
  ghcr.io/sv-copilot/saimon:rc /app/scripts/bulk_ingest.py --write
```

The scripts are mounted rather than baked: the runtime image carries the packages, not
`scripts/`. `ingest.env` needs `DATABASE_URL` (from `docker exec saimon-api printenv`) and
`SAIMON_EMBEDDING_MODEL_PATH`.

Write rate is minutes; embedding is the long pole. On four cores it runs at about 2 per second,
so 16,000 chunks take roughly two hours. Search abstains until the embedding pass reaches the
collection being queried.
