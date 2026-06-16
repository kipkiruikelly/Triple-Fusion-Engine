"""
=============================================================
 Stock Market Price Prediction System
 Step 2: Model Training (Local)
 Kelvin Kipkirui | DAC-01-0010/2025 | Zetech University
=============================================================

Run this script from the project root:
    python model_training.py

Trains:
  1. Linear Regression  (baseline)
  2. Random Forest      (ensemble)

Note: LSTM is trained separately on Google Colab.
      Open Step2_LSTM_Training.ipynb in Colab.
"""

import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import MinMaxScaler
import joblib
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style='whitegrid')

# =============================================================
#  CONFIGURATION
# =============================================================
TICKER       = 'AAPL'
TRAIN_RATIO  = 0.80
VAL_RATIO    = 0.10
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, 'Data')
SAVED_MODELS = os.path.join(BASE_DIR, 'Saved Models')
os.makedirs(SAVED_MODELS, exist_ok=True)


# =============================================================
#  STEP 1: LOAD & PREPARE DATA
# =============================================================
def load_data(ticker):
    print(f"\n{'='*55}")
    print(f"  STEP 1: LOADING DATA")
    print(f"{'='*55}")

    df = pd.read_csv(
        os.path.join(DATA_DIR, f'{ticker}_featured.csv'),
        index_col='Date', parse_dates=True
    )

    # ── Build lag features ────────────────────────────────────
    # Give models access to the last 5 days of close prices
    # and returns — this is the key information for next-day prediction
    for lag in range(1, 6):
        df[f'Close_lag_{lag}'] = df['Close'].shift(lag)
        df[f'Return_lag_{lag}'] = df['Daily_Return'].shift(lag)

    # Target: next day's closing price
    df['Next_Close'] = df['Close'].shift(-1)

    # Drop NaN rows created by lags and target shift
    df.dropna(inplace=True)

    # Feature set: technical indicators + lag features
    feature_cols = [
        'Close', 'High', 'Low', 'Volume',
        'SMA_7', 'SMA_21', 'EMA_12', 'EMA_26',
        'RSI_14', 'MACD', 'MACD_Signal', 'MACD_Hist',
        'BB_Upper', 'BB_Lower', 'BB_Width',
        'Volume_SMA_10', 'Daily_Return',
        'Close_lag_1', 'Close_lag_2', 'Close_lag_3',
        'Close_lag_4', 'Close_lag_5',
        'Return_lag_1', 'Return_lag_2', 'Return_lag_3',
    ]

    # Chronological split
    n         = len(df)
    train_end = int(n * TRAIN_RATIO)
    val_end   = int(n * (TRAIN_RATIO + VAL_RATIO))

    X_train = df.iloc[:train_end][feature_cols].values
    X_val   = df.iloc[train_end:val_end][feature_cols].values
    X_test  = df.iloc[val_end:][feature_cols].values

    y_train = df.iloc[:train_end]['Next_Close'].values
    y_val   = df.iloc[train_end:val_end]['Next_Close'].values
    y_test  = df.iloc[val_end:]['Next_Close'].values

    # Scale features
    scaler     = MinMaxScaler()
    X_train_sc = scaler.fit_transform(X_train)
    X_val_sc   = scaler.transform(X_val)
    X_test_sc  = scaler.transform(X_test)

    # Save updated scaler for Flask app
    joblib.dump(scaler,       os.path.join(SAVED_MODELS, f'scaler_sklearn_{ticker}.pkl'))
    joblib.dump(feature_cols, os.path.join(SAVED_MODELS, f'feature_cols_sklearn_{ticker}.pkl'))

    print(f"  X_train : {X_train_sc.shape}")
    print(f"  X_val   : {X_val_sc.shape}")
    print(f"  X_test  : {X_test_sc.shape}")
    print(f"  Features: {len(feature_cols)}")
    print(f"  y_test range: ${y_test.min():.2f} → ${y_test.max():.2f}")
    print(f"  ✅ Data loaded.")

    return {
        'X_train': X_train_sc, 'X_val': X_val_sc, 'X_test': X_test_sc,
        'y_train': y_train,    'y_val': y_val,     'y_test': y_test,
        'feature_cols': feature_cols
    }


# =============================================================
#  HELPER: COMPUTE METRICS
# =============================================================
def compute_metrics(y_true, y_pred, model_name):
    mae     = mean_absolute_error(y_true, y_pred)
    rmse    = np.sqrt(mean_squared_error(y_true, y_pred))
    r2      = r2_score(y_true, y_pred)
    dir_acc = np.mean((np.diff(y_true) > 0) == (np.diff(y_pred) > 0)) * 100

    print(f"\n  ── {model_name} Results ──────────────────────")
    print(f"     MAE                 : ${mae:.2f}")
    print(f"     RMSE                : ${rmse:.2f}")
    print(f"     R² Score            : {r2:.4f}")
    print(f"     Directional Accuracy: {dir_acc:.1f}%")

    return {
        'model': model_name,
        'mae': round(mae, 2),
        'rmse': round(rmse, 2),
        'r2': round(r2, 4),
        'directional_accuracy': round(dir_acc, 1)
    }


# =============================================================
#  STEP 2: LINEAR REGRESSION
# =============================================================
def train_linear_regression(data):
    print(f"\n{'='*55}")
    print(f"  STEP 2: LINEAR REGRESSION (Baseline)")
    print(f"{'='*55}")

    model = LinearRegression()
    model.fit(data['X_train'], data['y_train'])
    print(f"  ✅ Linear Regression trained.")

    y_pred  = model.predict(data['X_test'])
    metrics = compute_metrics(data['y_test'], y_pred, 'Linear Regression')

    save_path = os.path.join(SAVED_MODELS, f'lr_model_{TICKER}.pkl')
    joblib.dump(model, save_path)
    print(f"  Model saved: {save_path}")

    return model, metrics, y_pred


# =============================================================
#  STEP 3: RANDOM FOREST
# =============================================================
def train_random_forest(data):
    print(f"\n{'='*55}")
    print(f"  STEP 3: RANDOM FOREST REGRESSOR")
    print(f"{'='*55}")

    print(f"  Training Random Forest (300 trees, max_depth=12)...")
    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=12,
        min_samples_split=4,
        min_samples_leaf=2,
        max_features=0.7,
        random_state=42,
        n_jobs=-1
    )
    model.fit(data['X_train'], data['y_train'])
    print(f"  ✅ Random Forest trained.")

    y_pred  = model.predict(data['X_test'])
    metrics = compute_metrics(data['y_test'], y_pred, 'Random Forest')

    # Feature importance
    importance_df = pd.DataFrame({
        'Feature':    data['feature_cols'],
        'Importance': model.feature_importances_
    }).sort_values('Importance', ascending=False)

    print(f"\n  ── Top 5 Most Important Features ───────────")
    for _, row in importance_df.head(5).iterrows():
        bar = '█' * int(row['Importance'] * 100)
        print(f"     {row['Feature']:<22} {row['Importance']:.4f}  {bar}")

    save_path = os.path.join(SAVED_MODELS, f'rf_model_{TICKER}.pkl')
    joblib.dump(model, save_path)
    importance_df.to_csv(
        os.path.join(SAVED_MODELS, f'rf_feature_importance_{TICKER}.csv'),
        index=False
    )
    print(f"\n  Model saved: {save_path}")

    return model, metrics, y_pred


# =============================================================
#  STEP 4: GENERATE CHARTS
# =============================================================
def generate_charts(y_true, lr_pred, rf_pred, rf_model, feature_cols):
    print(f"\n{'='*55}")
    print(f"  STEP 4: GENERATING CHARTS")
    print(f"{'='*55}")

    # Chart 1: Actual vs Predicted
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
    x = range(len(y_true))

    for ax, pred, name, color in [
        (axes[0], lr_pred, 'Linear Regression', '#E74C3C'),
        (axes[1], rf_pred, 'Random Forest',      '#F39C12'),
    ]:
        ax.plot(x, y_true, color='#1F4E79', lw=1.5, label='Actual Price')
        ax.plot(x, pred,   color=color,     lw=1.5,
                linestyle='--', label=f'{name} Prediction')
        ax.fill_between(x, y_true, pred, alpha=0.08, color=color)
        ax.set_title(f'{TICKER} — {name}: Actual vs Predicted',
                     fontweight='bold')
        ax.set_ylabel('Price (USD)')
        ax.legend(fontsize=9)

    axes[1].set_xlabel('Trading Days (Test Set)')
    plt.tight_layout()
    chart1 = os.path.join(SAVED_MODELS, f'{TICKER}_lr_rf_predictions.png')
    plt.savefig(chart1, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Chart saved: {chart1}")

    # Chart 2: Feature Importance (top 10)
    imp_df = pd.DataFrame({
        'Feature':    feature_cols,
        'Importance': rf_model.feature_importances_
    }).sort_values('Importance', ascending=True).tail(10)

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(imp_df['Feature'], imp_df['Importance'],
                   color='#2E75B6', alpha=0.8, edgecolor='white')
    ax.set_title(f'{TICKER} — Random Forest: Top 10 Feature Importances',
                 fontweight='bold', fontsize=13)
    ax.set_xlabel('Importance Score')
    for bar, val in zip(bars, imp_df['Importance']):
        ax.text(bar.get_width() + 0.001,
                bar.get_y() + bar.get_height() / 2,
                f'{val:.4f}', va='center', fontsize=9)
    plt.tight_layout()
    chart2 = os.path.join(SAVED_MODELS, f'{TICKER}_feature_importance.png')
    plt.savefig(chart2, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Chart saved: {chart2}")


# =============================================================
#  STEP 5: COMPARISON TABLE
# =============================================================
def print_comparison_table(all_metrics):
    print(f"\n{'='*65}")
    print(f"  MODEL COMPARISON — {TICKER} TEST SET")
    print(f"{'='*65}")
    print(f"  {'Model':<22} {'MAE':>8} {'RMSE':>8} {'R²':>8} {'Dir. Acc':>10}")
    print(f"  {'-'*58}")
    for m in all_metrics:
        print(
            f"  {m['model']:<22} "
            f"${m['mae']:>7.2f} "
            f"${m['rmse']:>7.2f} "
            f"{m['r2']:>8.4f} "
            f"{m['directional_accuracy']:>9.1f}%"
        )
    print(f"{'='*65}")
    print(f"\n  ⚠️  LSTM results will be added after Colab training.")
    print(f"      Open Step2_LSTM_Training.ipynb in Google Colab.")

    pd.DataFrame(all_metrics).to_csv(
        os.path.join(SAVED_MODELS, f'model_comparison_{TICKER}.csv'),
        index=False
    )
    print(f"\n  Results saved to: Saved Models/model_comparison_{TICKER}.csv")


# =============================================================
#  MAIN
# =============================================================
def main():
    print("\n" + "="*55)
    print("  STOCK MARKET PRICE PREDICTION SYSTEM")
    print("  Step 2: Model Training (Local)")
    print("  Kelvin Kipkirui | DAC-01-0010/2025")
    print("="*55)

    data = load_data(TICKER)

    lr_model, lr_metrics, lr_pred = train_linear_regression(data)
    rf_model, rf_metrics, rf_pred = train_random_forest(data)

    generate_charts(
        data['y_test'], lr_pred, rf_pred,
        rf_model, data['feature_cols']
    )
    print_comparison_table([lr_metrics, rf_metrics])

    print(f"\n{'='*55}")
    print(f"  ✅ LOCAL TRAINING COMPLETE")
    print(f"  Models saved to: Saved Models/")
    print(f"\n  NEXT → Open Step2_LSTM_Training.ipynb in Google Colab")
    print(f"{'='*55}\n")


if __name__ == '__main__':
    main()
