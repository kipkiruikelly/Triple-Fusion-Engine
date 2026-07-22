# ── Triple-Fusion-Engine Base Image ──────────────────────────────────────────────
# Multi-stage build: builder stage compiles dependencies, runtime is minimal.
#
# Build:
#   docker build -t triple-fusion-engine .
#
# Run:
#   docker run -p 5000:5000 --env-file .env triple-fusion-engine
#
# Services (override CMD per service):
#   docker run ... triple-fusion-engine python data_pipeline.py
#   docker run ... triple-fusion-engine python app.py

FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# System deps for TA-Lib / numpy / TensorFlow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps in a venv
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ── Runtime Stage ────────────────────────────────────────────────────────────────

FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

# Cloud Run injects PORT env var (default 8080). We honour it so the
# health check passes. Locally you can override: -e PORT=5000
EXPOSE 8080
ENV PORT=8080
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 4 --timeout 120 wsgi:app"]
