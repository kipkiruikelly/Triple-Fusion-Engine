"""
lstm_trainer.py
Local LSTM Training Module for the Triple-Fusion-Engine.

Trains an LSTM neural network on the pre-processed sequence data from
data_pipeline.py. Previously this required Google Colab due to TensorFlow
compatibility issues on Python 3.13; with the project venv (Python 3.11)
TensorFlow is fully supported.

Architecture:
  - Two-scaler design: one MinMaxScaler for LSTM (Data/), one for sklearn (Saved Models/)
  - Sequence length: 60 bars (LOOKBACK from data_pipeline.py)
  - Bidirectional LSTM with dropout for regularization
  - Early stopping and learning rate reduction on plateau
  - Saves model in both .h5 (Keras) and .keras formats for inference

Usage:
    python lstm_trainer.py --ticker QQQ
    python lstm_trainer.py --ticker QQQ --epochs 100 --batch-size 32

Author: BullLogic
"""

import os
import warnings
import argparse
import logging
from typing import Dict, Tuple, Optional

warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"  # Suppress TF info messages

import numpy as np
import pandas as pd
import joblib
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "Data")
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")
os.makedirs(MODELS_DIR, exist_ok=True)

LOOKBACK = 60  # Must match data_pipeline.py LOOKBACK


def _check_tf() -> bool:
    """Check if TensorFlow is available."""
    try:
        import tensorflow as tf  # noqa: F401
        logger.info("TensorFlow version: %s", tf.__version__)
        return True
    except ImportError:
        logger.error(
            "TensorFlow is not installed. Install with: pip install tensorflow\n"
            "Note: TensorFlow requires Python 3.9-3.12. The project venv uses Python 3.11."
        )
        return False


def load_sequence_data(ticker: str) -> Dict[str, np.ndarray]:
    """Load pre-processed LSTM sequence data from Data/ directory.

    Expects files produced by data_pipeline.py:
      - X_train_TICKER.npy, y_train_TICKER.npy
      - X_val_TICKER.npy,   y_val_TICKER.npy
      - X_test_TICKER.npy,  y_test_TICKER.npy
      - scaler_TICKER.pkl, feature_cols_TICKER.pkl
    """
    prefix = f"{ticker}"
    required = [
        f"X_train_{prefix}.npy", f"y_train_{prefix}.npy",
        f"X_val_{prefix}.npy",   f"y_val_{prefix}.npy",
        f"X_test_{prefix}.npy",  f"y_test_{prefix}.npy",
    ]
    missing = [f for f in required if not os.path.exists(os.path.join(DATA_DIR, f))]
    if missing:
        raise FileNotFoundError(
            f"Missing LSTM data files: {missing}. "
            f"Run 'python data_pipeline.py' first to generate them."
        )

    logger.info("Loading LSTM sequence data from %s/", DATA_DIR)
    X_train = np.load(os.path.join(DATA_DIR, f"X_train_{prefix}.npy"))
    y_train = np.load(os.path.join(DATA_DIR, f"y_train_{prefix}.npy"))
    X_val   = np.load(os.path.join(DATA_DIR, f"X_val_{prefix}.npy"))
    y_val   = np.load(os.path.join(DATA_DIR, f"y_val_{prefix}.npy"))
    X_test  = np.load(os.path.join(DATA_DIR, f"X_test_{prefix}.npy"))
    y_test  = np.load(os.path.join(DATA_DIR, f"y_test_{prefix}.npy"))

    logger.info("  X_train: %s, X_val: %s, X_test: %s",
                X_train.shape, X_val.shape, X_test.shape)

    # Load scaler for inverse transform during evaluation
    scaler_path = os.path.join(DATA_DIR, f"scaler_{prefix}.pkl")
    scaler = joblib.load(scaler_path) if os.path.exists(scaler_path) else None

    # Load feature columns to find Close index
    feat_path = os.path.join(DATA_DIR, f"feature_cols_{prefix}.pkl")
    close_idx = 0
    if os.path.exists(feat_path):
        feature_cols = joblib.load(feat_path)
        try:
            close_idx = feature_cols.index("Close")
        except ValueError:
            close_idx = 0

    return {
        "X_train": X_train, "y_train": y_train,
        "X_val": X_val,     "y_val": y_val,
        "X_test": X_test,   "y_test": y_test,
        "scaler": scaler, "close_idx": close_idx,
        "n_features": X_train.shape[2],
    }


def build_lstm_model(
    n_features: int,
    lookback: int = LOOKBACK,
    lstm_units: Tuple[int, int] = (128, 64),
    dropout: float = 0.3,
    learning_rate: float = 0.001,
) -> "tf.keras.Model":
    """Build a bidirectional LSTM model for price prediction.

    Architecture:
      - Bidirectional LSTM layer 1 → BatchNorm → Dropout
      - Bidirectional LSTM layer 2 → BatchNorm → Dropout
      - Dense(32) → ReLU → Dropout
      - Dense(1) linear output (regression)

    Args:
        n_features: Number of input features per timestep.
        lookback: Number of timesteps (sequence length).
        lstm_units: Tuple of (layer1_units, layer2_units).
        dropout: Dropout rate after each LSTM layer.
        learning_rate: Adam optimizer learning rate.

    Returns:
        Compiled Keras model.
    """
    import tensorflow as tf
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import (
        LSTM, Bidirectional, Dense, Dropout, BatchNormalization, Input,
    )
    from tensorflow.keras.optimizers import Adam

    units1, units2 = lstm_units

    model = Sequential([
        Input(shape=(lookback, n_features), name="lstm_input"),
        Bidirectional(LSTM(units1, return_sequences=True, name="bi_lstm_1")),
        BatchNormalization(name="bn_1"),
        Dropout(dropout, name="dropout_1"),
        Bidirectional(LSTM(units2, return_sequences=False, name="bi_lstm_2")),
        BatchNormalization(name="bn_2"),
        Dropout(dropout, name="dropout_2"),
        Dense(32, activation="relu", name="dense_32"),
        Dropout(dropout / 2, name="dropout_3"),
        Dense(1, activation="linear", name="output"),
    ])

    model.compile(
        optimizer=Adam(learning_rate=learning_rate, clipnorm=1.0),
        loss="huber",  # Robust to outliers, better than MSE for financial data
        metrics=["mae"],
    )

    return model


def train_lstm(
    data: Dict[str, np.ndarray],
    ticker: str,
    epochs: int = 80,
    batch_size: int = 32,
    patience: int = 15,
) -> Tuple["tf.keras.Model", dict]:
    """Train the LSTM model with early stopping and LR reduction.

    Returns (trained_model, history_dict).
    """
    import tensorflow as tf
    from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

    model = build_lstm_model(data["n_features"])

    logger.info("LSTM Architecture:")
    model.summary(print_fn=logger.info)

    callbacks = [
        EarlyStopping(
            monitor="val_loss", patience=patience,
            restore_best_weights=True, verbose=1,
        ),
        ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=patience // 3,
            min_lr=1e-6, verbose=1,
        ),
    ]

    logger.info("Training LSTM (%d epochs, batch size %d)...", epochs, batch_size)
    history = model.fit(
        data["X_train"], data["y_train"],
        validation_data=(data["X_val"], data["y_val"]),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=callbacks,
        verbose=1,
    )

    return model, history.history


def evaluate_lstm(
    model: "tf.keras.Model",
    data: Dict[str, np.ndarray],
    ticker: str,
) -> dict:
    """Evaluate LSTM on the test set and compute metrics."""
    import tensorflow as tf

    y_pred_scaled = model.predict(data["X_test"], verbose=0).flatten()
    y_true_scaled = data["y_test"]

    # Inverse transform if scaler is available
    scaler = data["scaler"]
    close_idx = data["close_idx"]

    if scaler is not None:
        # Reconstruct full feature matrix for inverse transform
        # y is the Close column; we need to place it back into the feature space
        # The sequences predict the Close at the LAST timestep, so we take
        # the last timestep's features from X_test for inverse transform context
        last_step = data["X_test"][:, -1, :].copy()
        last_step_true = last_step.copy()
        last_step_pred = last_step.copy()

        last_step_true[:, close_idx] = y_true_scaled
        last_step_pred[:, close_idx] = y_pred_scaled

        y_true = scaler.inverse_transform(last_step_true)[:, close_idx]
        y_pred = scaler.inverse_transform(last_step_pred)[:, close_idx]
    else:
        y_true = y_true_scaled
        y_pred = y_pred_scaled

    # Metrics
    mae  = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2   = float(1 - ss_res / (ss_tot + 1e-12))

    # Directional accuracy
    if len(y_true) > 1:
        dir_acc = float(np.mean(
            (np.diff(y_true) > 0) == (np.diff(y_pred) > 0)
        ) * 100)
    else:
        dir_acc = 50.0

    logger.info("  LSTM Test Results:")
    logger.info("    MAE:  $%.2f  |  RMSE: $%.2f  |  R²: %.4f  |  Dir. Acc: %.1f%%",
                mae, rmse, r2, dir_acc)

    return {
        "model": "LSTM",
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "r2": round(r2, 4),
        "directional_accuracy": round(dir_acc, 1),
    }


def save_lstm(model: "tf.keras.Model", ticker: str, metrics: dict) -> None:
    """Save the LSTM model and metadata to Saved Models/."""
    h5_path  = os.path.join(MODELS_DIR, f"lstm_model_{ticker}.h5")
    k_path   = os.path.join(MODELS_DIR, f"lstm_model_{ticker}.keras")

    model.save(h5_path)
    model.save(k_path)
    logger.info("LSTM model saved → %s", h5_path)

    # Save metadata
    meta = {"lookback": LOOKBACK, "metrics": metrics}
    joblib.dump(meta, os.path.join(MODELS_DIR, f"lstm_meta_{ticker}.pkl"))


def plot_training_history(history: dict, ticker: str) -> None:
    """Plot training and validation loss curves."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Loss
    axes[0].plot(history["loss"], label="Train Loss", color="#2E75B6", lw=1.5)
    axes[0].plot(history["val_loss"], label="Val Loss", color="#E74C3C", lw=1.5)
    axes[0].set_title(f"{ticker} – LSTM Training Loss", fontweight="bold")
    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("Huber Loss")
    axes[0].legend()
    axes[0].grid(True, alpha=0.25)

    # MAE
    if "mae" in history and "val_mae" in history:
        axes[1].plot(history["mae"], label="Train MAE", color="#2E75B6", lw=1.5)
        axes[1].plot(history["val_mae"], label="Val MAE", color="#E74C3C", lw=1.5)
    axes[1].set_title(f"{ticker} – LSTM Training MAE", fontweight="bold")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("MAE")
    axes[1].legend()
    axes[1].grid(True, alpha=0.25)

    plt.tight_layout()
    plt.savefig(os.path.join(MODELS_DIR, f"{ticker}_lstm_training.png"), dpi=150, bbox_inches="tight")
    plt.close()
    logger.info("  Training chart saved → %s_lstm_training.png", ticker)


def plot_predictions(
    y_true: np.ndarray, y_pred: np.ndarray, ticker: str,
) -> None:
    """Plot actual vs predicted prices for the LSTM model."""
    fig, ax = plt.subplots(figsize=(14, 6))
    x = range(len(y_true))

    ax.plot(x, y_true, color="#1F4E79", lw=1.5, label="Actual Price")
    ax.plot(x, y_pred, color="#E74C3C", lw=1.5, linestyle="--", label="LSTM Prediction")
    ax.fill_between(x, y_true, y_pred, alpha=0.08, color="#E74C3C")
    ax.set_title(f"{ticker} – LSTM: Actual vs Predicted", fontweight="bold")
    ax.set_ylabel("Price (USD)")
    ax.set_xlabel("Trading Days (Test Set)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.25)

    plt.tight_layout()
    plt.savefig(os.path.join(MODELS_DIR, f"{ticker}_lstm_predictions.png"), dpi=150, bbox_inches="tight")
    plt.close()
    logger.info("  Prediction chart saved → %s_lstm_predictions.png", ticker)


def main():
    parser = argparse.ArgumentParser(description="LSTM Model Trainer")
    parser.add_argument("--ticker",     default="QQQ", metavar="SYM",
                        help="Ticker symbol (default: QQQ)")
    parser.add_argument("--epochs",     default=80,  type=int, metavar="N",
                        help="Maximum training epochs (default: 80)")
    parser.add_argument("--batch-size", default=32,  type=int, metavar="N",
                        help="Batch size (default: 32)")
    parser.add_argument("--patience",   default=15,  type=int, metavar="N",
                        help="Early stopping patience (default: 15)")
    parser.add_argument("--lr",         default=0.001, type=float, metavar="LR",
                        help="Learning rate (default: 0.001)")
    parser.add_argument("--units",      default="128,64", metavar="U",
                        help="LSTM units 'layer1,layer2' (default: 128,64)")
    parser.add_argument("--all-tickers", action="store_true",
                        help="Train on all tickers with saved sequence data")
    args = parser.parse_args()

    if not _check_tf():
        logger.error("Cannot proceed without TensorFlow.")
        return

    lstm_units = tuple(int(u.strip()) for u in args.units.split(","))

    tickers = [args.ticker]
    if args.all_tickers:
        import glob
        npys = glob.glob(os.path.join(DATA_DIR, "X_train_*.npy"))
        tickers = sorted([
            os.path.basename(p).replace("X_train_", "").replace(".npy", "")
            for p in npys
        ])
        logger.info("Found %d tickers with LSTM data: %s", len(tickers), tickers)

    for ticker in tickers:
        logger.info("\n%s Training LSTM for %s %s", "=" * 45, ticker, "=" * 45)
        try:
            data = load_sequence_data(ticker)
        except FileNotFoundError as e:
            logger.error("%s", e)
            continue

        model, history = train_lstm(
            data, ticker,
            epochs=args.epochs,
            batch_size=args.batch_size,
            patience=args.patience,
        )

        metrics = evaluate_lstm(model, data, ticker)
        save_lstm(model, ticker, metrics)
        plot_training_history(history, ticker)

        # Get predictions for chart
        import tensorflow as tf
        y_pred_scaled = model.predict(data["X_test"], verbose=0).flatten()
        scaler = data["scaler"]
        close_idx = data["close_idx"]
        if scaler is not None:
            last_step = data["X_test"][:, -1, :].copy()
            last_step_true = last_step.copy()
            last_step_pred = last_step.copy()
            last_step_true[:, close_idx] = data["y_test"]
            last_step_pred[:, close_idx] = y_pred_scaled
            y_true = scaler.inverse_transform(last_step_true)[:, close_idx]
            y_pred = scaler.inverse_transform(last_step_pred)[:, close_idx]
        else:
            y_true = data["y_test"]
            y_pred = y_pred_scaled
        plot_predictions(y_true, y_pred, ticker)

    logger.info("\nLSTM training complete. Models saved to %s/", MODELS_DIR)


if __name__ == "__main__":
    main()
