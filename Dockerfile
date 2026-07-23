# ── Stage 1: Build React Frontend ──────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --silent || npm install

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Build Python Virtual Environment ──────────────────────────────────
FROM python:3.11-slim-bookworm AS python-builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make libffi-dev libssl-dev libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Stage 3: Minimal Production Runtime ─────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies
COPY --from=python-builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy built React frontend assets into /app/frontend/dist
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Copy application source code
COPY . .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

WORKDIR /app/django_backend

# Collect static files for Django + Whitenoise
RUN python manage.py collectstatic --noinput --clear 2>/dev/null || true

EXPOSE 8080
ENV PORT=8080
ENV PYTHONPATH="/app:/app/django_backend"

CMD ["sh", "-c", "python manage.py migrate --noinput 2>/dev/null || true && gunicorn --bind 0.0.0.0:${PORT} --workers 4 --timeout 120 bulllogic.wsgi:application"]
