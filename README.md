# Triple Fusion Engine (BullLogic v3.0 Gold Release)

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-4.2-green.svg)](https://www.djangoproject.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-teal.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.0-61dafb.svg)](https://reactjs.org/)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)

---

## 📜 License & Intellectual Property Protection
**Proprietary and Closed-Source. All Rights Reserved.**

Copyright © 2026 Triple Fusion Engine.

This codebase, software, algorithms, machine learning models, and proprietary indicators are strictly closed-source and confidential. Unauthorized copying, distribution, modification, reverse engineering, or public deployment of any part of this software is strictly prohibited without prior written consent. See [LICENSE](LICENSE) for full legal terms.

An enterprise-grade, full-stack quantitative trading intelligence platform and MLOps engine powered by the **Triple Fusion Prediction Engine** (Market Structure + Machine Learning Ensembles + Technical Analysis).

Built with Django REST Framework, FastAPI, Celery, Redis, React 18, Vite, and MetaTrader 5 (MT5) execution bridges.

---

## 🏛️ System Architecture

```
                                ┌──────────────────────────────────────────┐
                                │        React 18 + Vite Frontend          │
                                │    (MUI Dark Glassmorphism Design UI)    │
                                └────────────────────┬─────────────────────┘
                                                     │
            ┌────────────────────────────────────────┴────────────────────────────────────────┐
            │                                                                                 │
            ▼                                                                                 ▼
┌──────────────────────────────────────────┐                               ┌──────────────────────────────────────────┐
│   Django REST Framework Backend (8001)   │                               │     FastAPI Microservice (8002)          │
│   • Auth, JWT, Security, Pass Reset      │                               │     • High-Speed ML Model Inference     │
│   • Multi-Portfolio & Audited Ledgers    │                               │     • WebSocket Real-time Feeds          │
│   • Smart Execution Router & Celery Tasks│                               │     • Standardized Pydantic Schemas     │
└───────────────────┬──────────────────────┘                               └────────────────────┬─────────────────────┘
                    │                                                                           │
                    └────────────────────────────────────┬──────────────────────────────────────┘
                                                         │
                                                         ▼
                                ┌──────────────────────────────────────────┐
                                │         Redis Cache & Celery Queue       │
                                │   (Sub-ms Quotes & Background Scans)     │
                                └──────────────────────────────────────────┘
```

---

## ✨ Key Enterprise Subsystems

### 1. 🤖 Interactive AI Trading Robots & Strategy Suite
Subscribers can activate, backtest, and automate signals across 6 specialized AI models:

* **Stacking Meta-Ensemble** (`Stocks`): Ridge Regression meta-learner ensembling out-of-fold predictions from Random Forest, XGBoost, and LightGBM.
* **XGBoost Directional Bot** (`Stocks`): Gradient boosted classifier predicting next-day price direction using lag returns and technical indicators.
* **Random Forest Value Bot** (`Stocks`): Regressor targeting mean-reversion entries around custom alpha factors.
* **Linear Regression Trend Bot** (`Stocks`): Statistical regression trading deviations around linear trend channels.
* **LightGBM Momentum Bot** (`Stocks`): High-speed tree model optimized for rapid intraday momentum breakout signals.

---

### 2. 🧠 MLOps Model Registry & Evaluation Metrics
* **Standardized Metric Tracking**: Evaluates models using Mean Absolute Error (**MAE**), Mean Squared Error (**MSE**), Root Mean Squared Error (**RMSE**), **$R^2$ Score**, and **Directional Accuracy (%)**.
* **Chronological Time-Series Validation**: Uses 5-fold `TimeSeriesSplit` cross-validation to guarantee zero future data leakage.
* **Hyperparameter Tuning**: Automated `RandomizedSearchCV` cross-validation across depth, estimators, learning rates, and regularization parameters.
* **Permutation Feature Importance**: Ranks indicator importance weights (`PD_Position`, `Bear_OB_Count`, `Bear_OB_Count`).

---

### 3. 💼 Enterprise Multi-Portfolio & Audited Ledger Engine
An advanced asset management engine built to maintain perfect ledger sync and transactional durability:
* **Audited Transaction Ledgers**: Enforces absolute accounting standards. Cash movements (Deposits, Withdrawals) and execution orders (Buys, Sells) are written into a non-nullable, chronological SQL ledger.
* **Dollar-Cost-Averaging (DCA) Math Logic**: Dynamically tracks asset positions and recalculates asset average entry cost base on buy-side events:
  $$\text{New Average Entry Price} = \frac{(\text{Existing Quantity} \times \text{Existing Average Price}) + (\text{Executed Quantity} \times \text{Executed Price})}{\text{Existing Quantity} + \text{Executed Quantity}}$$
* **Real-time Valuation Sweep**: Integrates a concurrent `ThreadPoolExecutor` and the `yfinance` endpoints to execute background price sweeps, instantly updating portfolio total equity, realized and unrealized profit-loss, and percentage asset allocations on-demand.
* **Strict Concurrency row locking**: Implements database-level row locking (`select_for_update`) during transactional trade processing to completely avoid overdrafts or duplicate order executions under concurrent REST API loads.

---

### 4. ⚡ Institutional Smart Order Execution Engine (JPMorgan DNA-Style)
* **TWAP / VWAP Iceberg Order Router**: Splits large parent orders into small child order slices to minimize market impact and slippage.
* **Adaptive Passive / Aggressive FSM**:
  $$\text{PASSIVE\_LIMIT (Order Block / FVG)} \xrightarrow{\text{80\% Time / <50\% Filled}} \text{AGGRESSIVE\_TAKER (Market Sweep)}$$
* **Post-Trade Execution Feedback**: Logs fill latency, benchmark arrival prices, average fill prices, and cumulative dollar slippage savings.

---

### 5. 🔐 Enterprise Authentication & Security
* **JWT Token Security**: Short-lived Access Tokens (15-min) + long-lived Refresh Tokens (24h) with automated refresh rotation, dual-token security, and Redis revocations blacklisting on logout.
* **Role-Based Access Control (RBAC)**: Secure user tiers (`free`, `plus`, `pro`, `admin`) validated dynamically using standard Django decorators.
* **1-Click Google OAuth 2.0**: Social login integration (`POST /api/auth/google`).
* **Email Password Reset**: 1-hour expiration tokenized reset emails (`/api/auth/forgot-password`).
* **Brute-Force Lockout**: 15-minute account lockouts after 5 consecutive failed login attempts.

---

### 6. ⚙️ Asynchronous MLOps Background Retraining Pipeline
* **Celery-Based Automated Training**: Offloads heavy model training runs, feature engineering, and high-frequency scanners to asynchronous background workers.
* **Evaluation Safety Gates**: Integrated safety guardrails validate model candidates automatically post-training. If the model exhibits negative $R^2$ scores or experiences directional accuracy degradation exceeding 10%, deployment is automatically rejected and the previous stable candidate remains in production.

---

## 📡 REST API Reference

### 🔐 Authentication APIs
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/login` | Session / JWT user login. |
| `POST` | `/api/register` | User registration with PIN verification. |
| `POST` | `/api/logout` | Revokes active JWT refresh tokens. |
| `POST` | `/api/auth/google` | 1-Click Google OAuth login. |
| `POST` | `/api/auth/forgot-password` | Initiates password reset email flow. |
| `POST` | `/api/auth/reset-password` | Confirms password reset. |

### 💼 Portfolio Management APIs
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/trading/portfolios` | Retrieves list of user portfolios. |
| `POST` | `/api/v1/trading/portfolios` | Creates a new user portfolio with funding. |
| `GET` | `/api/v1/trading/portfolios/<pk>` | Returns dynamic holdings valuations, weights, and metrics. |
| `DELETE` | `/api/v1/trading/portfolios/<pk>` | Soft-deletes/archives an active portfolio. |
| `POST` | `/api/v1/trading/portfolios/transaction` | Executes Deposit, Withdrawal, Buy, or Sell ledger transaction. |
| `GET` | `/api/v1/trading/portfolios/<id>/transactions` | Audits historical transaction logs. |

### 🤖 AI Robots & Automation APIs
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/bots` | Lists active AI Robots & subscription status. |
| `POST` | `/api/bots/subscribe` | Toggles strategy subscription. |
| `GET` | `/api/bots/signals` | Live signal stream for subscribed bots. |
| `POST` | `/api/bots/auto-trade` | Toggles Paper/MT5 auto-execution & risk limits. |
| `POST` | `/api/bots/backtest` | Executes interactive backtest sandbox. |

### 🧠 MLOps, Dataset & Analytics APIs
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/model/info` | Returns model version metadata, MAE, MSE, RMSE, and $R^2$ metrics. |
| `GET` | `/api/properties` | Inspects dataset rows, columns, nulls, and date ranges. |
| `POST` | `/api/upload` | Uploads and validates custom market CSV datasets. |
| `GET` | `/api/statistics` | Platform prediction statistics & win rates. |
| `GET` | `/api/feature-importance` | Indicator importance weight rankings. |
| `POST` | `/api/v1/trading/pipeline/run` | Triggers background Celery ML retraining task. |
| `GET` | `/api/v1/trading/pipeline/task/<task_id>` | Monitors live status and logs of background training runs. |

---

## 🛠️ Quick Start Guide

### Prerequisites
* Python 3.11+
* Node.js 18+
* Redis (used as Celery queue message broker)

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/kipkiruikelly/Triple-Fusion-Engine.git
cd Triple-Fusion-Engine

# Install Python dependencies
pip install -r requirements.txt

# Install Frontend dependencies
cd frontend
npm install
cd ..
```

### 2. Database Setup & Migrations
```bash
# Run Django migrations
python django_backend/manage.py migrate
```

### 3. Running Services
```bash
# Start Django Backend (Port 8001)
python django_backend/manage.py runserver 8001

# Start FastAPI Microservice (Port 8002)
uvicorn fastapi_service.main:app --port 8002 --reload

# Start Celery Asynchronous Workers
celery -A django_backend worker -l info

# Start React Frontend (Port 5173 / 5000)
cd frontend
npm run dev
```

---

## 📜 License & Intellectual Property Protection
**Proprietary and Closed-Source. All Rights Reserved.**

Copyright © 2026 Triple Fusion Engine. See [LICENSE](LICENSE) for full legal terms.
