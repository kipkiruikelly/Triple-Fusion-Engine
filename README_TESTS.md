# BullLogic Test Suite

Comprehensive test suite covering all Phase 1-4 modules with pytest.

## Current status

- Total tests: 435
- Result: 435 passed, 0 failed
- Last full run: 2026-07-13
- How to run: `python run_tests.py` (or `pytest tests/ -q`)

## Quick Start

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-html pytest-mock coverage

# Run all tests
python run_tests.py

# Run specific module
python run_tests.py --module risk
python run_tests.py --module sentiment
python run_tests.py --module ml

# Run with verbose output
python run_tests.py --module risk --verbose --log-level DEBUG

# Run with coverage
python run_tests.py --coverage

# Generate HTML report
python run_tests.py --html report.html

# Run a single test file directly
pytest tests/test_risk_manager.py -v
pytest tests/test_smart_router.py -v
```

## Test Modules

| Module Flag | Test File(s) | What's Tested |
|---|---|---|
| `risk` | `test_risk_manager.py` | Kelly criterion, trailing stops, volatility adjustment, drawdown tiers, guardrails, position sizing, trade history |
| `smart` | `test_smart_router.py` | TWAP/VWAP/Iceberg execution, market impact estimation, optimal chunk sizing, volume profiles |
| `sentiment` | `test_sentiment.py` | VADER lexicon scoring, news API integration, composite sentiment, signal generation |
| `calendar` | `test_economic_calendar.py` | Event filtering, impact scoring, volatility warnings, high-impact detection |
| `quality` | `test_data_quality.py` | DataFrame validation, OHLC consistency, staleness checks, feature matrix validation |
| `gamification` | `test_gamification.py` | Competitions, leaderboards, achievements, performance reports |
| `config` | `test_config.py` | Pydantic settings, environment presets, secret exclusion |
| `walk_forward` | `test_walk_forward.py` | Purged train/test splits, fold metrics computation |
| `ml` | `test_stacking_ensemble.py`, `test_data_pipeline.py` | Model evaluation metrics, feature importance, data cleaning, ICT features, train/val/test splits |
| `auth` | `test_auth.py`, `test_auth_flows.py` | Authentication, registration, login flows |
| `admin` | `test_admin.py` | Admin panel access control |
| `payments` | `test_payments.py` | Stripe/M-Pesa payment flows |
| `all` | All test files | Full test suite |

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures (app, db, client, sample data)
├── mock_data.py             # Mock OHLCV, trades, accounts, predictions
├── test_risk_manager.py     # Phase 3: Risk management
├── test_smart_router.py     # Phase 3: Smart order routing
├── test_sentiment.py        # Phase 4: Sentiment analysis
├── test_economic_calendar.py # Phase 4: Economic calendar
├── test_data_quality.py     # Phase 4: Data quality monitoring
├── test_gamification.py     # Phase 4: Gamification engine
├── test_config.py           # Phase 2: Centralized config
├── test_walk_forward.py     # Phase 1: Walk-forward analysis
├── test_stacking_ensemble.py # Phase 1: ML stacking ensemble
├── test_data_pipeline.py    # Phase 1-2: Data pipeline
├── test_alphas.py           # Existing: Alpha library
├── test_paper_engine.py     # Existing: Paper trading
├── test_auth.py             # Existing: Authentication
├── test_admin.py            # Existing: Admin panel
├── test_payments.py         # Existing: Payments
├── test_quota.py            # Existing: Quota system
├── test_theme.py            # Existing: Theme preferences
├── test_ethics.py           # Existing: Ethics checks
├── test_accuracy.py         # Existing: Prediction accuracy
└── test_pyth.py             # Existing: Pyth oracle
```

## Writing New Tests

1. Import fixtures from `conftest.py`:
   ```python
   def test_something(sample_df, risk_manager_instance):
       ...
   ```

2. Use `mock_data.py` for realistic test data:
   ```python
   from tests.mock_data import sample_trades, sample_ohlcv
   ```

3. Mock external APIs:
   ```python
   from unittest.mock import patch
   with patch("requests.get") as mock_get:
       mock_get.return_value.status_code = 200
   ```

4. Follow existing patterns: one test class per module, one method per scenario.

## CI/CD Integration

```yaml
# GitHub Actions example
- name: Run tests
  run: |
    pip install pytest pytest-cov pytest-html
    python run_tests.py --coverage --html report.html
```

## Fixtures Reference

| Fixture | Returns | Source |
|---|---|---|
| `sample_df` | 200-bar OHLCV DataFrame | `mock_data.sample_ohlcv` |
| `sample_trades_fixture` | 50 trade dicts | `mock_data.sample_trades` |
| `sample_account_fixture` | Account dict ($10k) | `mock_data.sample_account` |
| `risk_manager_instance` | Fresh RiskManager | `risk_manager.RiskManager` |
| `competition_engine` | Fresh CompetitionEngine | `gamification.CompetitionEngine` |
| `data_quality_monitor` | Fresh DataQualityMonitor | `data_quality.DataQualityMonitor` |
| `smart_router` | SmartOrderRouter with mock trader | `smart_router.SmartOrderRouter` |
| `mock_trader` | MagicMock MT5Trader | `unittest.mock.MagicMock` |
