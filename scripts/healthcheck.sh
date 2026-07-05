#!/usr/bin/env bash
# ── Triple-Fusion-Engine Health Check Script ──────────────────────────────────
#
# Checks all services and exits 0 if healthy, 1 if any fail.
# Suitable for cron monitoring, UptimeRobot, or pre-deploy smoke tests.
#
# Usage:
#   ./scripts/healthcheck.sh                    # check all
#   ./scripts/healthcheck.sh --quiet            # no output, exit code only
#   ./scripts/healthcheck.sh --service web      # check single service
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

QUIET=false
SERVICE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --quiet|-q) QUIET=true; shift ;;
        --service|-s) SERVICE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

log()   { $QUIET || echo "$@"; }
pass()  { $QUIET || echo "  ✓ $1"; }
fail()  { $QUIET || echo "  ✗ $1"; return 1; }

FAILURES=0

# ── Helpers ──────────────────────────────────────────────────────────────────

check_http() {
    local name="$1" url="$2" expect="${3:-200}"
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$url" 2>/dev/null || echo "000")
    if [[ "$code" == "$expect" ]]; then
        pass "$name ($code)"
    else
        fail "$name (expected $expect, got $code)"
    fi
}

check_tcp() {
    local name="$1" host="$2" port="$3"
    if timeout 5 bash -c "echo >/dev/tcp/${host}/${port}" 2>/dev/null; then
        pass "$name (${host}:${port})"
    else
        fail "$name (${host}:${port} unreachable)"
    fi
}

# ── Service Checks ───────────────────────────────────────────────────────────

if [[ -z "$SERVICE" ]] || [[ "$SERVICE" == "redis" ]]; then
    log "Redis:"
    if docker exec tfe-redis redis-cli ping 2>/dev/null | grep -q PONG; then
        pass "redis PONG"
    else
        fail "redis PING failed"
    fi
fi

if [[ -z "$SERVICE" ]] || [[ "$SERVICE" == "web" ]]; then
    log "Web (Flask):"
    check_http "web /health" "http://localhost:5000/health"
    check_http "web /login"  "http://localhost:5000/login" "200"
fi

if [[ -z "$SERVICE" ]] || [[ "$SERVICE" == "predictor" ]]; then
    log "Predictor:"
    check_http "predictor /health" "http://localhost:5001/health"
fi

if [[ -z "$SERVICE" ]] || [[ "$SERVICE" == "trader" ]]; then
    log "Trader:"
    if docker ps --format '{{.Names}}' | grep -q "tfe-trader"; then
        STATUS=$(docker inspect -f '{{.State.Status}}' tfe-trader 2>/dev/null || echo "missing")
        if [[ "$STATUS" == "running" ]]; then
            pass "trader container running"
        else
            fail "trader container status: ${STATUS}"
        fi
    else
        fail "tfe-trader container not found"
    fi
fi

if [[ -z "$SERVICE" ]] || [[ "$SERVICE" == "prometheus" ]]; then
    log "Prometheus:"
    check_http "prometheus /-/healthy" "http://localhost:9090/-/healthy"
fi

if [[ -z "$SERVICE" ]] || [[ "$SERVICE" == "grafana" ]]; then
    log "Grafana:"
    check_http "grafana /api/health" "http://localhost:3000/api/health"
fi

# ── Summary ──────────────────────────────────────────────────────────────────

log ""
log "Disk usage:"
df -h /var/lib/docker 2>/dev/null || df -h / 2>/dev/null || true

if [[ "$FAILURES" -eq 0 ]]; then
    log "✓ All services healthy"
    exit 0
else
    log "✗ ${FAILURES} check(s) failed"
    exit 1
fi
