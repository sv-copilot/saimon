# Migrations

Schema changes ship as files in `db/migrations/`. They are applied by CI/CD before services
restart, on the same host, against the compose Postgres.

```
db/migrations/2026-11-18-universes-and-collection.sql
scripts/apply_migrations.sh
```

`schema.sql` bootstraps an empty database. A migration moves one that already exists. Editing
`schema.sql` alone leaves every running database behind, which is how staging ended up with a
`knowledge_graph_nodes` table that had no `collection` column while the code expected one.

## The rules

- **One file, one change, in order.** Filenames sort; they are applied oldest first.
- **Never edit an applied migration.** The runner records a sha256 with each version and refuses
  to continue when a file changes afterwards. Two databases would otherwise disagree about what
  the schema means. If a change must land, add a new file; `--accept-drift` exists to re-record a
  file that was edited by mistake, and it does not re-run the SQL.
- **Idempotent.** `IF NOT EXISTS`, `ON CONFLICT DO NOTHING`, conditional grants. A migration may
  be applied to a database that already has part of the change — that is the normal case on the
  day it is written.
- **No roles assumed.** On a fresh database the per-service roles are created by
  `db/init-roles.sh` at container init, which may not have run when a migration applies. Grant
  only to roles that exist.

## Where it runs

| Environment | When | How |
|---|---|---|
| CI | every push and PR | `migrations` job: apply `schema.sql` to an empty Postgres, then every migration, then prove a second run changes nothing |
| Staging | every push to `rc` | deploy job copies `db/migrations/` and the runner to the host, `up -d postgres`, then `bash scripts/apply_migrations.sh` before recreating services |
| Production | every push to `main` | same, at `/data/saimon` |

## Locally

```bash
DATABASE_URL=postgresql://saimon:...@127.0.0.1:5433/saimon ./scripts/apply_migrations.sh --dry-run
DATABASE_URL=postgresql://saimon:...@127.0.0.1:5433/saimon ./scripts/apply_migrations.sh
```

Exit codes: `0` applied or nothing to do, `1` a migration failed, `2` a checksum drifted.
