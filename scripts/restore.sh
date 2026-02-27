#!/usr/bin/env bash
# =============================================================================
# scripts/restore.sh — PostgreSQL database restore from backup
#
# DANGER: This DROPS and recreates the target database. Use with caution.
# Always test the restore procedure in a staging environment first.
#
# Usage:
#   ./scripts/restore.sh ./backups/orchestrator_20260225T010000Z.dump.gz
#   S3_BUCKET=my-bucket ./scripts/restore.sh s3://my-bucket/db-backups/file.dump.gz
#
# Environment variables:
#   DATABASE_URL  — target PostgreSQL DSN (required)
#   CONFIRM       — set to "yes" to skip the interactive prompt (for automation)
# =============================================================================
set -euo pipefail

BACKUP_FILE="${1:-}"
CONFIRM="${CONFIRM:-no}"

if [[ -z "${BACKUP_FILE}" ]]; then
  echo "Usage: $0 <backup-file-or-s3-uri>" >&2
  exit 1
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set." >&2
  exit 1
fi

if [[ "${DATABASE_URL}" != postgres* ]]; then
  echo "ERROR: restore.sh only supports PostgreSQL." >&2
  exit 1
fi

# Warn loudly
echo "============================================================"
echo " WARNING: This will DESTROY all data in the target database."
echo " Target: ${DATABASE_URL}"
echo " Source: ${BACKUP_FILE}"
echo "============================================================"

if [[ "${CONFIRM}" != "yes" ]]; then
  read -r -p "Type 'yes' to proceed: " answer
  if [[ "${answer}" != "yes" ]]; then
    echo "Aborted." >&2
    exit 1
  fi
fi

# Download from S3 if needed
LOCAL_FILE="${BACKUP_FILE}"
if [[ "${BACKUP_FILE}" == s3://* ]]; then
  TMPFILE=$(mktemp /tmp/restore_XXXXXX.dump.gz)
  echo "[restore] Downloading ${BACKUP_FILE} from S3..."
  aws s3 cp "${BACKUP_FILE}" "${TMPFILE}"
  LOCAL_FILE="${TMPFILE}"
  trap "rm -f ${TMPFILE}" EXIT
fi

if [[ ! -f "${LOCAL_FILE}" ]]; then
  echo "ERROR: File not found: ${LOCAL_FILE}" >&2
  exit 1
fi

echo "[restore] Dropping existing schema and restoring..."
# Drop all tables in public schema cleanly (avoids needing superuser DROP DATABASE)
psql "${DATABASE_URL}" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" 2>/dev/null || true

# Restore
gunzip -c "${LOCAL_FILE}" | pg_restore --dbname="${DATABASE_URL}" --no-owner --no-privileges --single-transaction

echo "[restore] Running Alembic migrations to ensure schema is up to date..."
alembic upgrade head

echo "[restore] Restore complete. Verify data integrity before resuming traffic."
