"""
model_training.py
ML-based Quantitative Trading System

Loads the prepared dataset from the Data directory, trains Linear Regression
and Random Forest models, evaluates both on the held-out test set, and saves
the trained models and performance charts to the Saved Models directory.

The LSTM model is trained separately on Google Colab (Step2_LSTM_Training.ipynb)
due to TensorFlow compatibility constraints on Python 3.13.

Usage:
    python model_training.py

Author: BullLogic
"""

import os
import warnings
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


# Configuration
TICKER      = "QQQ"
TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "Data")
MODELS_DIR   = os.path.join(BASE_DIR, "Saved Models")
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


def load_data(ticker):
    print("Loading data...")
    df = pd.read_csv(
        os.path.join(DATA_DIR, f"{ticker}_featured.csv"),
        index_col="Date", parse_dates=True
    )

    for lag in range(1, 6):
        df[f"Close_lag_{lag}"]  = df["Close"].shift(lag)
        df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    df["Next_Close"]  = df["Close"].shift(-1)
    # RF predicts % return so its output is not bounded by the training price range
    df["Next_Return"] = (df["Next_Close"] / df["Close"] - 1) * 100
    df.dropna(inplace=True)

    n         = len(df)
    train_end = int(n * TRAIN_RATIO)
    val_end   = int(n * (TRAIN_RATIO + VAL_RATIO))

    X_train = df.iloc[:train_end][FEATURES].values
    X_val   = df.iloc[train_end:val_end][FEATURES].values
    X_test  = df.iloc[val_end:][FEATURES].values

    y_train     = df.iloc[:train_end]["Next_Close"].values
    y_val       = df.iloc[train_end:val_end]["Next_Close"].values
    y_test      = df.iloc[val_end:]["Next_Close"].values

    y_train_ret = df.iloc[:train_end]["Next_Return"].values
    y_val_ret   = df.iloc[train_end:val_end]["Next_Return"].values
    y_test_ret  = df.iloc[val_end:]["Next_Return"].values
    close_test  = df.iloc[val_end:]["Close"].values

    scaler     = MinMaxScaler()
    X_train_sc = scaler.fit_transform(X_train)
    X_val_sc   = scaler.transform(X_val)
    X_test_sc  = scaler.transform(X_test)

    joblib.dump(scaler,   os.path.join(MODELS_DIR, f"scaler_sklearn_{ticker}.pkl"))
    joblib.dump(FEATURES, os.path.join(MODELS_DIR, f"feature_cols_sklearn_{ticker}.pkl"))

    print(f"  Train: {X_train_sc.shape}, Val: {X_val_sc.shape}, Test: {X_test_sc.shape}")
    print(f"  Test price range: ${y_test.min():.2f} to ${y_test.max():.2f}")

    return {
        "X_train": X_train_sc, "X_val": X_val_sc, "X_test": X_test_sc,
        "y_train": y_train,    "y_val": y_val,     "y_test": y_test,
        "y_train_ret": y_train_ret, "y_val_ret": y_val_ret, "y_test_ret": y_test_ret,
        "close_test": close_test,
    }


def evaluate(y_true, y_pred, name):
    mae     = mean_absolute_error(y_true, y_pred)
    rmse    = np.sqrt(mean_squared_error(y_true, y_pred))
    r2      = r2_score(y_true, y_pred)
    dir_acc = np.mean((np.diff(y_true) > 0) == (np.diff(y_pred) > 0)) * 100

    print(f"  {name}")
    print(f"    MAE:  ${mae:.2f}  |  RMSE: ${rmse:.2f}  |  R2: {r2:.4f}  |  Dir. Acc: {dir_acc:.1f}%")

    return {"model": name, "mae": round(mae, 2), "rmse": round(rmse, 2),
            "r2": round(r2, 4), "directional_accuracy": round(dir_acc, 1)}


def train_linear_regression(data):
    print("\nTraining Linear Regression...")
    model = LinearRegression()
    model.fit(data["X_train"], data["y_train"])

    y_pred  = model.predict(data["X_test"])
    metrics = evaluate(data["y_test"], y_pred, "Linear Regression")

    joblib.dump(model, os.path.join(MODELS_DIR, f"lr_model_{TICKER}.pkl"))
    return model, metrics, y_pred


def train_random_forest(data):
    print("\nTraining Random Forest (300 trees)...")
    model = RandomForestRegressor(
        n_estimators=300, max_depth=12,
        min_samples_split=4, min_samples_leaf=2,
        max_features=0.7, random_state=42, n_jobs=-1
    )
    model.fit(data["X_train"], data["y_train_ret"])

    ret_pred = model.predict(data["X_test"])
    y_pred   = data["close_test"] * (1 + ret_pred / 100)
    metrics  = evaluate(data["y_test"], y_pred, "Random Forest")

    importance = pd.DataFrame({
        "Feature": FEATURES, "Importance": model.feature_importances_
    }).sort_values("Importance", ascending=False)

    print("\n  Top 5 features by importance:")
    for _, row in importance.head(5).iterrows():
        print(f"    {row['Feature']:<22} {row['Importance']:.4f}")

    joblib.dump(model, os.path.join(MODELS_DIR, f"rf_model_{TICKER}.pkl"))
    importance.to_csv(os.path.join(MODELS_DIR, f"rf_feature_importance_{TICKER}.csv"), index=False)
    return model, metrics, y_pred


def save_charts(y_true, lr_pred, rf_pred, rf_model):
    print("\nSaving charts...")
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    x = range(len(y_true))

    for ax, pred, name, color in [
        (axes[0], lr_pred, "Linear Regression", "#E74C3C"),
        (axes[1], rf_pred, "Random Forest",      "#F39C12"),
    ]:
        ax.plot(x, y_true, color="#1F4E79", lw=1.5, label="Actual Price")
        ax.plot(x, pred,   color=color,     lw=1.5, linestyle="--", label=f"{name} Prediction")
        ax.fill_between(x, y_true, pred, alpha=0.08, color=color)
        ax.set_title(f"{TICKER} — {name}: Actual vs Predicted", fontweight="bold")
        ax.set_ylabel("Price (USD)")
        ax.legend(fontsize=9)

    axes[1].set_xlabel("Trading Days (Test Set)")
    plt.tight_layout()
    plt.savefig(os.path.join(MODELS_DIR, f"{TICKER}_predictions.png"), dpi=150, bbox_inches="tight")
    plt.close()

    imp = pd.DataFrame({
        "Feature": FEATURES, "Importance": rf_model.feature_importances_
    }).sort_values("Importance", ascending=True).tail(10)

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(imp["Feature"], imp["Importance"], color="#2E75B6", alpha=0.8, edgecolor="white")
    ax.set_title(f"{TICKER} — Random Forest Feature Importances (Top 10)", fontweight="bold")
    ax.set_xlabel("Importance Score")
    for bar, val in zip(bars, imp["Importance"]):
        ax.text(bar.get_width() + 0.001, bar.get_y() + bar.get_height() / 2,
                f"{val:.4f}", va="center", fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(MODELS_DIR, f"{TICKER}_feature_importance.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Charts saved to Saved Models/")


def main():
    print(f"\nML-based Quantitative Trading System — Model Training")
    print(f"Ticker: {TICKER}\n")

    data = load_data(TICKER)

    lr_model,  lr_metrics,  lr_pred  = train_linear_regression(data)
    rf_model,  rf_metrics,  rf_pred  = train_random_forest(data)

    save_charts(data["y_test"], lr_pred, rf_pred, rf_model)

    print("\nResults summary:")
    results = pd.DataFrame([lr_metrics, rf_metrics])
    print(results.to_string(index=False))
    results.to_csv(os.path.join(MODELS_DIR, f"model_comparison_{TICKER}.csv"), index=False)

    print(f"\nTraining complete. Models saved to: {MODELS_DIR}")
    print("LSTM training: open Step2_LSTM_Training.ipynb in Google Colab\n")


if __name__ == "__main__":
    main()
