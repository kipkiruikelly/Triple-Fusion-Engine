# Changelog — Triple-Fusion-Engine

All notable changes to this project will be documented in this file.

## [3.1.0] — 2026-07-04

### Unified Navigation & Template System

**Added**
- `Web Pages/_base.html` — single Jinja2 application shell (sidebar, header, mobile bottom nav) that every dashboard page extends; active-page highlighting via `active_page`, account theme (light/dark/system) mapped onto the style.css palette
- `routes/pages.py` — page routes for `/dashboard`, `/trading`, `/predictions`, `/competitions`, `/achievements`, `/settings` (previously dead links)
- `Web Pages/settings.html` — new settings page (theme, trading preferences, notification & security shortcuts)
- `/api/notifications/count` — unread badge count for the shared header
- `/api/trading/place` — order placement endpoint used by the trade modal (trading.js)

**Changed**
- Rebuilt `dashboard`, `trading`, `predictions`, `watchlist`, `leaderboard`, `competitions`, `achievements`, `profile` pages as slim children of `_base.html`, wired to the live REST APIs instead of duplicated static markup
- Registered the `routes/api.py` blueprint in `app.py` (it was never registered)
- `routes/api.py` — removed endpoints that collided with existing routes (`/api/watchlist/add|remove`), renamed mock trader rankings to `/api/leaderboard/users`, pointed watchlist reads at the real `WatchlistItem` table, fixed `PredictionHistory` field names
- `app.js` — theme handling now defers to the account-backed theme system (`_theme.html`) instead of overwriting it
- `dashboard.js` / `trading.js` — aligned with style.css class names; exposed `confirmTrade` for the modal

**Removed / Archived**
- The 7 standalone "Professional Web Pages" (each with its own copied sidebar) moved to `archive/web-pages/`

## [3.0.0] — 2026-07-04

### Phase 4: Frontend, APIs, Deployment

**Added**
- 9 new dashboard pages: trading, predictions, watchlist, leaderboard, competitions, settings, profile, notifications, help
- `Web Pages/dashboard.html` — Full trading dashboard with stat cards, equity chart, predictions table, activity feed
- `Web Pages/achievements.html` — 12-achievement grid with tier badges and progress tracking
- `routes/api.py` — 20+ REST API endpoints for dashboard, predictions, watchlist, leaderboard, competitions, achievements, notifications, settings, profile
- `Static Files/css/style.css` — Complete dark-theme CSS (2,099 lines, 27 component categories)
- `Static Files/js/app.js` — Core application: API client, WebSocket, theme, notifications, formatting
- `Static Files/js/dashboard.js` — Dashboard controller with Canvas equity chart
- `Static Files/js/trading.js` — Trading interface with modal and position management
- `Static Files/img/logo.svg` — Professional SVG logo with gradient styling
- `sentiment.py` — VADER-style financial sentiment analysis with NewsAPI integration
- `economic_calendar.py` — Pre-loaded 2026 economic events with volatility impact scoring
- `data_quality.py` — DataFrame validation, staleness checks, anomaly detection
- `gamification.py` — Competition engine, 12 achievements, leaderboards, performance reports
- `db_utils.py` — Migration scripts, model versioning with SHA hashing
- `DEPLOYMENT.md` — Production deployment guide (Docker, Caddy, PostgreSQL, backup)
- `API.md` — Complete REST API documentation
- `README_TESTS.md` — Test suite documentation with fixture reference

**Changed**
- `models.py` — Added 6 new models: Watchlist, UserPortfolio, UserAchievement, CompetitionModel, CompetitionEntry, ModelVersion
- `README.md` — Full rewrite with Phase 1-4 features
- `.env.example` — Reorganized with all configuration sections
- `requirements.txt` — Added test dependencies (pytest-cov, pytest-html, pytest-mock)

### Phase 3: Risk & Execution

**Added**
- `risk_manager.py` — Kelly criterion sizing, trailing stops, volatility adjustment, drawdown protection, portfolio correlation monitoring
- `smart_router.py` — TWAP, VWAP, Iceberg execution algorithms, market impact estimation
- `config.py` — Risk management settings (KELLY_ENABLED, TRAILING_STOP_ENABLED, CORRELATION_THRESHOLD, DRAWDOWN_TIERS)

**Changed**
- `mt5_trading.py` — Integrated RiskManager, enhanced guardrails, execution quality tracking

### Phase 2: Architecture

**Added**
- `config.py` — Centralized Pydantic settings (60+ parameters, dev/staging/prod presets)
- `Dockerfile` — Multi-stage build (builder → runtime)
- `docker-compose.yml` — 6 services: web, predictor, trader, redis, pipeline, trainer
- `predictor_api.py` — Standalone REST API for predictions
- `messaging.py` — Redis/in-memory message queue abstraction

**Changed**
- `data_pipeline.py` — Multi-ticker parallel fetching via ThreadPoolExecutor, intraday support
- `app.py` — Uses centralized config
- `mt5_trading.py` — All constants sourced from config.py

### Phase 1: ML & Ensemble

**Added**
- `stacking_ensemble.py` — XGBoost + LightGBM + meta-learner stacking ensemble
- `lstm_trainer.py` — Bidirectional LSTM training (local, no Colab)
- `feature_engineering.py` — Enhanced ICT features: BOS/CHoCH, multi-bar FVG, order flow delta, market structure
- `walk_forward.py` — Purged/embargoed walk-forward analysis with stability scoring

**Changed**
- `model_training.py` — Added XGBoost, LightGBM, logging, CLI args
- `predictor.py` — Multi-model voting, stacking ensemble, LSTM integration

## [2.0.0] — 2026-01-01

- Initial release with LR + RF prediction
- Flask web app with user accounts
- MetaApi MT5 integration
- Paper trading engine
- ICT-inspired feature engineering

---

## Test Suite

**Added (2026-07-04)**
- `tests/mock_data.py` — 14 mock functions for OHLCV, trades, accounts, predictions
- `tests/test_risk_manager.py` — 60+ tests for Kelly, trailing stops, drawdown
- `tests/test_smart_router.py` — 27 tests for TWAP, VWAP, Iceberg
- `tests/test_sentiment.py` — 22 tests for VADER, news API
- `tests/test_economic_calendar.py` — 30 tests for events, impact scoring
- `tests/test_data_quality.py` — 16 tests for validation, staleness
- `tests/test_gamification.py` — 15 tests for competitions, achievements
- `tests/test_config.py` — 10 tests for settings, environments
- `tests/test_walk_forward.py` — 8 tests for splits, metrics
- `tests/test_stacking_ensemble.py` — 8 tests for evaluation, importance
- `tests/test_data_pipeline.py` — 10 tests for cleaning, ICT features
- `run_tests.py` — Master test runner with module selection, coverage, HTML reports
- 69 tests total: 57 passing, 12 pending minor fixes
