# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ML-based Quantitative Trading System — a Python ML project that predicts next-day closing prices using Linear Regression, Random Forest, and LSTM models, served via a Flask web app.

**Author:** Kelvin Kipkirui | DAC-01-0010/2025 | Zetech University

## Environment

Uses the Anaconda `base` environment (Python 3.13). TensorFlow is **not compatible with Python 3.13**, so the LSTM model is trained on Google Colab only.

```bash
# Activate base conda env if not already active
conda activate base

# Install dependencies
pip install -r requirements.txt
```

## Workflow (must run in order)

**Step 1 — Data pipeline** (downloads OHLCV data, engineers features, saves to `Data/`)
```bash
python data_pipeline.py
```

**Step 2 — Train sklearn models** (Linear Regression + Random Forest, saves to `Saved Models/`)
```bash
python model_training.py
```

**Step 2b — LSTM training** — open `Step2_LSTM_Training.ipynb` in Google Colab and run all cells. Download `lstm_model_AAPL.keras` and place it in `Saved Models/`.

**Step 3 — Run the Flask app**
```bash
python app.py          # development (http://127.0.0.1:5000)
flask run              # alternative
gunicorn app:app       # production (Procfile)
```

## Architecture

### Data Flow
```
data_pipeline.py  →  Data/AAPL_featured.csv + .npy arrays + scaler_AAPL.pkl
model_training.py →  Saved Models/lr_model_AAPL.pkl + rf_model_AAPL.pkl + scaler_sklearn_AAPL.pkl
app.py            ←  loads models at startup, fetches live 6-month data via yfinance per request
```

### Two Separate Scalers
- `Data/scaler_AAPL.pkl` — fit on the LSTM pipeline's 19 raw OHLCV+indicator features
- `Saved Models/scaler_sklearn_AAPL.pkl` — fit on the sklearn pipeline's 25 features (adds 5 Close lags + 3 Return lags, drops Open and BB_Mid)

These are not interchangeable. `app.py` uses the sklearn scaler.

### Flask App (`app.py`)
- Templates in `Web Pages/` (not `templates/`), static files in `Static Files/`
- Models loaded once at startup via `joblib.load()`
- `POST /predict` — form submission, returns `result.html`
- `GET /api/predict/<ticker>` — JSON API (omits chart data from response)
- `build_features()` replicates feature engineering from `data_pipeline.py` for live inference
- LSTM prediction slot exists but returns `"N/A"` — the keras model is loaded only if integrated later

### Configuration Constants
Both `data_pipeline.py` and `model_training.py` have a `TICKER = "AAPL"` constant at the top. Change it to run the pipeline for a different stock. The app accepts any ticker via form/API input at runtime.

### Target Variable
`model_training.py` predicts `Next_Close` (tomorrow's closing price via `df["Close"].shift(-1)`). The confidence score in `app.py` is a heuristic based on predicted change relative to recent 20-day volatility.
