# BullLogic API Documentation

Base URL: `https://your-domain.com/api`

All endpoints return JSON. Authenticated endpoints require a valid session cookie (Flask-Login) or Bearer token.

## Authentication

```
POST /login
Content-Type: application/x-www-form-urlencoded

identifier=username&password=yourpass

Response: redirect to /dashboard on success
```

Session is maintained via cookie. For API-only access, include `Authorization: Bearer <token>` header.

---

## Dashboard

### GET /api/dashboard
Returns aggregated dashboard data.

**Response:**
```json
{
  "ok": true,
  "data": {
    "portfolio": {
      "equity": 10250.00,
      "balance": 10000.00,
      "daily_pnl": 125.50,
      "change_pct": 1.26,
      "win_rate": 58.3,
      "open_positions": 2
    },
    "predictions_today": 3,
    "plan": "pro"
  }
}
```

---

## Predictions

### GET /api/predictions/recent?limit=5
Returns recent prediction history.

### POST /api/predictions/signal
Generate a live prediction signal.

**Request:**
```json
{"ticker": "AAPL", "interval": "1d"}
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "ticker": "AAPL",
    "direction": "Up",
    "confidence": 72.5,
    "predicted_price": 195.30,
    "models": {"lr": 193.0, "rf": 196.5, "xgb": 194.2, "lgb": 195.8, "stacking": 195.3},
    "sentiment": {"bias": "bullish", "score": 0.45, "magnitude": 0.6},
    "economic_warning": {"level": "none"}
  }
}
```

---

## Watchlist

### GET /api/watchlist
Returns user's watchlist with current prices.

### POST /api/watchlist/add
Add a ticker. Body: `{"ticker": "AAPL", "notes": "Tech giant"}`

### POST /api/watchlist/remove
Remove a ticker. Body: `{"ticker": "AAPL"}`

---

## Leaderboard

### GET /api/leaderboard?period=all-time&limit=50&metric=return_pct

**Parameters:**
- `period`: `weekly`, `monthly`, `all-time`
- `limit`: Number of entries (max 100)
- `metric`: `return_pct`, `sharpe`, `win_rate`

**Response:**
```json
{
  "ok": true,
  "data": {
    "leaderboard": [
      {"rank": 1, "username": "AlphaTrader", "return_pct": 34.5, "sharpe": 2.1, "win_rate": 68.0, "trades": 156, "equity": 13450.0}
    ],
    "period": "all-time",
    "total_participants": 342
  }
}
```

---

## Competitions

### GET /api/competitions?status=active
List competitions. Status: `active`, `upcoming`, `completed`, `all`.

### GET /api/competitions/:id/leaderboard
Leaderboard for a specific competition.

---

## Achievements

### GET /api/achievements/user
User's achievement progress.

**Response:**
```json
{
  "ok": true,
  "data": {
    "unlocked": ["first_trade", "ten_trades", "win_streak_5"],
    "total": 12,
    "points": 30
  }
}
```

---

## Notifications

### GET /api/notifications
List user notifications.

### POST /api/notifications/mark-read
Body: `{"id": 1}` or `{"all": true}`

---

## Settings

### GET /api/settings
Current user preferences.

### POST /api/settings
Update preferences. Body: `{"theme": "dark", "default_ticker": "NVDA"}`

---

## Profile

### GET /api/profile
User profile with subscription info.

---

## Market Data

### GET /api/market/movers?limit=5
Top market movers.

### GET /api/activity/recent?limit=10
Recent user activity feed.

---

## Portfolio

### GET /api/portfolio
Portfolio summary.

### GET /api/portfolio/equity-curve
90-day equity curve data for charts.

---

## Trading

### GET /api/trading/positions
Open positions list.

### GET /api/trading/orders?limit=20
Order history.

---

## Health Check

### GET /health
```json
{"status": "ok", "uptime_seconds": 3600, "version": "3.0.0"}
```

### GET /api/predictor/health (predictor service, port 5001)
```json
{"status": "ok", "service": "predictor-api", "ml_available": true}
```

---

## Error Responses

All errors follow this format:
```json
{"ok": false, "error": "Human-readable error message"}
```

HTTP status codes:
- `400` - Bad request (missing parameters)
- `401` - Unauthorized (login required)
- `403` - Forbidden (insufficient permissions)
- `429` - Rate limited
- `500` - Internal server error
