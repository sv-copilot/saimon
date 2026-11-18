#!/usr/bin/env bash
# Apply db/migrations/*.sql exactly once, in filename order.
#
# The ledger is a table in the same database, so a migration and its record land
# together. A file whose checksum changed after it was applied is a refusal, not
# a re-run: editing an applied migration makes two databases disagree about what
# the schema means, and that is the failure this guards against.
#
#   ./scripts/apply_migrations.sh                      # via docker compose on the host
#   DATABASE_URL=postgresql://... ./scripts/apply_migrations.sh
#   ./scripts/apply_migrations.sh --dry-run
#
# Exit codes: 0 applied or nothing to do, 1 a migration failed, 2 a checksum drifted.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATIONS="$ROOT/db/migrations"
DRY_RUN=0
ACCEPT_DRIFT=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --accept-drift) ACCEPT_DRIFT=1 ;;
    esac
done

# The deploy host has docker and no psql client, so the client comes from an
# image either way. DATABASE_URL is used for a direct connection; otherwise the
# compose postgres service is addressed by name.
psql_invoke() {
    local mode="$1"; shift
    if [ -n "${DATABASE_URL:-}" ] && command -v psql >/dev/null 2>&1; then
        psql "$DATABASE_URL" -v ON_ERROR_STOP=1 "$@"
    elif [ -n "${DATABASE_URL:-}" ]; then
        docker run --rm -i --network host "${PSQL_IMAGE:-postgres:16}" \
            psql "$DATABASE_URL" -v ON_ERROR_STOP=1 "$@"
    else
        docker compose exec -T postgres psql -U saimon -d saimon -v ON_ERROR_STOP=1 "$@"
    fi
}

# stdin is closed for every call: the deploy pipes this script into `bash -s`,
# so a client that reads stdin consumes the rest of the deploy script and the
# job "succeeds" after applying migrations without ever restarting a service.
psql_run() { psql_invoke query -At "$@" < /dev/null; }

# SQL is passed as an argument rather than on stdin for the same reason.
apply_file() {
    local sql
    sql="$(cat "$1")"
    psql_invoke exec -q -c "$sql" < /dev/null
}

psql_run -c "CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)" >/dev/null || { echo "cannot create schema_migrations" >&2; exit 1; }

shopt -s nullglob
files=("$MIGRATIONS"/*.sql)
if [ ${#files[@]} -eq 0 ]; then
    echo "no migrations"
    exit 0
fi

IFS=$'\n' files=($(printf '%s\n' "${files[@]}" | sort))
unset IFS

applied=0
skipped=0
for file in "${files[@]}"; do
    version="$(basename "$file")"
    checksum="$(sha256sum "$file" | cut -d' ' -f1)"
    row="$(psql_run -c "SELECT checksum FROM schema_migrations WHERE version = '$version'")"

    if [ -n "$row" ]; then
        if [ "$row" != "$checksum" ]; then
            if [ "$ACCEPT_DRIFT" = "1" ]; then
                echo "DRIFT ACCEPTED: $version re-recorded (${row:0:12} -> ${checksum:0:12}); SQL not re-run" >&2
                psql_run -c "UPDATE schema_migrations SET checksum = '$checksum', applied_at = now() WHERE version = '$version'" >/dev/null
                continue
            fi
            echo "DRIFT: $version was applied with checksum ${row:0:12}, file now ${checksum:0:12}" >&2
            echo "Re-run with --accept-drift only if the change is known safe; the SQL is not re-applied." >&2
            exit 2
        fi
        skipped=$((skipped + 1))
        continue
    fi

    if [ "$DRY_RUN" = "1" ]; then
        echo "pending: $version"
        continue
    fi

    echo "applying: $version"
    if ! apply_file "$file"; then
        echo "FAILED: $version" >&2
        exit 1
    fi
    psql_run -c "INSERT INTO schema_migrations (version, checksum) VALUES ('$version', '$checksum')" >/dev/null
    applied=$((applied + 1))
done

echo "migrations: ${applied} applied, ${skipped} already present"
