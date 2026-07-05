#!/usr/bin/env bash
# ── Triple-Fusion-Engine Backup Script ────────────────────────────────────────
#
# Backs up the database (SQLite or PostgreSQL) + ML models + logs.
# Designed for cron.daily or manual invocation.
#
# Usage:
#   ./scripts/backup.sh                        # local backup only
#   ./scripts/backup.sh --upload               # also upload to S3/Azure
#
# Environment:
#   BACKUP_DIR              target directory (default: ./backups)
#   BACKUP_RETENTION_DAYS   auto-delete older than N days (default: 30)
#   DATABASE_URL            db connection; empty = SQLite at instance/users.db
#   BACKUP_S3_BUCKET        optional S3 bucket (s3://my-bucket/tfe-backups)
#   BACKUP_AZURE_CONTAINER  optional Azure container name
#   AZURE_STORAGE_CONNECTION_STRING  Azure connection string
#
# Cron entry (daily at 02:00):
#   0 2 * * * cd /opt/tfe && ./scripts/backup.sh >> logs/backup.log 2>&1
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_DIR}/backups}"
RETENTION="${BACKUP_RETENTION_DAYS:-30}"
DATE="$(date +%Y%m%d-%H%M%S)"
UPLOAD=false

if [[ "${1:-}" == "--upload" ]]; then
    UPLOAD=true
fi

mkdir -p "$BACKUP_DIR"

echo "=== TFE Backup started at $(date) ==="

# ── 1. Database Backup ───────────────────────────────────────────────────────

DB_URL="${DATABASE_URL:-}"
DB_BACKUP="${BACKUP_DIR}/db_${DATE}"

# Ensure the instance directory exists (SQLite multi-container: db is in the volume)
INSTANCE_DIR="${PROJECT_DIR}/instance"
if [ ! -f "${INSTANCE_DIR}/users.db" ] && docker ps --format '{{.Names}}' | grep -q "tfe-web"; then
    echo "Copying SQLite DB from tfe-web container..."
    docker cp tfe-web:/app/instance/users.db "${BACKUP_DIR}/users_${DATE}.db" 2>/dev/null || true
else
    echo "Copying SQLite DB from host mount..."
    cp "${INSTANCE_DIR}/users.db" "${BACKUP_DIR}/users_${DATE}.db" 2>/dev/null || true
fi

if [ -f "${BACKUP_DIR}/users_${DATE}.db" ]; then
    echo "  SQLite: ${BACKUP_DIR}/users_${DATE}.db ($(du -h "${BACKUP_DIR}/users_${DATE}.db" | cut -f1))"
else
    echo "  SQLite: no users.db found — skipping"
fi

# PostgreSQL (if DATABASE_URL is set)
if [[ -n "$DB_URL" && "$DB_URL" == postgresql://* ]]; then
    # Parse DATABASE_URL: postgresql://user:pass@host:port/dbname
    PG_USER=$(echo "$DB_URL" | sed -n 's|.*://\([^:]*\):.*|\1|p')
    PG_PASS=$(echo "$DB_URL" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')
    PG_HOST=$(echo "$DB_URL" | sed -n 's|.*@\([^:/]*\).*|\1|p')
    PG_PORT=$(echo "$DB_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
    PG_DB=$(echo "$DB_URL" | sed -n 's|.*/\([^?]*\).*|\1|p')
    PG_PORT="${PG_PORT:-5432}"

    echo "  PostgreSQL: dumping ${PG_DB}@${PG_HOST}:${PG_PORT}..."
    if PGPASSWORD="$PG_PASS" pg_dump -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
        -Fc -f "${DB_BACKUP}.pgdump" --no-owner --no-acl 2>/dev/null; then
        echo "  PostgreSQL: ${DB_BACKUP}.pgdump ($(du -h "${DB_BACKUP}.pgdump" | cut -f1))"
    else
        echo "  PostgreSQL: pg_dump failed — is pg_dump installed and the host reachable?"
    fi
fi

# ── 2. Model Backup ──────────────────────────────────────────────────────────

MODELS_DIR="${PROJECT_DIR}/Saved Models"
if [ -d "$MODELS_DIR" ] && [ "$(ls -A "$MODELS_DIR" 2>/dev/null)" ]; then
    MODELS_ARCHIVE="${BACKUP_DIR}/models_${DATE}.tar.gz"
    tar -czf "$MODELS_ARCHIVE" -C "$PROJECT_DIR" "Saved Models" 2>/dev/null
    echo "  Models: ${MODELS_ARCHIVE} ($(du -h "$MODELS_ARCHIVE" | cut -f1))"
else
    echo "  Models: Saved Models/ empty or missing — skipping"
fi

# ── 3. Cleanup (rotation) ───────────────────────────────────────────────────

DELETED=$(find "$BACKUP_DIR" -type f \( -name "*.db" -o -name "*.pgdump" -o -name "*.tar.gz" \) -mtime +"$RETENTION" -delete -print | wc -l)
echo "  Rotation: removed ${DELETED} file(s) older than ${RETENTION} days"

# ── 4. Cloud Upload (optional) ───────────────────────────────────────────────

if $UPLOAD; then
    echo "  Upload: starting..."

    # S3
    if [[ -n "${BACKUP_S3_BUCKET:-}" ]]; then
        echo "  Upload: S3 → ${BACKUP_S3_BUCKET}"
        if command -v aws &>/dev/null; then
            aws s3 sync "$BACKUP_DIR" "$BACKUP_S3_BUCKET" --delete --exclude "*" \
                --include "users_${DATE}.db" \
                --include "models_${DATE}.tar.gz" \
                ${DB_BACKUP:+"--include db_${DATE}.pgdump"} 2>/dev/null || echo "  Upload: aws s3 sync failed"
        else
            echo "  Upload: aws CLI not installed — skipping S3"
        fi
    fi

    # Azure Blob
    if [[ -n "${BACKUP_AZURE_CONTAINER:-}" && -n "${AZURE_STORAGE_CONNECTION_STRING:-}" ]]; then
        echo "  Upload: Azure → ${BACKUP_AZURE_CONTAINER}"
        if command -v azcopy &>/dev/null; then
            azcopy sync "$BACKUP_DIR" "https://${AZURE_STORAGE_CONNECTION_STRING#*AccountName=}..." \
                --include-pattern "users_${DATE}.db;models_${DATE}.tar.gz" 2>/dev/null || true
        elif command -v az &>/dev/null; then
            az storage blob upload-batch -d "$BACKUP_AZURE_CONTAINER" -s "$BACKUP_DIR" \
                --pattern "*${DATE}*" 2>/dev/null || echo "  Upload: az storage blob upload-batch failed"
        else
            echo "  Upload: azcopy / az CLI not installed — skipping Azure"
        fi
    fi
fi

echo "=== TFE Backup complete at $(date) ==="
