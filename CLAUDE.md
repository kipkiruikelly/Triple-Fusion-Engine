# Stock Market Price Prediction System — Claude Code Instructions
# Kelvin Kipkirui | DAC-01-0010/2025 | Zetech University
# GitHub: kipkiruikelly/Stock-Market-Predictor

## PROJECT OVERVIEW
ML-based Quantitative Trading System — a Python ML web application that predicts the next trading day's closing price for any listed stock ticker using Linear Regression, Random Forest, and LSTM models. Built with Flask and deployed on Render. Developed as a diploma project for the Diploma in AI and Cloud Technologies (DAC) programme at Zetech University, Kenya.

---

## WHAT HAS BEEN BUILT (DO NOT BREAK THESE)

### Core Python files
- `app.py` — Flask web app. Auth via Flask-Login + SQLAlchemy. Per-ticker model cache with Azure fallback. Routes: /login, /register, /logout, /, /predict, /api/predict/<ticker>, /health, /metrics. Monitoring counters in `_metrics` dict. Request timing via `g`.
- `auth.py` — Lightweight SQLite auth module (session-based alternative). DB: Data/users.db. Functions: init_db(), create_user(), verify_user().
- `predictor.py` — Shared ML inference layer. Loads LR+RF models, fetches live yfinance data, engineers 25 features, returns prediction dict. Used by app.py and trading loop.
- `data_pipeline.py` — Downloads 5y OHLCV, engineers 19 features using `ta` library, saves to Data/.
- `model_training.py` — Trains LR + RF on AAPL with 25 features. Saves to Saved Models/.
- `train_all_tickers.py` — Trains LR+RF for 9 tickers (AAPL TSLA MSFT GOOGL NVDA META AMZN NDX QQQ) in parallel (~16s daily, ~21s 1h). Supports `--interval 1d|1h|15m`, `--upload`, `--fast`, `--workers`. Daily models: 45 features (TA + ICT). 1h models: 55 features (+ kill zones + session). Model files use suffix: `_1h.pkl` for intraday, no suffix for daily.
- `azure_storage.py` — Azure Blob Storage integration. Container: trained-models. Auth: AZURE_STORAGE_CONNECTION_STRING env var. Functions: upload_models_to_azure(), download_models_from_azure(), list_models_in_azure(), azure_enabled().
- `mt5_trading.py` — MT5/MetaApi/Paper trading engine for Pro users.

### Web Pages (stored in `Web Pages/` — do not rename)
- `index.html` — Dark financial dashboard. Orange accent (#FF6B35).
- `result.html` — Prediction results with TradingView chart, model comparison, indicator cards.
- `login.html` — Dark-themed login form.
- `register.html` — Dark-themed registration form.
- `pricing.html` — Subscription pricing page.
- `mt5.html` — MT5 algorithmic trading dashboard (Pro only).

### Infrastructure
- `Dockerfile` — Python 3.11-slim, non-root appuser, Gunicorn on port 5000.
- `.dockerignore` — Excludes venv/, __pycache__, .git, notebooks, .DS_Store, .env, logs.
- `.python-version` — 3.11.9 (pins for Render).
- `Procfile` — web: gunicorn app:app
- `requirements.txt` — Pinned versions. Key: flask==3.0.3, ta==0.11.0, azure-storage-blob==12.19.0.

### Saved Models — Daily (1d, 45 features, LR→price / RF→return)
- AAPL: LR MAE $3.36 R2=0.9444 | RF MAE $3.45
- QQQ:  LR MAE $4.74 R2=0.9946 | RF MAE $4.76  (6,829 bars, 27y history)
- NDX:  LR MAE $180 R2=0.9975  | RF MAE $239   (10,225 bars, 40y history)
- LSTM: N/A locally (TensorFlow not compatible with Python 3.13)

### Saved Models — Intraday (1h, 55 features, includes ICT kill zones)
- AAPL: LR MAE $1.07 R2=0.9935 | RF MAE $1.04  (5,048 bars, 730d)
- QQQ:  LR MAE $2.08 R2=0.9969 | RF MAE $2.07  (5,048 bars, 730d)
- NDX:  LR MAE $85  R2=0.9969  | RF MAE $87    (5,048 bars, 730d)
- Top ICT feature on 1h: Price_vs_MidnightOpen (#1 both QQQ+AAPL, ~10-12% importance)

### ICT Feature Performance by Timeframe
- Daily (1d): Dist_200SMA, Dist_PWH, Body_Ratio, Dist_to_SH work best
- 1h intraday: Price_vs_MidnightOpen, Session_High/Low_Dist, Hour_Sin work best
- FVG/OB/Swept features are weak on daily — meaningful only on 1h or lower

---

## IMPORTANT CONSTRAINTS

### Never change these
- `ta` library — do NOT switch to pandas_ta
- `template_folder="Web Pages"` — do not rename folder
- `static_folder="Static Files"` — do not rename folder
- `Saved Models/` and `Data/` folder names
- Real model metrics above — these are actual test-set results

### Azure Storage
- Container: `trained-models` (private)
- Auth: `AZURE_STORAGE_CONNECTION_STRING` env var
- Files per ticker: lr_model_{T}.pkl, rf_model_{T}.pkl, scaler_sklearn_{T}.pkl, feature_cols_sklearn_{T}.pkl
- app.py tries Azure download as fallback if local model files missing

### Flask config
- `@login_required` protects `/` and `/predict`
- `session["username"]` / Flask-Login both supported
- `auth.py` stays as separate module

---

## ENVIRONMENT
- Dev: MacBook Air (Apple Silicon), Python 3.13 via Anaconda
- TensorFlow does NOT work locally — LSTM shows N/A in UI
- Deployment: Render, Python 3.11.9
- Local run: `python app.py` → http://127.0.0.1:5000
- Docker: `docker build -t stock-predictor . && docker run -p 5000:5000 stock-predictor`
- Train daily (all 9, ~16s):     `python train_all_tickers.py`
- Train 1h intraday (~21s):       `python train_all_tickers.py --interval 1h`
- Train fast (RF-50/d6):          `python train_all_tickers.py --fast`
- Train subset + upload:          `python train_all_tickers.py --tickers QQQ NDX --upload`
