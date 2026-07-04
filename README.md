# Triple-Fusion-Engine — Stock Market Prediction & Algorithmic Trading System

**BullLogic**

A production-grade machine-learning web application that predicts next-day stock closing prices and executes algorithmic trades automatically. **Phase 1** upgrades the ML stack from simple LR+RF fusion to a full stacking ensemble with XGBoost, LightGBM, local LSTM training, enhanced ICT-inspired features, and robust walk-forward backtesting.

---

## Features

- **Stacking Ensemble ML**, XGBoost + LightGBM + Random Forest + Linear Regression with Ridge meta-learner
- **LSTM Neural Network**, Local training with bidirectional LSTM, dropout, early stopping (no Colab required)
- **ICT-Inspired Features**, Order Blocks, FVGs, BOS/CHoCH, Order Flow Delta, Market Structure analysis
- **Walk-Forward Backtesting**, Purged/embargoed time-based splits, fold-level metrics, stability scoring
- **Technical Analysis**, RSI, MACD, Bollinger Bands, EMA, ATR computed live from yfinance data
- **TradingView Charts**, Interactive live chart with RSI and MACD studies for any ticker
- **User Accounts**, Registration, login, subscription tiers (Free: 5 predictions/day, Pro: unlimited)
- **Algorithmic Trading**, ML-fused signals automatically placed as real or paper trades
- **MetaApi Integration**, Connect to any MT5 broker from Mac, Linux, or Windows without Wine
- **Paper Trading**, $10,000 virtual account with real market data; no broker needed
- **Risk Management**, ATR-based SL/TP (1.5× / 3×), 1% risk per trade, 5% daily loss circuit-breaker

---

## Architecture (Phase 1 Enhanced)

```
data_pipeline.py      →  Data/AAPL_featured.csv + numpy arrays + enhanced ICT features
feature_engineering.py →  BOS/CHoCH, Enhanced FVG, Order Flow, Market Structure
model_training.py     →  Saved Models/lr_model_AAPL.pkl + rf_model_AAPL.pkl + xgb + lgb
stacking_ensemble.py  →  Saved Models/stacking_meta_AAPL.pkl (Ridge meta-learner)
lstm_trainer.py       →  Saved Models/lstm_model_AAPL.h5 (bidirectional LSTM)
predictor.py          →  shared ML inference layer (uses all models + stacking ensemble)
walk_forward.py       →  Walk-forward analysis with purged splits and stability scoring
app.py                →  Flask web app (auth, predictions, MT5 routes)
mt5_trading.py        →  trading engine (MetaApi / paper / direct MT5 bridge)
```

### Model Hierarchy
| Model | Target | Role |
|---|---|---|
| Linear Regression | Next close price | Baseline, stable |
| Random Forest | Next return % | Feature-rich, non-linear |
| XGBoost | Next return % | Gradient boosting, regularization |
| LightGBM | Next return % | Fast gradient boosting, leaf-wise |
| **Stacking Ensemble** | **Next close price** | **Meta-learner combining all above** |
| LSTM | Next close price | Deep learning, sequence memory |

### Multi-Model Voting (trading loop)
- All available models vote: BUY (price up) or SELL (price down)
- Majority vote determines action; tie → HOLD
- Stacking ensemble prediction used as primary price target when available
- Confidence based on vote agreement ratio (higher agreement = higher confidence)

---

## Setup

### Requirements
- Python 3.10–3.12 (venv recommended)
- TensorFlow requires Python 3.9–3.12 (project venv uses Python 3.11)

### 1. Create virtual environment & install dependencies
```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # Mac/Linux
pip install -r requirements.txt
```

### 2. Build training data (with enhanced ICT features)
```bash
python data_pipeline.py
```

### 3. Train base models (LR, RF, XGBoost, LightGBM)
```bash
python model_training.py
```

### 4. Train stacking ensemble
```bash
python stacking_ensemble.py --ticker QQQ
```

### 5. Train LSTM (local, no Colab needed)
```bash
python lstm_trainer.py --ticker QQQ --epochs 80
```

### 6. Run walk-forward validation
```bash
python walk_forward.py --ticker QQQ --folds 5
```

### 7. Run the app
```bash
python app.py
```
Open **http://127.0.0.1:5000**

---

## Hosted Server Access

The app runs as a persistent systemd service on a Kali Linux server, accessible privately via Tailscale VPN:

| Access | URL |
|---|---|
| HTTPS (recommended) | https://kali.tail3ceaef.ts.net |
| Direct IP | http://100.116.236.84:5000 |
| SSH | `ssh xkcdhatguy@100.116.236.84` |

Requires Tailscale installed and connected to the `kipkiruikelly.github` tailnet.

---

## Algorithmic Trading

### Option A, MetaApi (recommended, works on Mac/Linux/Windows)
1. Sign up at [metaapi.cloud](https://metaapi.cloud) (free tier available)
2. Add your broker's MT5 account in the MetaApi dashboard
3. In the app: go to **MT5 Algo Trading** → **MetaApi** tab
4. Paste your **API Token** and **Account ID** → Connect
5. Set symbol, timeframe, risk % → **Start Algorithm**

### Option B, Paper Trading (no account needed)
- Click the **Paper** tab → Connect instantly
- Trades execute against live yfinance prices with $10,000 virtual balance

### Option C, Direct MT5 Bridge (Linux only)
Requires Wine ≥ 10.12 with Python + MetaTrader5 + rpyc installed inside the Wine prefix.
```bash
sudo apt install wine-devel
WINEPREFIX=~/.mt5 wine python.exe -m mt5linux -p 18812 --host 0.0.0.0
```

---

## Project Structure

```
Stock-Market-Predictor/
├── app.py                        # Flask app, auth, prediction routes, MT5 API
├── predictor.py                  # Shared ML inference (multi-model voting)
├── mt5_trading.py                # Trading engine (MetaApi / paper / direct MT5)
├── data_pipeline.py              # Step 1, download OHLCV data, engineer features
├── model_training.py             # Step 2, train LR + RF + XGB + LGB
├── stacking_ensemble.py          # Phase 1, cross-validated stacking ensemble
├── lstm_trainer.py               # Phase 1, bidirectional LSTM training
├── feature_engineering.py        # Phase 1, enhanced ICT features
├── walk_forward.py               # Phase 1, walk-forward analysis framework
├── alphas.py                     # WorldQuant-style alpha library
├── requirements.txt
├── Procfile                      # gunicorn entry point for deployment
│
├── Data/                         # Generated by data_pipeline.py
│   ├── AAPL_featured.csv
│   ├── X_train_AAPL.npy  ...
│   └── scaler_AAPL.pkl
│
├── Saved Models/                 # Generated by training scripts
│   ├── lr_model_AAPL.pkl
│   ├── rf_model_AAPL.pkl
│   ├── xgb_model_AAPL.pkl
│   ├── lgb_model_AAPL.pkl
│   ├── scaler_sklearn_AAPL.pkl
│   ├── feature_cols_sklearn_AAPL.pkl
│   ├── stacking_meta_AAPL.pkl    # Meta-learner
│   ├── stacking_meta_scaler_AAPL.pkl
│   └── lstm_model_AAPL.h5        # Bidirectional LSTM
│
├── Web Pages/
│   ├── index.html                # Home, ticker input, quota counter
│   ├── result.html               # Prediction result + TradingView chart
│   ├── mt5.html                  # Algo trading dashboard
│   ├── login.html
│   ├── register.html
│   └── pricing.html
│
├── tests/                        # Unit tests
├── tools/                        # Deployment scripts (Caddy, NSSM, ngrok)
│
└── Step1_Data_Collection_Pipeline.ipynb
    Step2_LSTM_Training.ipynb
```

---

## Quick Start (All Models)

```bash
# 1. Pipeline
python data_pipeline.py

# 2. Base models
python model_training.py

# 3. Stacking ensemble
python stacking_ensemble.py --ticker QQQ

# 4. LSTM
python lstm_trainer.py --ticker QQQ

# 5. Validate
python walk_forward.py --ticker QQQ --folds 5

# 6. Launch
python app.py
```

---

## Configuration

| Constant | File | Default | Description |
|---|---|---|---|
| `TICKER` | `data_pipeline.py` | `QQQ` | Symbol used for training |
| `FREE_DAILY_LIMIT` | `app.py` | `5` | Predictions per day for free users |
| `MAX_POSITIONS` | `mt5_trading.py` | `3` | Max concurrent open positions |
| `DAILY_LOSS_LIMIT` | `mt5_trading.py` | `0.05` | 5% equity drawdown halts trading |
| `PAPER_BALANCE` | `mt5_trading.py` | `10000` | Starting virtual balance |

---

## Disclaimer

Predictions and trades generated by this system are for **educational purposes only**. They do not constitute financial advice. Past performance does not guarantee future results. Never risk capital you cannot afford to lose.
