"""
=============================================================
 Stock Market Price Prediction System
 Step 1: Data Collection & Pipeline
 Kelvin Kipkirui | DAC-01-0010/2025 | Zetech University
=============================================================

Run this script from the project root:
    python data_pipeline.py

It will:
  1. Download historical OHLCV stock data via yfinance
  2. Clean the raw data
  3. Engineer all technical indicator features
  4. Split into train / validation / test sets
  5. Scale features using MinMaxScaler
  6. Build LSTM input sequences
  7. Save all outputs to the /data folder

Requirements:
    pip install yfinance pandas-ta scikit-learn matplotlib seaborn joblib
"""

# ── Standard library ──────────────────────────────────────────
import os
import warnings
warnings.filterwarnings('ignore')

# ── Data handling ──────────────────────────────────────────────
import numpy as np
import pandas as pd

# ── Data retrieval ─────────────────────────────────────────────
import yfinance as yf

# ── Technical indicators ───────────────────────────────────────
import pandas_ta as ta

# ── Preprocessing ──────────────────────────────────────────────
from sklearn.preprocessing import MinMaxScaler
import joblib

# ── Visualisation ──────────────────────────────────────────────
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

# =============================================================
#  CONFIGURATION — Edit these values to change stock/dates
# =============================================================
TICKER     = 'AAPL'         # Any valid Yahoo Finance ticker
START_DATE = '2019-01-01'
END_DATE   = '2024-01-01'
LOOKBACK   = 60             # LSTM lookback window in trading days

TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10
TEST_RATIO  = 0.10

# Paths
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# Features used for model training
MODEL_FEATURES = [
    'Open', 'High', 'Low', 'Close', 'Volume',
    'SMA_7', 'SMA_21', 'EMA_12', 'EMA_26',
    'RSI_14', 'MACD', 'MACD_Signal', 'MACD_Hist',
    'BB_Upper', 'BB_Lower', 'BB_Mid', 'BB_Width',
    'Volume_SMA_10', 'Daily_Return'
]


# =============================================================
#  STEP 1: DOWNLOAD DATA
# =============================================================
def download_stock_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Download historical OHLCV data for a given ticker from Yahoo Finance.

    Parameters
    ----------
    ticker : str   Yahoo Finance ticker symbol (e.g. 'AAPL', 'SCOM.NR')
    start  : str   Start date in 'YYYY-MM-DD' format
    end    : str   End date in 'YYYY-MM-DD' format

    Returns
    -------
    pd.DataFrame   DataFrame with columns: Open, High, Low, Close, Volume
    """
    print(f"\n{'='*55}")
    print(f"  STEP 1: DOWNLOADING DATA — {ticker}")
    print(f"{'='*55}")
    print(f"  Fetching {ticker} from {start} to {end}...")

    df = yf.download(
        ticker,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False
    )

    # Flatten multi-level columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    df.index = pd.to_datetime(df.index)
    df.index.name = 'Date'

    if df.empty:
        raise ValueError(
            f"No data returned for '{ticker}'. "
            "Check the ticker symbol and date range."
        )

    print(f"  ✅ {len(df):,} trading days downloaded.")
    print(f"     Range: {df.index.min().date()} → {df.index.max().date()}")
    return df


# =============================================================
#  STEP 2: CLEAN DATA
# =============================================================
def clean_stock_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean raw OHLCV data.

    Steps:
      - Remove duplicate index entries
      - Drop fully-NaN rows
      - Forward-fill remaining NaN values
      - Remove zero-volume rows (non-trading days)
      - Sort chronologically

    Parameters
    ----------
    df : pd.DataFrame   Raw OHLCV DataFrame

    Returns
    -------
    pd.DataFrame   Cleaned DataFrame
    """
    print(f"\n{'='*55}")
    print(f"  STEP 2: CLEANING DATA")
    print(f"{'='*55}")

    df = df.copy()
    n_orig = len(df)

    df = df[~df.index.duplicated(keep='first')]
    df.dropna(how='all', inplace=True)
    df.ffill(inplace=True)

    zero_vol = (df['Volume'] == 0).sum()
    df = df[df['Volume'] > 0]
    df.sort_index(inplace=True)

    print(f"  Original rows      : {n_orig:,}")
    print(f"  Zero-volume removed: {zero_vol}")
    print(f"  Final rows         : {len(df):,}")
    print(f"  Remaining NaNs     : {df.isnull().sum().sum()}")
    print(f"  ✅ Cleaning complete.")
    return df


# =============================================================
#  STEP 3: FEATURE ENGINEERING
# =============================================================
def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicator features from OHLCV data.

    Features:
      Trend      → SMA_7, SMA_21, EMA_12, EMA_26
      Momentum   → RSI_14, MACD, MACD_Signal, MACD_Hist
      Volatility → BB_Upper, BB_Lower, BB_Mid, BB_Width
      Volume     → Volume_SMA_10
      Return     → Daily_Return (%)
      Target     → Direction (1=Up, 0=Down for next day)

    Parameters
    ----------
    df : pd.DataFrame   Cleaned OHLCV DataFrame

    Returns
    -------
    pd.DataFrame   DataFrame with all features and target
    """
    print(f"\n{'='*55}")
    print(f"  STEP 3: FEATURE ENGINEERING")
    print(f"{'='*55}")

    df = df.copy()
    n_before = len(df)

    # Trend
    df['SMA_7']  = ta.sma(df['Close'], length=7)
    df['SMA_21'] = ta.sma(df['Close'], length=21)
    df['EMA_12'] = ta.ema(df['Close'], length=12)
    df['EMA_26'] = ta.ema(df['Close'], length=26)

    # Momentum
    df['RSI_14'] = ta.rsi(df['Close'], length=14)
    macd_df = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    df['MACD']        = macd_df['MACD_12_26_9']
    df['MACD_Signal'] = macd_df['MACDs_12_26_9']
    df['MACD_Hist']   = macd_df['MACDh_12_26_9']

    # Volatility
    bb_df = ta.bbands(df['Close'], length=20, std=2)
    # Column names vary by pandas-ta version — find them dynamically
    bb_upper_col = [c for c in bb_df.columns if c.startswith('BBU')][0]
    bb_lower_col = [c for c in bb_df.columns if c.startswith('BBL')][0]
    bb_mid_col   = [c for c in bb_df.columns if c.startswith('BBM')][0]
    df['BB_Upper'] = bb_df[bb_upper_col]
    df['BB_Lower'] = bb_df[bb_lower_col]
    df['BB_Mid']   = bb_df[bb_mid_col]
    df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid']

    # Volume
    df['Volume_SMA_10'] = ta.sma(df['Volume'], length=10)

    # Return
    df['Daily_Return'] = df['Close'].pct_change() * 100

    # Target: 1 if next-day close > today's close, else 0
    df['Direction'] = (df['Close'].shift(-1) > df['Close']).astype(int)

    # Drop NaN rows (indicator warm-up + target shift)
    df.dropna(inplace=True)

    print(f"  Input rows    : {n_before:,}")
    print(f"  Rows dropped  : {n_before - len(df)} (warm-up + target shift)")
    print(f"  Final rows    : {len(df):,}")
    print(f"  Total columns : {len(df.columns)}")
    print(f"  ✅ Feature engineering complete.")
    return df


# =============================================================
#  STEP 4: TRAIN / VALIDATION / TEST SPLIT
# =============================================================
def split_data(df: pd.DataFrame,
               train_ratio: float,
               val_ratio: float) -> tuple:
    """
    Split DataFrame chronologically into train, validation, and test sets.

    Parameters
    ----------
    df          : pd.DataFrame   Full featured DataFrame
    train_ratio : float          Proportion for training (e.g. 0.80)
    val_ratio   : float          Proportion for validation (e.g. 0.10)

    Returns
    -------
    tuple of (df_train, df_val, df_test)
    """
    print(f"\n{'='*55}")
    print(f"  STEP 4: CHRONOLOGICAL SPLIT")
    print(f"{'='*55}")

    n = len(df)
    train_end = int(n * train_ratio)
    val_end   = int(n * (train_ratio + val_ratio))

    df_train = df.iloc[:train_end]
    df_val   = df.iloc[train_end:val_end]
    df_test  = df.iloc[val_end:]

    print(f"  Train : {len(df_train):,} rows  "
          f"({df_train.index.min().date()} → {df_train.index.max().date()})")
    print(f"  Val   : {len(df_val):,} rows  "
          f"({df_val.index.min().date()} → {df_val.index.max().date()})")
    print(f"  Test  : {len(df_test):,} rows  "
          f"({df_test.index.min().date()} → {df_test.index.max().date()})")

    up_pct = df['Direction'].mean() * 100
    print(f"\n  Direction balance: Up={up_pct:.1f}%  Down={100-up_pct:.1f}%")
    print(f"  ✅ Split complete.")
    return df_train, df_val, df_test


# =============================================================
#  STEP 5: SCALE FEATURES
# =============================================================
def scale_features(df_train: pd.DataFrame,
                   df_val: pd.DataFrame,
                   df_test: pd.DataFrame,
                   features: list,
                   ticker: str) -> tuple:
    """
    Fit MinMaxScaler on training data only and transform all splits.

    Parameters
    ----------
    df_train, df_val, df_test : pd.DataFrame   Split DataFrames
    features                  : list            Feature column names
    ticker                    : str             Used for saving scaler file

    Returns
    -------
    tuple of (X_train_scaled, X_val_scaled, X_test_scaled, scaler, close_idx)
    """
    print(f"\n{'='*55}")
    print(f"  STEP 5: FEATURE SCALING")
    print(f"{'='*55}")

    scaler = MinMaxScaler(feature_range=(0, 1))

    X_train_scaled = scaler.fit_transform(df_train[features])
    X_val_scaled   = scaler.transform(df_val[features])
    X_test_scaled  = scaler.transform(df_test[features])

    close_idx = features.index('Close')

    # Save scaler and feature list
    scaler_path   = os.path.join(DATA_DIR, f'scaler_{ticker}.pkl')
    features_path = os.path.join(DATA_DIR, f'feature_cols_{ticker}.pkl')
    joblib.dump(scaler,   scaler_path)
    joblib.dump(features, features_path)

    print(f"  Features scaled  : {len(features)}")
    print(f"  Train shape      : {X_train_scaled.shape}")
    print(f"  Val shape        : {X_val_scaled.shape}")
    print(f"  Test shape       : {X_test_scaled.shape}")
    print(f"  Scaler saved to  : {scaler_path}")
    print(f"  ✅ Scaling complete.")
    return X_train_scaled, X_val_scaled, X_test_scaled, scaler, close_idx


# =============================================================
#  STEP 6: BUILD LSTM SEQUENCES
# =============================================================
def build_sequences(scaled_data: np.ndarray,
                    target_col: np.ndarray,
                    lookback: int) -> tuple:
    """
    Build overlapping LSTM sequences from scaled data.

    Input shape required by LSTM: (samples, timesteps, features)

    Parameters
    ----------
    scaled_data : np.ndarray   2D array (n_rows, n_features)
    target_col  : np.ndarray   1D array of target values (scaled Close)
    lookback    : int           Number of previous days to use as context

    Returns
    -------
    X : np.ndarray   Shape (n_rows - lookback, lookback, n_features)
    y : np.ndarray   Shape (n_rows - lookback,)
    """
    X, y = [], []
    for i in range(lookback, len(scaled_data)):
        X.append(scaled_data[i - lookback : i])
        y.append(target_col[i])
    return np.array(X), np.array(y)


# =============================================================
#  STEP 7: VISUALISE AND SAVE
# =============================================================
def save_charts(df_featured: pd.DataFrame,
                df_train: pd.DataFrame,
                df_val: pd.DataFrame,
                df_test: pd.DataFrame,
                ticker: str) -> None:
    """Generate and save key EDA charts to the data directory."""

    sns.set_theme(style='whitegrid')

    # Chart 1: Price + Moving Averages
    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)

    axes[0].plot(df_featured.index, df_featured['Close'],
                 color='#1F4E79', lw=1.5, label='Close')
    axes[0].plot(df_featured.index, df_featured['SMA_7'],
                 color='#E67E22', lw=1.1, linestyle='--', label='SMA 7')
    axes[0].plot(df_featured.index, df_featured['SMA_21'],
                 color='#27AE60', lw=1.1, linestyle='--', label='SMA 21')
    axes[0].fill_between(df_featured.index,
                         df_featured['BB_Upper'], df_featured['BB_Lower'],
                         alpha=0.08, color='#2E75B6', label='Bollinger Bands')
    axes[0].set_title(f'{ticker} — Price, MAs & Bollinger Bands', fontweight='bold')
    axes[0].set_ylabel('Price (USD)')
    axes[0].legend(loc='upper left', fontsize=9)

    axes[1].plot(df_featured.index, df_featured['RSI_14'],
                 color='#8E44AD', lw=1.2, label='RSI (14)')
    axes[1].axhline(70, color='red',   lw=0.8, linestyle='--', alpha=0.6)
    axes[1].axhline(30, color='green', lw=0.8, linestyle='--', alpha=0.6)
    axes[1].set_title(f'{ticker} — RSI (14)', fontweight='bold')
    axes[1].set_ylabel('RSI')
    axes[1].set_ylim(0, 100)
    axes[1].legend(fontsize=9)

    axes[2].plot(df_featured.index, df_featured['MACD'],
                 color='#2E75B6', lw=1.2, label='MACD')
    axes[2].plot(df_featured.index, df_featured['MACD_Signal'],
                 color='#E74C3C', lw=1.2, label='Signal')
    colors = df_featured['MACD_Hist'].apply(
        lambda x: '#27AE60' if x >= 0 else '#E74C3C'
    )
    axes[2].bar(df_featured.index, df_featured['MACD_Hist'],
                color=colors, alpha=0.4, width=1)
    axes[2].axhline(0, color='black', lw=0.5)
    axes[2].set_title(f'{ticker} — MACD', fontweight='bold')
    axes[2].set_ylabel('MACD')
    axes[2].set_xlabel('Date')
    axes[2].legend(fontsize=9)

    plt.tight_layout()
    chart1_path = os.path.join(DATA_DIR, f'{ticker}_indicators.png')
    plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Chart saved: {chart1_path}")

    # Chart 2: Train/Val/Test split
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(df_train.index, df_train['Close'], color='#1F4E79', lw=1.5,
            label=f'Train ({len(df_train):,})')
    ax.plot(df_val.index,   df_val['Close'],   color='#F39C12', lw=1.5,
            label=f'Validation ({len(df_val):,})')
    ax.plot(df_test.index,  df_test['Close'],  color='#E74C3C', lw=1.5,
            label=f'Test ({len(df_test):,})')
    ax.axvline(df_val.index[0],  color='#F39C12', linestyle='--', lw=1, alpha=0.5)
    ax.axvline(df_test.index[0], color='#E74C3C', linestyle='--', lw=1, alpha=0.5)
    ax.set_title(f'{ticker} — Train / Validation / Test Split', fontweight='bold')
    ax.set_ylabel('Close Price (USD)')
    ax.set_xlabel('Date')
    ax.legend()
    plt.tight_layout()
    chart2_path = os.path.join(DATA_DIR, f'{ticker}_split.png')
    plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Chart saved: {chart2_path}")


# =============================================================
#  MAIN — Run the full pipeline
# =============================================================
def main():
    print("\n" + "="*55)
    print("  STOCK MARKET PRICE PREDICTION SYSTEM")
    print("  Step 1: Data Collection & Pipeline")
    print("  Kelvin Kipkirui | DAC-01-0010/2025")
    print("="*55)

    # ── 1. Download ───────────────────────────────────────────
    df_raw = download_stock_data(TICKER, START_DATE, END_DATE)

    # ── 2. Clean ──────────────────────────────────────────────
    df_clean = clean_stock_data(df_raw)

    # ── 3. Feature engineering ────────────────────────────────
    df_featured = engineer_features(df_clean)

    # ── 4. Split ──────────────────────────────────────────────
    df_train, df_val, df_test = split_data(df_featured, TRAIN_RATIO, VAL_RATIO)

    # ── 5. Scale ──────────────────────────────────────────────
    (X_train_sc, X_val_sc, X_test_sc,
     scaler, close_idx) = scale_features(
        df_train, df_val, df_test, MODEL_FEATURES, TICKER
    )

    # ── 6. Build sequences ────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  STEP 6: BUILDING LSTM SEQUENCES")
    print(f"{'='*55}")

    X_train, y_train = build_sequences(X_train_sc, X_train_sc[:, close_idx], LOOKBACK)
    X_val,   y_val   = build_sequences(X_val_sc,   X_val_sc[:,   close_idx], LOOKBACK)
    X_test,  y_test  = build_sequences(X_test_sc,  X_test_sc[:,  close_idx], LOOKBACK)

    print(f"  X_train : {X_train.shape}")
    print(f"  X_val   : {X_val.shape}")
    print(f"  X_test  : {X_test.shape}")

    # ── 7. Save all outputs ───────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  STEP 7: SAVING OUTPUTS")
    print(f"{'='*55}")

    np.save(os.path.join(DATA_DIR, f'X_train_{TICKER}.npy'), X_train)
    np.save(os.path.join(DATA_DIR, f'X_val_{TICKER}.npy'),   X_val)
    np.save(os.path.join(DATA_DIR, f'X_test_{TICKER}.npy'),  X_test)
    np.save(os.path.join(DATA_DIR, f'y_train_{TICKER}.npy'), y_train)
    np.save(os.path.join(DATA_DIR, f'y_val_{TICKER}.npy'),   y_val)
    np.save(os.path.join(DATA_DIR, f'y_test_{TICKER}.npy'),  y_test)
    df_featured.to_csv(os.path.join(DATA_DIR, f'{TICKER}_featured.csv'))

    save_charts(df_featured, df_train, df_val, df_test, TICKER)

    print(f"\n{'='*55}")
    print(f"  ✅ PIPELINE COMPLETE")
    print(f"{'='*55}")
    print(f"  All files saved to: {DATA_DIR}/")
    print(f"\n  NEXT STEP → Run: python model_training.py")
    print(f"{'='*55}\n")


if __name__ == '__main__':
    main()
