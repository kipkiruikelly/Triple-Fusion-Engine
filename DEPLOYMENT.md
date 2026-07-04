# Deployment Guide — Triple-Fusion-Engine

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

### Health Check Endpoint

```
GET /health
Response: {"status": "ok", "uptime_seconds": 3600, "version": "3.0.0"}
```

### Docker Monitoring

```bash
# Container status
docker compose ps

# Resource usage
docker stats

# Logs
docker compose logs -f --tail=100 web
docker compose logs -f --tail=100 trader
```

### Log Rotation

Add to `/etc/docker/daemon.json`:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "5"
  }
}
```

## Backup Strategy

### Database Backup (Daily Cron)

```bash
#!/bin/bash
# /etc/cron.daily/backup-tfe
BACKUP_DIR=/backups/tfe
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d)

# SQLite backup
cp instance/users.db $BACKUP_DIR/users_$DATE.db

# Model backup
tar -czf $BACKUP_DIR/models_$DATE.tar.gz "Saved Models/"

# Keep last 30 days
find $BACKUP_DIR -mtime +30 -delete
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
