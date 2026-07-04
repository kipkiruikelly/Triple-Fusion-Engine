# BullLogic Deployment Guide

Production deployment guide for the BullLogic algorithmic trading platform.

## Prerequisites

- **Server**: Linux (Ubuntu 22.04+), 4+ CPU cores, 8GB+ RAM, 50GB+ SSD
- **Software**: Docker 24+, Docker Compose v2, Git, Caddy (reverse proxy)
- **Domain**: A domain name pointing to your server (e.g., `trading.yourdomain.com`)
- **API Keys**: MetaApi token, email SMTP credentials, Stripe keys (optional)

## Quick Deploy (Docker)

```bash
# Clone the repository
git clone https://github.com/kipkiruikelly/Triple-Fusion-Engine.git
cd Triple-Fusion-Engine

# Copy and edit environment file
cp .env.example .env
nano .env  # Fill in all required values

# Set production environment
echo "ENV=production" >> .env

# Build and start all services
docker compose up -d --build

# Verify all services are healthy
docker compose ps
```

### Production Deploy (Recommended)

For production, use the overlay compose file with resource limits, persistent
named volumes, and log rotation:

```bash
# Copy the production env template
cp .env.production .env
nano .env  # Fill in all required values (especially SECRET_KEY)

# Build and start with production overrides
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Verify
docker compose ps
./scripts/healthcheck.sh
```

**What the production overlay adds over the base compose file:**

| Feature | Base | Production |
|---------|------|------------|
| Volumes | Bind mounts (host dirs) | Named Docker volumes |
| Restart | `unless-stopped` | `always` (survives daemon restarts) |
| Redis | No persistence config | AOF enabled + `allkeys-lru` + RDB snapshots |
| Resource limits | None | CPU/memory limits per service |
| Log rotation | Default (unlimited) | JSON-file driver, 10 MB x 3-5 files |
| Gunicorn | Basic config | `--preload`, `--max-requests 1000`, recycling |
| Healthchecks | Basic intervals | Added `start_period` (40s web, 60s predictor) |
| Trader safety | None | `ENABLE_LIVE_TRADING=false` hard override |

**With monitoring stack:**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  -f docker-compose.monitoring.yml up -d --build
```

### Service Health Checks

```bash
# Web UI
curl http://localhost:5000/health

# Prediction API
curl http://localhost:5001/health

# Redis
docker compose exec redis redis-cli ping
```

## Environment Variables

### Required for Production

| Variable | Description |
|---|---|
| `SECRET_KEY` | Random 64-char string for Flask sessions |
| `ENV` | Set to `production` |
| `DATABASE_URL` | PostgreSQL connection string (or leave default for SQLite) |
| `MAIL_SERVER` | SMTP server for emails |
| `MAIL_USERNAME` | SMTP username |
| `MAIL_PASSWORD` | SMTP password |
| `METAAPI_TOKEN` | MetaApi cloud API token |
| `METAAPI_ACCOUNT_ID` | MetaApi MT5 account ID |

### Optional

| Variable | Description |
|---|---|
| `REDIS_URL` | Redis connection string (defaults to `redis://redis:6379/0`) |
| `USE_REDIS` | Set to `true` for multi-container setups |
| `STRIPE_SECRET_KEY` | Stripe API key for payments |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `ANTHROPIC_API_KEY` | Claude API key (optional) |
| `TELEGRAM_BOT_TOKEN` | Telegram alerts bot token |

## SSL/TLS with Caddy

```bash
# Install Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

Create `/etc/caddy/Caddyfile`:
```
trading.yourdomain.com {
    reverse_proxy localhost:5000
    encode gzip
    header Strict-Transport-Security "max-age=31536000; includeSubDomains"
}
```

## Database Setup

### SQLite (Default, Development)

No setup required. Database is created automatically at `instance/users.db`.

### PostgreSQL (Production)

```bash
# Install PostgreSQL
sudo apt install postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql -c "CREATE USER tfe WITH PASSWORD 'strong-password';"
sudo -u postgres psql -c "CREATE DATABASE tfe OWNER tfe;"

# Update .env
DATABASE_URL=postgresql://tfe:strong-password@localhost:5432/tfe
```

Run migrations:
```bash
docker compose run --rm web python -c "from db_utils import run_migrations; run_migrations()"
```

## Monitoring

### Unified Health Check

```bash
# Check all services at once (exit code 0 = healthy)
./scripts/healthcheck.sh

# Single service only
./scripts/healthcheck.sh --service web

# Silent mode for cron / UptimeRobot
./scripts/healthcheck.sh --quiet
```

### Prometheus + Grafana Stack

Start the monitoring stack alongside the main services:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  -f docker-compose.monitoring.yml up -d --build
```

**Access:**
- Grafana: `http://localhost:3000` (default: admin / admin)
- Prometheus: `http://localhost:9090`
- cadvisor (container metrics): `http://localhost:8080`
- Node Exporter (host metrics): `http://localhost:9100`

The stack auto-configures:
- Prometheus scrapes the web `/health` and predictor `/health` endpoints
- cadvisor collects per-container CPU, memory, disk, and network
- Node exporter collects host-level metrics
- Grafana datasource (Prometheus) is provisioned automatically

Dashboard JSON files placed in `monitoring/grafana/dashboards/` are auto-loaded.

### Log Rotation

The production compose file already configures log rotation per service
(JSON-file driver, max 10 MB x 3-5 files). No daemon-level config needed.
For global settings, add to `/etc/docker/daemon.json`.

## Backup Strategy

### Database Backup (Daily Cron)

```bash
#!/bin/bash
# Daily cron entry (02:00):
# 0 2 * * * cd /opt/tfe && ./scripts/backup.sh >> logs/backup.log 2>&1

# Local backup (DB + models)
./scripts/backup.sh

# With S3 upload
./scripts/backup.sh --upload
```

### Restoring from Backup

```bash
# Restore from local backup
./scripts/restore.sh
```

### Model Versioning

Models are tracked in the `model_version` table with feature and data hashes for full reproducibility:
```python
from db_utils import create_model_version, get_model_versions
create_model_version("AAPL", "rf", metrics, "rf_model_AAPL.pkl", feature_list, data_hash)
```

## Performance Tuning

### Gunicorn Workers

In `docker-compose.yml`, adjust workers based on CPU cores:
```yaml
command: gunicorn --workers $((2 * $(nproc) + 1)) --bind 0.0.0.0:5000 wsgi:app
```

### Redis Cache

Enable Redis for session storage and caching:
```
USE_REDIS=true
REDIS_URL=redis://redis:6379/0
```

### Static Assets

Serve static files through Caddy or CDN for better performance.

## Troubleshooting

### Services Won't Start
```bash
docker compose logs web        # Check web service errors
docker compose logs redis      # Check Redis connectivity
```

### Database Issues
```bash
docker compose exec web python -c "from extensions import db; from app import create_app; app=create_app(); app.app_context().push(); db.create_all()"
```

### Trading Engine Errors
```bash
docker compose logs trader
# Common issues: invalid MetaApi token, MT5 bridge not running, rate limits
```

### Model Loading Failures
Check that `Saved Models/` directory contains the required `.pkl` files and is mounted correctly in Docker volumes.

## Scaling

### Multi-Server Architecture

For high-availability production:
1. **Load Balancer**: HAProxy or Nginx in front of multiple `web` containers
2. **Database**: Managed PostgreSQL (AWS RDS, DigitalOcean, etc.)
3. **Redis**: Managed Redis (Elasticache, Redis Cloud)
4. **File Storage**: S3/Azure Blob for models and data
5. **CDN**: Cloudflare for static assets

### Environment-Specific docker-compose files

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Security Checklist

- [ ] `SECRET_KEY` set to a strong random value
- [ ] HTTPS enabled via Caddy/nginx
- [ ] Firewall configured (only ports 80/443 open)
- [ ] Database password is strong and unique
- [ ] API keys are not committed to git
- [ ] `.env` is in `.gitignore`
- [ ] Docker runs as non-root user
- [ ] Regular security updates (`apt update && apt upgrade`)
- [ ] Rate limiting enabled for API endpoints
- [ ] Session cookies set to `Secure` and `HttpOnly`