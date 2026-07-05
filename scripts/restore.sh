#!/usr/bin/env bash
# ── Triple-Fusion-Engine Restore Script ──────────────────────────────────────
#
# Restores the database and models from the latest backup.
# Run this on a fresh server to recover from disaster.
#
# Usage:
#   ./scripts/restore.sh                          # restore from latest local backup
#   ./scripts/restore.sh /path/to/backup_dir      # restore from specific dir
#   ./scripts/restore.sh --s3 s3://my-bucket/tfe  # pull from S3 first, then restore
#
# WARNING: This overwrites the current database and models.
#          Stop all TFE services first:
#            docker compose -f docker-compose.yml -f docker-compose.prod.yml down
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${PROJECT_DIR}/backups"
S3_SOURCE=""
RESTORE_DB=true
RESTORE_MODELS=true

# ── Parse args ───────────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --s3)
            S3_SOURCE="$2"; shift 2 ;;
        --no-db)
            RESTORE_DB=false; shift ;;
        --no-models)
            RESTORE_MODELS=false; shift ;;
        -*)
            echo "Unknown flag: $1"; exit 1 ;;
        *)
            BACKUP_DIR="$1"; shift ;;
    esac
done

echo "=== TFE Restore started at $(date) ==="
echo "  Backup dir: ${BACKUP_DIR}"

# ── Pull from S3 if requested ────────────────────────────────────────────────

if [[ -n "$S3_SOURCE" ]]; then
    echo "  Pulling from S3: ${S3_SOURCE} → ${BACKUP_DIR}"
    mkdir -p "$BACKUP_DIR"
    if command -v aws &>/dev/null; then
        aws s3 sync "$S3_SOURCE" "$BACKUP_DIR" --delete 2>/dev/null || {
            echo "ERROR: aws s3 sync failed"; exit 1
        }
    else
        echo "ERROR: aws CLI not installed"
        exit 1
    fi
fi

if [ ! -d "$BACKUP_DIR" ]; then
    echo "ERROR: backup directory not found: ${BACKUP_DIR}"
    exit 1
fi

# ── 1. Find latest backups ──────────────────────────────────────────────────

LATEST_DB=$(find "$BACKUP_DIR" -name "users_*.db" -type f -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
LATEST_PGDUMP=$(find "$BACKUP_DIR" -name "db_*.pgdump" -type f -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
LATEST_MODELS=$(find "$BACKUP_DIR" -name "models_*.tar.gz" -type f -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)

# ── 2. Restore Database ─────────────────────────────────────────────────────

if $RESTORE_DB; then
    # SQLite
    if [[ -n "$LATEST_DB" ]]; then
        echo "  Restoring SQLite: ${LATEST_DB}"
        mkdir -p "${PROJECT_DIR}/instance"
        cp "$LATEST_DB" "${PROJECT_DIR}/instance/users.db"
        echo "  → ${PROJECT_DIR}/instance/users.db restored"
    else
        echo "  SQLite: no backup found — skipping"
    fi

    # PostgreSQL
    if [[ -n "$LATEST_PGDUMP" ]]; then
        DB_URL="${DATABASE_URL:-}"
        if [[ -n "$DB_URL" && "$DB_URL" == postgresql://* ]]; then
            echo "  Restoring PostgreSQL from: ${LATEST_PGDUMP}"
            PG_USER=$(echo "$DB_URL" | sed -n 's|.*://\([^:]*\):.*|\1|p')
            PG_PASS=$(echo "$DB_URL" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')
            PG_HOST=$(echo "$DB_URL" | sed -n 's|.*@\([^:/]*\).*|\1|p')
            PG_PORT=$(echo "$DB_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
            PG_DB=$(echo "$DB_URL" | sed -n 's|.*/\([^?]*\).*|\1|p')
            PG_PORT="${PG_PORT:-5432}"

            PGPASSWORD="$PG_PASS" pg_restore -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" \
                -d "$PG_DB" --clean --if-exists --no-owner --no-acl \
                "$LATEST_PGDUMP" 2>/dev/null && \
                echo "  → PostgreSQL ${PG_DB} restored" || \
                echo "  ERROR: pg_restore failed"
        else
            echo "  PostgreSQL: DATABASE_URL not set — cannot restore pgdump"
        fi
    else
        echo "  PostgreSQL: no backup found — skipping"
    fi
fi

# ── 3. Restore Models ───────────────────────────────────────────────────────

if $RESTORE_MODELS; then
    if [[ -n "$LATEST_MODELS" ]]; then
        echo "  Restoring models: ${LATEST_MODELS}"
        MODELS_DIR="${PROJECT_DIR}/Saved Models"
        rm -rf "$MODELS_DIR" 2>/dev/null || true
        mkdir -p "$MODELS_DIR"
        tar -xzf "$LATEST_MODELS" -C "$PROJECT_DIR" 2>/dev/null
        MODEL_COUNT=$(find "$MODELS_DIR" -type f | wc -l)
        echo "  → ${MODEL_COUNT} file(s) restored to ${MODELS_DIR}"
    else
        echo "  Models: no backup found — skipping"
    fi
fi

echo "=== TFE Restore complete at $(date) ==="
echo ""
echo "Next steps:"
echo "  1. Verify .env is configured correctly"
echo "  2. Run migrations: docker compose run --rm web python -c \"from db_utils import run_migrations; run_migrations()\""
echo "  3. Start services: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
echo "  4. Check health:  ./scripts/healthcheck.sh"
