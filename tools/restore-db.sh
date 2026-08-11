#!/usr/bin/env bash
# restore-db.sh — restore a Saimon PostgreSQL database from a compressed backup.
#
# Usage:
#   ./tools/restore-db.sh backups/saimon-backup-20240101T000000Z.sql.gz
#   ./tools/restore-db.sh -h HOST -p PORT backups/...
#
# WARNING: This will DROP and recreate all tables.  Use with caution.

set -euo pipefail

if [ $# -eq 0 ]; then
  echo "Usage: $0 [-h host] [-p port] [-U user] [-d database] <backup-file.sql.gz>" >&2
  echo "" >&2
  echo "  Restore a Saimon database from a compressed pg_dump backup." >&2
  echo "  WARNING: Destructive — drops existing data." >&2
  exit 1
fi

# ── parse flags ────────────────────────────────────────────────
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-saimon}"
DB_NAME="${DB_NAME:-saimon}"
DB_PASSWORD="${DB_PASSWORD:-saimon-dev}"

while getopts "h:p:U:d:" opt; do
  case "$opt" in
    h) DB_HOST="$OPTARG" ;;
    p) DB_PORT="$OPTARG" ;;
    U) DB_USER="$OPTARG" ;;
    d) DB_NAME="$OPTARG" ;;
    *) echo "Usage: $0 [-h host] [-p port] [-U user] [-d database] <backup-file.sql.gz>" >&2; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

BACKUP_FILE="$1"
shift || true

if [ ! -f "$BACKUP_FILE" ]; then
  echo "[restore] ❌ Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

# ── confirm ────────────────────────────────────────────────────
echo "[restore] ⚠️  WARNING: This will DROP all data in '${DB_NAME}' on ${DB_HOST}:${DB_PORT}"
echo "[restore] Backup file: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
echo ""
read -r -p "Type 'yes' to confirm restore: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "[restore] Cancelled."
  exit 0
fi

# ── restore ────────────────────────────────────────────────────
if [ -n "${DATABASE_URL:-}" ]; then
  echo "[restore] Using DATABASE_URL from environment"
  gunzip -c "$BACKUP_FILE" | PGPASSWORD="${DB_PASSWORD}" psql "${DATABASE_URL}"
else
  echo "[restore] Connecting to ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  gunzip -c "$BACKUP_FILE" | PGPASSWORD="${DB_PASSWORD}" psql \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME"
fi

echo "[restore] ✅ Restore complete from: $BACKUP_FILE"
