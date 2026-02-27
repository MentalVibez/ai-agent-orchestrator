#!/usr/bin/env bash
# =============================================================================
# scripts/backup.sh — PostgreSQL database backup
#
# Creates a compressed pg_dump archive and optionally uploads to S3.
#
# Usage:
#   ./scripts/backup.sh                          # backup to ./backups/
#   BACKUP_DIR=/mnt/backups ./scripts/backup.sh  # custom directory
#   S3_BUCKET=my-bucket ./scripts/backup.sh      # upload to S3 after backup
#
# Environment variables:
#   DATABASE_URL    — PostgreSQL DSN (required; must be postgres://)
#   BACKUP_DIR      — local directory for backup files (default: ./backups)
#   S3_BUCKET       — if set, upload the archive to s3://<bucket>/db-backups/
#   RETENTION_DAYS  — delete local backups older than N days (default: 7)
#
# Cron example (daily at 01:00 UTC):
#   0 1 * * * /app/scripts/backup.sh >> /var/log/db-backup.log 2>&1
# =============================================================================
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
FILENAME="orchestrator_${TIMESTAMP}.dump.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set." >&2
  exit 1
fi

if [[ "${DATABASE_URL}" != postgres* ]]; then
  echo "ERROR: backup.sh only supports PostgreSQL. DATABASE_URL must start with postgres://." >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

echo "[backup] Starting backup at ${TIMESTAMP}..."
pg_dump "${DATABASE_URL}" --format=custom | gzip > "${FILEPATH}"
BACKUP_SIZE=$(du -sh "${FILEPATH}" | cut -f1)
echo "[backup] Backup complete: ${FILEPATH} (${BACKUP_SIZE})"

# Optional: upload to S3
if [[ -n "${S3_BUCKET:-}" ]]; then
  S3_KEY="db-backups/${FILENAME}"
  echo "[backup] Uploading to s3://${S3_BUCKET}/${S3_KEY} ..."
  aws s3 cp "${FILEPATH}" "s3://${S3_BUCKET}/${S3_KEY}" --storage-class STANDARD_IA
  echo "[backup] Upload complete."
fi

# Remove old local backups
echo "[backup] Cleaning up backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -name "orchestrator_*.dump.gz" -mtime "+${RETENTION_DAYS}" -delete
echo "[backup] Done."
