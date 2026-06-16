"""
=============================================================
 Stock Market Price Prediction System
 Step 3: Flask Web Application
 Kelvin Kipkirui | DAC-01-0010/2025 | Zetech University
=============================================================

Run locally:
    python app.py

Then open: http://127.0.0.1:5000
"""

import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import joblib
import json
from datetime import datetime, timedelta

import yfinance as yf
import pandas_ta as ta

from flask import Flask, render_template, request, jsonify

app = Flask(__name__, template_folder='Web Pages', static_folder='Static Files')
app.secret_key = 'stock_market_predictor_2025'

# =============================================================
#  PATHS
# =============================================================
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
SAVED_MODELS = os.path.join(BASE_DIR, 'Saved Models')
DATA_DIR     = os.path.join(BASE_DIR, 'Data')

# =============================================================
#  LOAD MODELS AT STARTUP
# =============================================================
print("Loading models...")

lr_model     = joblib.load(os.path.join(SAVED_MODELS, 'lr_model_AAPL.pkl'))
rf_model     = joblib.load(os.path.join(SAVED_MODELS, 'rf_model_AAPL.pkl'))
scaler       = joblib.load(os.path.join(SAVED_MODELS, 'scaler_sklearn_AAPL.pkl'))
feature_cols = joblib.load(os.path.join(SAVED_MODELS, 'feature_cols_sklearn_AAPL.pkl'))

# Load LSTM if available
# LSTM disabled locally — TensorFlow not supported on Python 3.13/Mac
# LSTM model was trained on Google Colab and results are documented separately
lstm_model    = None
lstm_scaler   = None
lstm_features = None
print("ℹ️  LSTM disabled locally (use Colab for LSTM inference).")

print("✅ Models ready.")

# =============================================================
#  FEATURE ENGINEERING
# =============================================================
def engineer_features(df):
    """Compute all technical indicators from OHLCV data."""
    df = df.copy()

    df['SMA_7']  = ta.sma(df['Close'], length=7)
    df['SMA_21'] = ta.sma(df['Close'], length=21)
    df['EMA_12'] = ta.ema(df['Close'], length=12)
    df['EMA_26'] = ta.ema(df['Close'], length=26)
    df['RSI_14'] = ta.rsi(df['Close'], length=14)

    macd_df = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    df['MACD']        = macd_df['MACD_12_26_9']
    df['MACD_Signal'] = macd_df['MACDs_12_26_9']
    df['MACD_Hist']   = macd_df['MACDh_12_26_9']

    bb_df = ta.bbands(df['Close'], length=20, std=2)
    bb_upper_col = [c for c in bb_df.columns if c.startswith('BBU')][0]
    bb_lower_col = [c for c in bb_df.columns if c.startswith('BBL')][0]
    bb_mid_col   = [c for c in bb_df.columns if c.startswith('BBM')][0]
    df['BB_Upper'] = bb_df[bb_upper_col]
    df['BB_Lower'] = bb_df[bb_lower_col]
    df['BB_Mid']   = bb_df[bb_mid_col]
    df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid']

    df['Volume_SMA_10'] = ta.sma(df['Volume'], length=10)
    df['Daily_Return']  = df['Close'].pct_change() * 100

    # Lag features
    for lag in range(1, 6):
        df[f'Close_lag_{lag}']  = df['Close'].shift(lag)
        df[f'Return_lag_{lag}'] = df['Daily_Return'].shift(lag)

    df.dropna(inplace=True)
    return df


def build_lstm_sequences(df, lstm_feats, lstm_sc, lookback=60):
    """Build LSTM input sequences from featured DataFrame."""
    scaled = lstm_sc.transform(df[lstm_feats].values)
    if len(scaled) < lookback:
        return None
    return scaled[-lookback:].reshape(1, lookback, len(lstm_feats))


# =============================================================
#  PREDICTION PIPELINE
# =============================================================
def predict(ticker):
    """
    Run the full prediction pipeline for a given ticker.

    Returns a dict with:
        current_price, lr_pred, rf_pred, lstm_pred,
        direction, confidence, chart_data, rsi, macd
    """
    # Download 6 months of data (enough for all indicators + lags)
    df = yf.download(ticker, period='6mo', auto_adjust=True, progress=False)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if df.empty or len(df) < 70:
        raise ValueError(f"Not enough data for '{ticker}'. Check the ticker symbol.")

    # Engineer features
    df = engineer_features(df)

    if df.empty:
        raise ValueError("Feature engineering failed — not enough data.")

    # Current price
    current_price = float(df['Close'].iloc[-1])

    # ── sklearn predictions ───────────────────────────────────
    X = df[feature_cols].iloc[-1:].values
    X_scaled = scaler.transform(X)

    lr_pred = float(lr_model.predict(X_scaled)[0])
    rf_pred = float(rf_model.predict(X_scaled)[0])

    # ── LSTM prediction ───────────────────────────────────────
    lstm_pred = None
    if lstm_model is not None:
        try:
            X_lstm = build_lstm_sequences(df, lstm_features, lstm_scaler)
            if X_lstm is not None:
                pred_scaled = lstm_model.predict(X_lstm, verbose=0).flatten()[0]
                close_idx   = lstm_features.index('Close')
                dummy       = np.zeros((1, len(lstm_features)))
                dummy[0, close_idx] = pred_scaled
                lstm_pred = float(lstm_scaler.inverse_transform(dummy)[0, close_idx])
        except Exception as e:
            print(f"LSTM prediction error: {e}")

    # ── Direction and confidence ──────────────────────────────
    # Use Linear Regression as primary predictor (best performer)
    primary_pred = lr_pred
    price_change = primary_pred - current_price
    direction    = 'Up' if price_change > 0 else 'Down'

    # Confidence based on magnitude of predicted change vs recent volatility
    recent_vol  = float(df['Daily_Return'].tail(20).std())
    change_pct  = abs(price_change / current_price * 100)
    confidence  = min(95, max(51, 50 + (change_pct / max(recent_vol, 0.1)) * 10))

    # ── Chart data (last 90 days) ─────────────────────────────
    chart_df = df.tail(90)
    chart_dates  = [d.strftime('%Y-%m-%d') for d in chart_df.index]
    chart_prices = [round(float(p), 2) for p in chart_df['Close']]
    chart_sma7   = [round(float(p), 2) for p in chart_df['SMA_7']]
    chart_sma21  = [round(float(p), 2) for p in chart_df['SMA_21']]

    # ── Technical signals ─────────────────────────────────────
    rsi  = round(float(df['RSI_14'].iloc[-1]), 1)
    macd = round(float(df['MACD'].iloc[-1]), 3)
    bb_upper = round(float(df['BB_Upper'].iloc[-1]), 2)
    bb_lower = round(float(df['BB_Lower'].iloc[-1]), 2)

    # RSI signal
    if rsi >= 70:
        rsi_signal = 'Overbought'
    elif rsi <= 30:
        rsi_signal = 'Oversold'
    else:
        rsi_signal = 'Neutral'

    # MACD signal
    macd_hist = float(df['MACD_Hist'].iloc[-1])
    macd_signal = 'Bullish' if macd_hist > 0 else 'Bearish'

    return {
        'ticker'       : ticker.upper(),
        'current_price': round(current_price, 2),
        'lr_pred'      : round(lr_pred, 2),
        'rf_pred'      : round(rf_pred, 2),
        'lstm_pred'    : round(lstm_pred, 2) if lstm_pred else 'N/A',
        'primary_pred' : round(primary_pred, 2),
        'price_change' : round(price_change, 2),
        'change_pct'   : round(change_pct, 2),
        'direction'    : direction,
        'confidence'   : round(confidence, 1),
        'chart_dates'  : json.dumps(chart_dates),
        'chart_prices' : json.dumps(chart_prices),
        'chart_sma7'   : json.dumps(chart_sma7),
        'chart_sma21'  : json.dumps(chart_sma21),
        'rsi'          : rsi,
        'rsi_signal'   : rsi_signal,
        'macd'         : macd,
        'macd_signal'  : macd_signal,
        'bb_upper'     : bb_upper,
        'bb_lower'     : bb_lower,
        'as_of'        : df.index[-1].strftime('%B %d, %Y'),
    }


# =============================================================
#  ROUTES
# =============================================================
@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')


@app.route('/predict', methods=['POST'])
def predict_route():
    ticker = request.form.get('ticker', '').upper().strip()

    if not ticker:
        return render_template('index.html', error='Please enter a stock ticker symbol.')

    # Basic validation
    if len(ticker) > 10 or not ticker.replace('.', '').isalpha():
        return render_template('index.html',
                               error=f'"{ticker}" does not look like a valid ticker. Try AAPL, TSLA, or MSFT.')
    try:
        result = predict(ticker)
        return render_template('result.html', **result)
    except ValueError as e:
        return render_template('index.html', error=str(e))
    except Exception as e:
        return render_template('index.html',
                               error=f'Could not fetch data for "{ticker}". Please check the symbol and try again.')


@app.route('/api/predict/<ticker>', methods=['GET'])
def api_predict(ticker):
    """JSON API endpoint for programmatic access."""
    try:
        result = predict(ticker.upper())
        # Remove chart JSON strings for clean API response
        result.pop('chart_dates', None)
        result.pop('chart_prices', None)
        result.pop('chart_sma7', None)
        result.pop('chart_sma21', None)
        return jsonify({'status': 'success', 'data': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400


# =============================================================
#  MAIN
# =============================================================
if __name__ == '__main__':
    print("\n" + "="*55)
    print("  STOCK MARKET PRICE PREDICTION SYSTEM")
    print("  Flask Web Application")
    print("  Kelvin Kipkirui | DAC-01-0010/2025")
    print("="*55)
    print("  Open your browser at: http://127.0.0.1:5000")
    print("="*55 + "\n")
    app.run(debug=True, port=5000)
