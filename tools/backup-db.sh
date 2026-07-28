#!/usr/bin/env bash
# backup-db.sh — dump the Saimon PostgreSQL database to a compressed file.
#
# Usage:
#   ./tools/backup-db.sh                    # local docker-compose
#   ./tools/backup-db.sh -h HOST -p PORT    # remote / staging
#
# Reads DATABASE_URL from environment, or falls back to local docker-compose
# defaults.  Creates timestamped .sql.gz files in ./backups/.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
BACKUP_FILE="${BACKUP_DIR}/saimon-backup-${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

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
    *) echo "Usage: $0 [-h host] [-p port] [-U user] [-d database]" >&2; exit 1 ;;
  esac
done

# ── use DATABASE_URL if set ────────────────────────────────────
if [ -n "${DATABASE_URL:-}" ]; then
  echo "[backup] Using DATABASE_URL from environment"
  PGPASSWORD="${DB_PASSWORD}" pg_dump \
    --no-owner \
    --no-acl \
    "${DATABASE_URL}" \
    | gzip > "$BACKUP_FILE"
else
  echo "[backup] Connecting to ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  PGPASSWORD="${DB_PASSWORD}" pg_dump \
    --no-owner \
    --no-acl \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    | gzip > "$BACKUP_FILE"
fi

# ── verify ─────────────────────────────────────────────────────
if [ -s "$BACKUP_FILE" ]; then
  BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
  echo "[backup] ✅ Backup saved: $BACKUP_FILE (${BACKUP_SIZE})"
else
  echo "[backup] ❌ Backup failed — empty file" >&2
  rm -f "$BACKUP_FILE"
  exit 1
fi

# ── cleanup old backups (keep last 30 days) ────────────────────
find "$BACKUP_DIR" -name "saimon-backup-*.sql.gz" -mtime +30 -delete 2>/dev/null || true
echo "[backup] Retained backups from last 30 days in ${BACKUP_DIR}"
