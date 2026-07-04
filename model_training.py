"""
model_training.py
ML-based Quantitative Trading System — Enhanced with Stacking Ensemble & LSTM.

Trains the full model suite for the Triple-Fusion-Engine:
  - Linear Regression (baseline, predicts next close price)
  - Random Forest (predicts next return %)
  - XGBoost (gradient boosting, predicts next return %)
  - LightGBM (gradient boosting, predicts next return %)
  - Stacking Ensemble (meta-learner combining all base models)
  - LSTM (via lstm_trainer.py, neural network on sequence data)

Models are saved to Saved Models/ for use by predictor.py and backtest.py.

Usage:
    python model_training.py                          # QQQ, all models
    python model_training.py --ticker AAPL            # Single ticker
    python model_training.py --skip-lstm --skip-stacking  # Base models only
    python model_training.py --all-tickers            # All tickers with data

Author: BullLogic
"""

import os
import sys
import warnings
import argparse
import logging
from typing import Dict, List, Optional, Tuple, Any

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import joblib
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

sns.set_theme(style="whitegrid")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────────

# Phase 2: Centralized config via config.py
try:
    from config import settings as _cfg
    TICKER      = _cfg.DEFAULT_TICKER
    TRAIN_RATIO = _cfg.TRAIN_RATIO
    VAL_RATIO   = _cfg.VAL_RATIO
    CV_FOLDS    = _cfg.CV_FOLDS
except ImportError:
    TICKER      = "QQQ"
    TRAIN_RATIO = 0.80
    VAL_RATIO   = 0.10
    CV_FOLDS    = 5

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "Data")
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")
os.makedirs(MODELS_DIR, exist_ok=True)

FEATURES = [
    "Close", "High", "Low", "Volume",
    "SMA_7", "SMA_21", "EMA_12", "EMA_26",
    "RSI_14", "MACD", "MACD_Signal", "MACD_Hist",
    "BB_Upper", "BB_Lower", "BB_Width",
    "Volume_SMA_10", "Daily_Return",
    "Close_lag_1", "Close_lag_2", "Close_lag_3",
    "Close_lag_4", "Close_lag_5",
    "Return_lag_1", "Return_lag_2", "Return_lag_3",
    # ICT-inspired features
    "Above_200SMA", "Dist_200SMA",
    "Body_Ratio", "Displacement",
    "Dist_to_SH", "Dist_to_SL",
    "Structure_Bullish", "PD_Position",
    "Bull_FVG_Count", "Bear_FVG_Count",
    "Bull_OB_Count", "Bear_OB_Count",
    "Dist_PWH", "Dist_PWL",
    "Swept_High", "Swept_Low",
    "Quarter_Sin", "Quarter_Cos",
    "Month_Sin", "Month_Cos",
]


def _check_optional_packages() -> Dict[str, bool]:
    """Check availability of optional ML packages."""
    status = {"xgb": False, "lgb": False, "tf": False}
    try:
        import xgboost  # noqa: F401
        status["xgb"] = True
    except ImportError:
        logger.warning("XGBoost not installed. Skipping XGBoost training.")
    try:
        import lightgbm  # noqa: F401
        status["lgb"] = True
    except ImportError:
        logger.warning("LightGBM not installed. Skipping LightGBM training.")
    try:
        import tensorflow  # noqa: F401
        status["tf"] = True
    except ImportError:
        logger.warning("TensorFlow not installed. Skipping LSTM training.")
    return status


def load_data(ticker: str) -> Dict[str, Any]:
    """Load featured data and prepare train/val/test splits."""
    csv_path = os.path.join(DATA_DIR, f"{ticker}_featured.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"Featured data not found: {csv_path}. Run 'python data_pipeline.py' first."
        )

    logger.info("Loading data from %s", csv_path)
    df = pd.read_csv(csv_path, index_col="Date", parse_dates=True)

    # Ensure required features exist
    available = [f for f in FEATURES if f in df.columns]
    missing   = [f for f in FEATURES if f not in df.columns]
    if missing:
        logger.info("Filling missing features with 0: %s", missing)
    for f in missing:
        df[f] = 0.0

    # Alpha features
    alpha_cols = [c for c in df.columns if c.startswith("Alpha_")]
    if alpha_cols:
        available.extend(alpha_cols)

    # Lag features if not present
    for lag in range(1, 6):
        if f"Close_lag_{lag}" not in df.columns:
            df[f"Close_lag_{lag}"] = df["Close"].shift(lag)
    for lag in range(1, 4):
        if f"Return_lag_{lag}" not in df.columns:
            df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    # Targets
    df["Next_Close"]  = df["Close"].shift(-1)
    df["Next_Return"] = (df["Next_Close"] / df["Close"] - 1) * 100
    df.dropna(inplace=True)

    n = len(df)
    train_end = int(n * TRAIN_RATIO)
    val_end   = int(n * (TRAIN_RATIO + VAL_RATIO))

    X = df[available].values
    y_close  = df["Next_Close"].values
    y_return = df["Next_Return"].values
    close_test = df.iloc[val_end:]["Close"].values
    close_train = df.iloc[:train_end]["Close"].values

    # Scale features
    scaler = MinMaxScaler()
    X_train_sc = scaler.fit_transform(X[:train_end])
    X_val_sc   = scaler.transform(X[train_end:val_end])
    X_test_sc  = scaler.transform(X[val_end:])

    logger.info("Train: %d, Val: %d, Test: %d rows | %d features",
                train_end, val_end - train_end, n - val_end, len(available))

    # Save scaler and feature list
    joblib.dump(scaler,   os.path.join(MODELS_DIR, f"scaler_sklearn_{ticker}.pkl"))
    joblib.dump(available, os.path.join(MODELS_DIR, f"feature_cols_sklearn_{ticker}.pkl"))

    return {
        "X_train": X_train_sc, "X_val": X_val_sc, "X_test": X_test_sc,
        "y_train_close": y_close[:train_end],
        "y_val_close":   y_close[train_end:val_end],
        "y_test_close":  y_close[val_end:],
        "y_train_return": y_return[:train_end],
        "y_val_return":   y_return[train_end:val_end],
        "y_test_return":  y_return[val_end:],
        "close_train": close_train,
        "close_test":  close_test,
        "feature_cols": available,
        "scaler": scaler,
    }


def evaluate(y_true: np.ndarray, y_pred: np.ndarray, name: str) -> dict:
    """Compute standard regression metrics."""
    mae  = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2   = r2_score(y_true, y_pred)
    dir_acc = float(np.mean(
        (np.diff(y_true) > 0) == (np.diff(y_pred) > 0)
    ) * 100) if len(y_true) > 1 else 50.0

    logger.info("  %-22s  MAE: $%7.2f  RMSE: $%7.2f  R²: %6.4f  Dir: %5.1f%%",
                name, mae, rmse, r2, dir_acc)
    return {
        "model": name, "mae": round(mae, 2), "rmse": round(rmse, 2),
        "r2": round(r2, 4), "directional_accuracy": round(dir_acc, 1),
    }


# ── Base Model Training ─────────────────────────────────────────────────────────

def train_linear_regression(data: Dict[str, Any], ticker: str) -> Tuple[Any, np.ndarray, dict]:
    """Train Linear Regression (predicts next close price)."""
    logger.info("Training Linear Regression...")
    model = LinearRegression()
    model.fit(data["X_train"], data["y_train_close"])
    y_pred = model.predict(data["X_test"])
    metrics = evaluate(data["y_test_close"], y_pred, "Linear Regression")
    joblib.dump(model, os.path.join(MODELS_DIR, f"lr_model_{ticker}.pkl"))
    return model, y_pred, metrics


def train_random_forest(data: Dict[str, Any], ticker: str) -> Tuple[Any, np.ndarray, dict]:
    """Train Random Forest (predicts next return %)."""
    logger.info("Training Random Forest (300 trees)...")
    model = RandomForestRegressor(
        n_estimators=300, max_depth=12,
        min_samples_split=4, min_samples_leaf=2,
        max_features=0.7, random_state=42, n_jobs=-1,
    )
    model.fit(data["X_train"], data["y_train_return"])
    ret_pred = model.predict(data["X_test"])
    y_pred   = data["close_test"] * (1 + ret_pred / 100)
    metrics  = evaluate(data["y_test_close"], y_pred, "Random Forest")

    # Feature importance
    importance = pd.DataFrame({
        "Feature": data["feature_cols"],
        "Importance": model.feature_importances_,
    }).sort_values("Importance", ascending=False)

    logger.info("  Top 5 RF features: %s",
                ", ".join(f"{r['Feature']}({r['Importance']:.3f})"
                          for _, r in importance.head(5).iterrows()))

    joblib.dump(model, os.path.join(MODELS_DIR, f"rf_model_{ticker}.pkl"))
    importance.to_csv(os.path.join(MODELS_DIR, f"rf_feature_importance_{ticker}.csv"), index=False)
    return model, y_pred, metrics


def train_xgboost(data: Dict[str, Any], ticker: str) -> Optional[Tuple[Any, np.ndarray, dict]]:
    """Train XGBoost (predicts next return %). Returns None if XGBoost unavailable."""
    try:
        import xgboost as xgb
    except ImportError:
        return None

    logger.info("Training XGBoost...")
    model = xgb.XGBRegressor(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, reg_alpha=1, reg_lambda=1,
        random_state=42, n_jobs=-1, verbosity=0,
    )
    model.fit(data["X_train"], data["y_train_return"])
    ret_pred = model.predict(data["X_test"])
    y_pred   = data["close_test"] * (1 + ret_pred / 100)
    metrics  = evaluate(data["y_test_close"], y_pred, "XGBoost")
    joblib.dump(model, os.path.join(MODELS_DIR, f"xgb_model_{ticker}.pkl"))
    return model, y_pred, metrics


def train_lightgbm(data: Dict[str, Any], ticker: str) -> Optional[Tuple[Any, np.ndarray, dict]]:
    """Train LightGBM (predicts next return %). Returns None if LightGBM unavailable."""
    try:
        import lightgbm as lgb
    except ImportError:
        return None

    logger.info("Training LightGBM...")
    model = lgb.LGBMRegressor(
        n_estimators=300, max_depth=8, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=0.1,
        random_state=42, n_jobs=-1, verbose=-1,
    )
    model.fit(data["X_train"], data["y_train_return"])
    ret_pred = model.predict(data["X_test"])
    y_pred   = data["close_test"] * (1 + ret_pred / 100)
    metrics  = evaluate(data["y_test_close"], y_pred, "LightGBM")
    joblib.dump(model, os.path.join(MODELS_DIR, f"lgb_model_{ticker}.pkl"))
    return model, y_pred, metrics


# ── Charts ──────────────────────────────────────────────────────────────────────

def save_charts(
    data: Dict[str, Any],
    preds: Dict[str, np.ndarray],
    ticker: str,
) -> None:
    """Save prediction comparison and feature importance charts."""
    logger.info("Saving charts...")

    # Actual vs Predicted comparison
    n_models = len(preds)
    fig, axes = plt.subplots(n_models, 1, figsize=(14, 3 * n_models), sharex=True)
    if n_models == 1:
        axes = [axes]

    x = range(len(data["y_test_close"]))
    colors = {"Linear Regression": "#E74C3C", "Random Forest": "#F39C12",
              "XGBoost": "#27AE60", "LightGBM": "#8E44AD"}

    for ax, (name, pred) in zip(axes, preds.items()):
        color = colors.get(name, "#2E75B6")
        ax.plot(x, data["y_test_close"], color="#1F4E79", lw=1.5, label="Actual")
        ax.plot(x, pred, color=color, lw=1.5, linestyle="--", label=name)
        ax.fill_between(x, data["y_test_close"], pred, alpha=0.08, color=color)
        ax.set_title(f"{ticker} – {name}: Actual vs Predicted", fontweight="bold")
        ax.set_ylabel("Price (USD)")
        ax.legend(fontsize=9)

    axes[-1].set_xlabel("Trading Days (Test Set)")
    plt.tight_layout()
    plt.savefig(os.path.join(MODELS_DIR, f"{ticker}_predictions.png"), dpi=150, bbox_inches="tight")
    plt.close()
    logger.info("  Charts saved → %s_predictions.png", ticker)


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Enhanced Model Training for Triple-Fusion-Engine")
    parser.add_argument("--ticker",       default="QQQ", metavar="SYM")
    parser.add_argument("--skip-lstm",    action="store_true",
                        help="Skip LSTM training")
    parser.add_argument("--skip-stacking", action="store_true",
                        help="Skip stacking ensemble (use stacking_ensemble.py separately)")
    parser.add_argument("--skip-xgboost", action="store_true",
                        help="Skip XGBoost training")
    parser.add_argument("--skip-lightgbm", action="store_true",
                        help="Skip LightGBM training")
    parser.add_argument("--all-tickers",  action="store_true",
                        help="Train on all tickers with featured data")
    args = parser.parse_args()

    pkg = _check_optional_packages()

    tickers = [args.ticker]
    if args.all_tickers:
        import glob
        csvs = glob.glob(os.path.join(DATA_DIR, "*_featured.csv"))
        tickers = sorted([
            os.path.basename(p).replace("_featured.csv", "")
            for p in csvs
        ])
        logger.info("Found %d tickers with data: %s", len(tickers), tickers)

    for ticker in tickers:
        logger.info("\n%s Training models for %s %s", "=" * 45, ticker, "=" * 45)

        try:
            data = load_data(ticker)
        except FileNotFoundError as e:
            logger.error("%s", e)
            continue

        preds = {}
        all_metrics = []

        # 1. Linear Regression
        lr_model, lr_pred, lr_metrics = train_linear_regression(data, ticker)
        preds["Linear Regression"] = lr_pred
        all_metrics.append(lr_metrics)

        # 2. Random Forest
        rf_model, rf_pred, rf_metrics = train_random_forest(data, ticker)
        preds["Random Forest"] = rf_pred
        all_metrics.append(rf_metrics)

        # 3. XGBoost
        if not args.skip_xgboost and pkg["xgb"]:
            xgb_result = train_xgboost(data, ticker)
            if xgb_result:
                _, xgb_pred, xgb_metrics = xgb_result
                preds["XGBoost"] = xgb_pred
                all_metrics.append(xgb_metrics)

        # 4. LightGBM
        if not args.skip_lightgbm and pkg["lgb"]:
            lgb_result = train_lightgbm(data, ticker)
            if lgb_result:
                _, lgb_pred, lgb_metrics = lgb_result
                preds["LightGBM"] = lgb_pred
                all_metrics.append(lgb_metrics)

        # Charts
        save_charts(data, preds, ticker)

        # Summary
        logger.info("\n%s Results Summary %s", "-" * 12, "-" * 12)
        results = pd.DataFrame(all_metrics)
        logger.info("\n" + results.to_string(index=False))
        results.to_csv(os.path.join(MODELS_DIR, f"model_comparison_{ticker}.csv"), index=False)

        # ── Stacking Ensemble (delegated to stacking_ensemble.py) ────────────
        if not args.skip_stacking:
            logger.info("\n%s Stacking Ensemble %s", "-" * 12, "-" * 12)
            logger.info("Run 'python stacking_ensemble.py --ticker %s' for "
                        "cross-validated stacking ensemble.", ticker)

        # ── LSTM (delegated to lstm_trainer.py) ──────────────────────────────
        if not args.skip_lstm and pkg["tf"]:
            logger.info("\n%s LSTM Training %s", "-" * 12, "-" * 12)
            logger.info("Run 'python lstm_trainer.py --ticker %s' for LSTM training.", ticker)
        elif not args.skip_lstm and not pkg["tf"]:
            logger.info("\nLSTM: TensorFlow not available. Use Colab notebook "
                        "(Step2_LSTM_Training.ipynb) or install TensorFlow.")

    logger.info("\nTraining complete. Models saved to: %s", MODELS_DIR)
    logger.info("Next steps:")
    logger.info("  1. python stacking_ensemble.py --ticker %s", args.ticker)
    logger.info("  2. python lstm_trainer.py --ticker %s", args.ticker)
    logger.info("  3. python predictor.py  (or start Flask app)")


if __name__ == "__main__":
    main()