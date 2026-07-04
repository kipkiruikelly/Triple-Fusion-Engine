"""
stacking_ensemble.py
Stacking Ensemble for the Triple-Fusion-Engine.

Replaces the simple LR+RF fusion with a proper stacking ensemble:
  - Base models: LinearRegression, RandomForest, XGBoost, LightGBM
  - Meta-learner: Ridge regression trained on out-of-fold predictions
  - Cross-validated base predictions prevent data leakage
  - Feature importance analysis across all base models

Architecture:
  - LR predicts next close price (absolute target)
  - RF, XGB, LGB predict next return % (relative target, scale-invariant)
  - Meta-learner combines all predictions + original features

Usage:
    python stacking_ensemble.py --ticker QQQ
    python stacking_ensemble.py --ticker QQQ --cv-folds 5

Author: BullLogic
"""

import os
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

from sklearn.linear_model import LinearRegression, Ridge, LogisticRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_predict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "Data")
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")
os.makedirs(MODELS_DIR, exist_ok=True)

# Feature set mirrors model_training.py FEATURES + alpha features
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


def _safe_import() -> Tuple[bool, bool]:
    """Check availability of XGBoost and LightGBM."""
    xgb_ok = lgb_ok = False
    try:
        import xgboost as xgb  # noqa: F401
        xgb_ok = True
    except ImportError:
        logger.warning("XGBoost not installed. Install with: pip install xgboost")
    try:
        import lightgbm as lgb  # noqa: F401
        lgb_ok = True
    except ImportError:
        logger.warning("LightGBM not installed. Install with: pip install lightgbm")
    return xgb_ok, lgb_ok


def load_data(ticker: str) -> Dict[str, Any]:
    """Load featured data and prepare train/val/test splits.

    Returns a dict with scaled feature matrices, targets, and metadata.
    """
    csv_path = os.path.join(DATA_DIR, f"{ticker}_featured.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"Featured data not found: {csv_path}. Run 'python data_pipeline.py' first."
        )

    logger.info("Loading featured data from %s", csv_path)
    df = pd.read_csv(csv_path, index_col="Date", parse_dates=True)

    # Ensure required features exist; fill missing with 0
    available = [f for f in FEATURES if f in df.columns]
    missing = [f for f in FEATURES if f not in df.columns]
    if missing:
        logger.info("Missing feature columns (will fill with 0): %s", missing)
    for f in missing:
        df[f] = 0.0

    # Alpha features (if available from alphas.py)
    alpha_cols = [c for c in df.columns if c.startswith("Alpha_")]
    if alpha_cols:
        available.extend(alpha_cols)
        logger.info("Including %d alpha features", len(alpha_cols))
    else:
        logger.info("No alpha features found; run data_pipeline.py with alphas enabled")

    # Create lag features if not present
    for lag in range(1, 6):
        col = f"Close_lag_{lag}"
        if col not in df.columns:
            df[col] = df["Close"].shift(lag)
    for lag in range(1, 4):
        col = f"Return_lag_{lag}"
        if col not in df.columns:
            df[col] = df["Daily_Return"].shift(lag)

    # Targets
    df["Next_Close"]  = df["Close"].shift(-1)
    df["Next_Return"] = (df["Next_Close"] / df["Close"] - 1) * 100
    df.dropna(inplace=True)

    n = len(df)
    train_end = int(n * 0.80)
    val_end   = int(n * 0.90)

    X = df[available].values
    y_close  = df["Next_Close"].values
    y_return = df["Next_Return"].values
    close_test = df.iloc[val_end:]["Close"].values

    # Scale features
    scaler = MinMaxScaler()
    X_train = scaler.fit_transform(X[:train_end])
    X_val   = scaler.transform(X[train_end:val_end])
    X_test  = scaler.transform(X[val_end:])

    logger.info("Train: %d, Val: %d, Test: %d rows", train_end, val_end - train_end, n - val_end)
    logger.info("Feature count: %d", len(available))

    return {
        "X_train": X_train, "X_val": X_val, "X_test": X_test,
        "y_train_close": y_close[:train_end],
        "y_val_close":   y_close[train_end:val_end],
        "y_test_close":  y_close[val_end:],
        "y_train_return": y_return[:train_end],
        "y_val_return":   y_return[train_end:val_end],
        "y_test_return":  y_return[val_end:],
        "close_test": close_test,
        "feature_cols": available,
        "scaler": scaler,
    }


def evaluate(y_true: np.ndarray, y_pred: np.ndarray, name: str) -> dict:
    """Compute standard regression metrics."""
    mae  = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2   = r2_score(y_true, y_pred)
    # Directional accuracy
    if len(y_true) > 1:
        dir_acc = np.mean((np.diff(y_true) > 0) == (np.diff(y_pred) > 0)) * 100
    else:
        dir_acc = 50.0

    logger.info("  %-22s  MAE: $%7.2f  RMSE: $%7.2f  R²: %6.4f  Dir: %5.1f%%",
                name, mae, rmse, r2, dir_acc)
    return {
        "model": name, "mae": round(mae, 2), "rmse": round(rmse, 2),
        "r2": round(r2, 4), "directional_accuracy": round(dir_acc, 1),
    }


def train_base_models(data: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    """Train individual base models and return them with their predictions."""
    xgb_ok, lgb_ok = _safe_import()
    models = {}
    preds  = {}

    # ── Linear Regression (predicts next close price) ─────────────────────────
    logger.info("Training LinearRegression...")
    lr = LinearRegression()
    lr.fit(data["X_train"], data["y_train_close"])
    models["lr"] = lr
    preds["lr"]  = lr.predict(data["X_test"])
    evaluate(data["y_test_close"], preds["lr"], "LinearRegression")
    joblib.dump(lr, os.path.join(MODELS_DIR, f"lr_model_{ticker}.pkl"))

    # ── Random Forest (predicts next return %) ────────────────────────────────
    logger.info("Training RandomForest (300 trees)...")
    rf = RandomForestRegressor(
        n_estimators=300, max_depth=12,
        min_samples_split=4, min_samples_leaf=2,
        max_features=0.7, random_state=42, n_jobs=-1,
    )
    rf.fit(data["X_train"], data["y_train_return"])
    models["rf"] = rf
    rf_ret = rf.predict(data["X_test"])
    preds["rf"] = data["close_test"] * (1 + rf_ret / 100)
    evaluate(data["y_test_close"], preds["rf"], "RandomForest")
    joblib.dump(rf, os.path.join(MODELS_DIR, f"rf_model_{ticker}.pkl"))

    # ── XGBoost (predicts next return %) ──────────────────────────────────────
    if xgb_ok:
        import xgboost as xgb
        logger.info("Training XGBoost...")
        xgb_model = xgb.XGBRegressor(
            n_estimators=300, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, reg_alpha=1, reg_lambda=1,
            random_state=42, n_jobs=-1, verbosity=0,
        )
        xgb_model.fit(data["X_train"], data["y_train_return"])
        models["xgb"] = xgb_model
        xgb_ret = xgb_model.predict(data["X_test"])
        preds["xgb"] = data["close_test"] * (1 + xgb_ret / 100)
        evaluate(data["y_test_close"], preds["xgb"], "XGBoost")
        joblib.dump(xgb_model, os.path.join(MODELS_DIR, f"xgb_model_{ticker}.pkl"))

        # Feature importance
        _save_feature_importance(
            xgb_model.feature_importances_, data["feature_cols"],
            f"xgb_feature_importance_{ticker}", "XGBoost"
        )

    # ── LightGBM (predicts next return %) ─────────────────────────────────────
    if lgb_ok:
        import lightgbm as lgb
        logger.info("Training LightGBM...")
        lgb_model = lgb.LGBMRegressor(
            n_estimators=300, max_depth=8, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=0.1,
            random_state=42, n_jobs=-1, verbose=-1,
        )
        lgb_model.fit(data["X_train"], data["y_train_return"])
        models["lgb"] = lgb_model
        lgb_ret = lgb_model.predict(data["X_test"])
        preds["lgb"] = data["close_test"] * (1 + lgb_ret / 100)
        evaluate(data["y_test_close"], preds["lgb"], "LightGBM")
        joblib.dump(lgb_model, os.path.join(MODELS_DIR, f"lgb_model_{ticker}.pkl"))

        _save_feature_importance(
            lgb_model.feature_importances_, data["feature_cols"],
            f"lgb_feature_importance_{ticker}", "LightGBM"
        )

    # ── Save feature importance for RandomForest ──────────────────────────────
    _save_feature_importance(
        rf.feature_importances_, data["feature_cols"],
        f"rf_feature_importance_{ticker}", "RandomForest"
    )

    return models, preds


def _save_feature_importance(
    importances: np.ndarray, feature_names: List[str],
    filename: str, model_name: str,
) -> None:
    """Save feature importance to CSV and create a bar chart."""
    imp_df = pd.DataFrame({
        "Feature": feature_names, "Importance": importances,
    }).sort_values("Importance", ascending=False)

    csv_path = os.path.join(MODELS_DIR, f"{filename}.csv")
    imp_df.to_csv(csv_path, index=False)

    top15 = imp_df.head(15).sort_values("Importance", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(top15["Feature"], top15["Importance"], color="#2E75B6", alpha=0.8, edgecolor="white")
    ax.set_title(f"{model_name} Feature Importance (Top 15)", fontweight="bold")
    ax.set_xlabel("Importance Score")
    for bar, val in zip(bars, top15["Importance"]):
        ax.text(bar.get_width() + 0.001, bar.get_y() + bar.get_height() / 2,
                f"{val:.4f}", va="center", fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(MODELS_DIR, f"{filename}.png"), dpi=150, bbox_inches="tight")
    plt.close()
    logger.info("  Feature importance saved → %s", filename)


def build_stacking_ensemble(
    data: Dict[str, Any], models: Dict[str, Any], ticker: str,
    cv_folds: int = 5,
) -> Tuple[Any, Any, dict]:
    """Build a stacking ensemble with cross-validated meta-features.

    Strategy:
      1. Generate out-of-fold predictions from each base model via K-fold CV.
         LR predicts price; RF/XGB/LGB predict return %.
      2. Train a Ridge meta-learner on the OOF predictions + original features.
      3. Final-fit all base models on the full training set.

    Returns (stacking_meta, stacking_scaler, metrics).
    """
    logger.info("Building stacking ensemble (%d-fold CV)...", cv_folds)

    X_train = data["X_train"]
    y_train_close  = data["y_train_close"]
    y_train_return = data["y_train_return"]
    X_val   = data["X_val"]
    y_val_close    = data["y_val_close"]

    kf = KFold(n_splits=cv_folds, shuffle=True, random_state=42)

    # Container for out-of-fold predictions + original features
    n_train = len(X_train)
    meta_features_train = np.zeros((n_train, 0))

    # Generate OOF predictions for each base model
    meta_cols = []

    # 1. LinearRegression OOF predictions (price target)
    lr_oof = cross_val_predict(models["lr"], X_train, y_train_close, cv=kf)
    meta_features_train = np.column_stack([meta_features_train, lr_oof])
    meta_cols.append("lr_oof_price")

    # 2. RF OOF return predictions, converted to price
    rf_oof_ret = cross_val_predict(models["rf"], X_train, y_train_return, cv=kf)
    # Need training close prices for conversion
    # Reconstruct from data: we need close prices for each fold
    close_train = data.get("close_train")
    if close_train is None:
        # Estimate: get closes from the original DataFrame
        logger.info("Recomputing close_train for price conversion...")
        csv_path = os.path.join(DATA_DIR, f"{ticker}_featured.csv")
        df = pd.read_csv(csv_path, index_col="Date", parse_dates=True)
        for lag in range(1, 6):
            df[f"Close_lag_{lag}"] = df["Close"].shift(lag)
        for lag in range(1, 4):
            df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)
        df["Next_Close"]  = df["Close"].shift(-1)
        df["Next_Return"] = (df["Next_Close"] / df["Close"] - 1) * 100
        df.dropna(inplace=True)
        n = len(df)
        train_end = int(n * 0.80)
        close_train = df.iloc[:train_end]["Close"].values

    rf_oof_price = close_train * (1 + rf_oof_ret / 100)
    meta_features_train = np.column_stack([meta_features_train, rf_oof_price])
    meta_cols.append("rf_oof_price")

    # 3. XGBoost OOF return → price
    if "xgb" in models:
        xgb_oof_ret = cross_val_predict(models["xgb"], X_train, y_train_return, cv=kf)
        xgb_oof_price = close_train * (1 + xgb_oof_ret / 100)
        meta_features_train = np.column_stack([meta_features_train, xgb_oof_price])
        meta_cols.append("xgb_oof_price")

    # 4. LightGBM OOF return → price
    if "lgb" in models:
        lgb_oof_ret = cross_val_predict(models["lgb"], X_train, y_train_return, cv=kf)
        lgb_oof_price = close_train * (1 + lgb_oof_ret / 100)
        meta_features_train = np.column_stack([meta_features_train, lgb_oof_price])
        meta_cols.append("lgb_oof_price")

    # Optionally add original features as meta-features (reduces to top 10 by RF importance)
    rf_imp = models["rf"].feature_importances_
    top10_idx = np.argsort(rf_imp)[-10:]
    meta_features_train = np.column_stack([
        meta_features_train,
        X_train[:, top10_idx],
    ])
    meta_cols.extend([data["feature_cols"][i] for i in top10_idx])

    # Scale meta-features
    meta_scaler = StandardScaler()
    meta_features_train_sc = meta_scaler.fit_transform(meta_features_train)

    # Train meta-learner (Ridge regression)
    logger.info("Training meta-learner (Ridge) on %d meta-features...", len(meta_cols))
    meta_learner = Ridge(alpha=1.0, random_state=42)
    meta_learner.fit(meta_features_train_sc, y_train_close)

    # Evaluate on validation set
    meta_features_val = _build_meta_features(
        data["X_val"], data["X_test"], models, data, top10_idx,
        build_val=True,
    )["val"]
    meta_features_val_sc = meta_scaler.transform(meta_features_val)
    y_val_pred = meta_learner.predict(meta_features_val_sc)
    metrics = evaluate(y_val_close, y_val_pred, "Stacking Ensemble (Val)")

    # Save stacking artifacts
    joblib.dump(meta_learner, os.path.join(MODELS_DIR, f"stacking_meta_{ticker}.pkl"))
    joblib.dump(meta_scaler, os.path.join(MODELS_DIR, f"stacking_meta_scaler_{ticker}.pkl"))
    joblib.dump(meta_cols,  os.path.join(MODELS_DIR, f"stacking_meta_cols_{ticker}.pkl"))
    joblib.dump(top10_idx,  os.path.join(MODELS_DIR, f"stacking_top10_idx_{ticker}.pkl"))
    joblib.dump(data["feature_cols"], os.path.join(MODELS_DIR, f"feature_cols_sklearn_{ticker}.pkl"))
    joblib.dump(data["scaler"], os.path.join(MODELS_DIR, f"scaler_sklearn_{ticker}.pkl"))

    logger.info("Stacking ensemble saved to %s/", MODELS_DIR)
    return meta_learner, meta_scaler, metrics


def _build_meta_features(
    X_val: np.ndarray, X_test: np.ndarray,
    models: Dict[str, Any], data: Dict[str, Any],
    top10_idx: np.ndarray, build_val: bool = True,
) -> Dict[str, np.ndarray]:
    """Build meta-features for validation and test sets."""
    result: Dict[str, np.ndarray] = {}

    for split_name, X_split in [("val", X_val), ("test", X_test)]:
        if split_name == "val" and not build_val:
            continue
        feats = np.zeros((len(X_split), 0))

        # LR price prediction
        feats = np.column_stack([feats, models["lr"].predict(X_split)])

        # RF return → price
        close_split = data.get(f"close_{split_name}")
        if close_split is None:
            close_split = data["close_test"] if split_name == "test" else data.get("close_test")
        rf_ret = models["rf"].predict(X_split)
        feats = np.column_stack([feats, close_split * (1 + rf_ret / 100)])

        if "xgb" in models:
            xgb_ret = models["xgb"].predict(X_split)
            feats = np.column_stack([feats, close_split * (1 + xgb_ret / 100)])

        if "lgb" in models:
            lgb_ret = models["lgb"].predict(X_split)
            feats = np.column_stack([feats, close_split * (1 + lgb_ret / 100)])

        feats = np.column_stack([feats, X_split[:, top10_idx]])
        result[split_name] = feats

    return result


def save_comparison_chart(
    y_true: np.ndarray, preds: Dict[str, np.ndarray],
    ticker: str,
) -> None:
    """Plot actual vs predicted for all models on the same chart."""
    logger.info("Saving model comparison chart...")
    n_models = len(preds)
    fig, axes = plt.subplots(n_models, 1, figsize=(14, 3 * n_models), sharex=True)
    if n_models == 1:
        axes = [axes]

    x = range(len(y_true))
    colors = {"lr": "#E74C3C", "rf": "#F39C12", "xgb": "#27AE60", "lgb": "#8E44AD"}

    for ax, (name, pred) in zip(axes, preds.items()):
        color = colors.get(name, "#2E75B6")
        ax.plot(x, y_true, color="#1F4E79", lw=1.5, label="Actual Price")
        ax.plot(x, pred,     color=color,     lw=1.5, linestyle="--", label=f"{name.upper()} Prediction")
        ax.fill_between(x, y_true, pred, alpha=0.08, color=color)
        ax.set_title(f"{ticker} – {name.upper()}: Actual vs Predicted", fontweight="bold")
        ax.set_ylabel("Price (USD)")
        ax.legend(fontsize=9)

    axes[-1].set_xlabel("Trading Days (Test Set)")
    plt.tight_layout()
    plt.savefig(os.path.join(MODELS_DIR, f"{ticker}_ensemble_comparison.png"), dpi=150, bbox_inches="tight")
    plt.close()
    logger.info("  Chart saved → %s_ensemble_comparison.png", ticker)


def main():
    parser = argparse.ArgumentParser(description="Stacking Ensemble Trainer")
    parser.add_argument("--ticker",  default="QQQ", metavar="SYM",
                        help="Ticker symbol (default: QQQ)")
    parser.add_argument("--cv-folds", default=5, type=int, metavar="N",
                        help="Cross-validation folds (default: 5)")
    parser.add_argument("--skip-stacking", action="store_true",
                        help="Train base models only, skip stacking ensemble")
    parser.add_argument("--all-tickers", action="store_true",
                        help="Train on all tickers with saved feature data")
    args = parser.parse_args()

    tickers = [args.ticker]
    if args.all_tickers:
        import glob
        csvs = glob.glob(os.path.join(DATA_DIR, "*_featured.csv"))
        tickers = sorted([
            os.path.basename(p).replace("_featured.csv", "")
            for p in csvs
        ])
        logger.info("Found %d tickers with feature data: %s", len(tickers), tickers)

    all_results = []
    for ticker in tickers:
        logger.info("\n%s Training stacking ensemble for %s %s", "=" * 50, ticker, "=" * 50)
        try:
            data = load_data(ticker)
        except FileNotFoundError as e:
            logger.error("%s", e)
            continue

        models, preds = train_base_models(data, ticker)

        if not args.skip_stacking:
            meta_learner, meta_scaler, stacking_metrics = build_stacking_ensemble(
                data, models, ticker, cv_folds=args.cv_folds,
            )

        save_comparison_chart(data["y_test_close"], preds, ticker)

        # Final test evaluation for stacking
        if not args.skip_stacking:
            _, meta_scaler = joblib.load(os.path.join(MODELS_DIR, f"stacking_meta_scaler_{ticker}.pkl")), \
                             joblib.load(os.path.join(MODELS_DIR, f"stacking_meta_{ticker}.pkl"))
            top10_idx = joblib.load(os.path.join(MODELS_DIR, f"stacking_top10_idx_{ticker}.pkl"))
            meta_cols = joblib.load(os.path.join(MODELS_DIR, f"stacking_meta_cols_{ticker}.pkl"))

            meta_feats = _build_meta_features(
                data["X_val"], data["X_test"], models, data, top10_idx,
            )["test"]
            meta_feats_sc = meta_scaler.transform(meta_feats)
            y_stack_pred = meta_learner.predict(meta_feats_sc)
            stacking_metrics = evaluate(data["y_test_close"], y_stack_pred, "Stacking Ensemble (Test)")

        # Summary
        logger.info("\n%s SUMMARY %s", "-" * 12, "-" * 12)
        for name, pred in preds.items():
            evaluate(data["y_test_close"], pred, name.upper())
        logger.info("-" * 30)

    # Aggregate summary
    if len(tickers) > 1:
        logger.info("\n%s AGGREGATE RESULTS %s", "=" * 20, "=" * 20)
        logger.info("Trained %d tickers successfully", len(tickers))


if __name__ == "__main__":
    main()
