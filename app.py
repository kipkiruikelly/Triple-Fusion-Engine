"""
app.py
Stock Market Price Prediction System

Flask web application that serves next-day stock price predictions using
Linear Regression and Random Forest models trained on historical OHLCV data
with technical indicator features.

Usage:
    python app.py

Then open: http://127.0.0.1:5000

Author: Kelvin Kipkirui | DAC-01-0010/2025 | Zetech University
"""

import os
import json
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import joblib
import yfinance as yf
import ta
from flask import Flask, render_template, request, jsonify

app = Flask(__name__, template_folder="Web Pages", static_folder="Static Files")
app.secret_key = os.environ.get("SECRET_KEY", "smp-dev-key-2025")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")

# Load models at startup
print("Loading models...")
lr_model     = joblib.load(os.path.join(MODELS_DIR, "lr_model_AAPL.pkl"))
rf_model     = joblib.load(os.path.join(MODELS_DIR, "rf_model_AAPL.pkl"))
scaler       = joblib.load(os.path.join(MODELS_DIR, "scaler_sklearn_AAPL.pkl"))
feature_cols = joblib.load(os.path.join(MODELS_DIR, "feature_cols_sklearn_AAPL.pkl"))
print("Models loaded.")


def build_features(df):
    """Compute all technical indicator and lag features from OHLCV data."""
    df = df.copy()

    df["SMA_7"]  = ta.trend.sma_indicator(df["Close"], window=7)
    df["SMA_21"] = ta.trend.sma_indicator(df["Close"], window=21)
    df["EMA_12"] = ta.trend.ema_indicator(df["Close"], window=12)
    df["EMA_26"] = ta.trend.ema_indicator(df["Close"], window=26)
    df["RSI_14"] = ta.momentum.rsi(df["Close"], window=14)

    macd_obj = ta.trend.MACD(df["Close"], window_fast=12, window_slow=26, window_sign=9)
    df["MACD"]        = macd_obj.macd()
    df["MACD_Signal"] = macd_obj.macd_signal()
    df["MACD_Hist"]   = macd_obj.macd_diff()

    bb_obj = ta.volatility.BollingerBands(df["Close"], window=20, window_dev=2)
    df["BB_Upper"] = bb_obj.bollinger_hband()
    df["BB_Lower"] = bb_obj.bollinger_lband()
    df["BB_Mid"]   = bb_obj.bollinger_mavg()
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"]

    df["Volume_SMA_10"] = ta.trend.sma_indicator(df["Volume"], window=10)
    df["Daily_Return"]  = df["Close"].pct_change() * 100

    for lag in range(1, 6):
        df[f"Close_lag_{lag}"]  = df["Close"].shift(lag)
        df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    df.dropna(inplace=True)
    return df


def run_prediction(ticker):
    """Download data, engineer features, and return prediction results."""
    yf_ticker = ticker.replace(".", "-")
    df = yf.download(yf_ticker, period="6mo", auto_adjust=True, progress=False)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if df.empty or len(df) < 70:
        raise ValueError(f"Not enough data for '{ticker}'. Please check the ticker symbol.")

    df = build_features(df)

    if df.empty:
        raise ValueError("Feature engineering failed — insufficient data history.")

    current_price = float(df["Close"].iloc[-1])
    X = scaler.transform(df[feature_cols].iloc[-1:].values)

    lr_pred = float(lr_model.predict(X)[0])
    rf_ret  = float(rf_model.predict(X)[0])
    rf_pred = current_price * (1 + rf_ret / 100)

    price_change = lr_pred - current_price
    direction    = "Up" if price_change > 0 else "Down"
    recent_vol   = float(df["Daily_Return"].tail(20).std())
    change_pct   = abs(price_change / current_price * 100)
    confidence   = min(95, max(51, 50 + (change_pct / max(recent_vol, 0.1)) * 10))

    chart_df     = df.tail(90)
    chart_dates  = [d.strftime("%Y-%m-%d") for d in chart_df.index]
    chart_prices = [round(float(p), 2) for p in chart_df["Close"]]
    chart_sma7   = [round(float(p), 2) for p in chart_df["SMA_7"]]
    chart_sma21  = [round(float(p), 2) for p in chart_df["SMA_21"]]

    rsi       = round(float(df["RSI_14"].iloc[-1]), 1)
    macd_val  = round(float(df["MACD"].iloc[-1]), 3)
    macd_hist = float(df["MACD_Hist"].iloc[-1])

    if rsi >= 70:
        rsi_signal = "Overbought"
    elif rsi <= 30:
        rsi_signal = "Oversold"
    else:
        rsi_signal = "Neutral"

    return {
        "ticker"       : ticker.upper(),
        "current_price": round(current_price, 2),
        "lr_pred"      : round(lr_pred, 2),
        "rf_pred"      : round(rf_pred, 2),
        "lstm_pred"    : "N/A",
        "primary_pred" : round(lr_pred, 2),
        "price_change" : round(price_change, 2),
        "change_pct"   : round(change_pct, 2),
        "direction"    : direction,
        "confidence"   : round(confidence, 1),
        "chart_dates"  : json.dumps(chart_dates),
        "chart_prices" : json.dumps(chart_prices),
        "chart_sma7"   : json.dumps(chart_sma7),
        "chart_sma21"  : json.dumps(chart_sma21),
        "rsi"          : rsi,
        "rsi_signal"   : rsi_signal,
        "macd"         : macd_val,
        "macd_signal"  : "Bullish" if macd_hist > 0 else "Bearish",
        "bb_upper"     : round(float(df["BB_Upper"].iloc[-1]), 2),
        "bb_lower"     : round(float(df["BB_Lower"].iloc[-1]), 2),
        "as_of"        : df.index[-1].strftime("%B %d, %Y"),
    }


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/predict", methods=["POST"])
def predict():
    ticker = request.form.get("ticker", "").upper().strip()

    if not ticker:
        return render_template("index.html", error="Please enter a stock ticker symbol.")

    if len(ticker) > 10 or not ticker.replace(".", "").isalpha():
        return render_template("index.html",
                               error=f'"{ticker}" is not a valid ticker. Try AAPL, TSLA, or MSFT.')
    try:
        result = run_prediction(ticker)
        return render_template("result.html", **result)
    except ValueError as e:
        return render_template("index.html", error=str(e))
    except Exception:
        return render_template("index.html",
                               error=f'Could not fetch data for "{ticker}". Please check the symbol and try again.')


@app.route("/api/predict/", methods=["GET"])
def api_predict_empty():
    return jsonify({"status": "error", "message": "Please provide a ticker symbol, e.g. /api/predict/AAPL"}), 400


@app.route("/api/predict/<ticker>", methods=["GET"])
def api_predict(ticker):
    try:
        result = run_prediction(ticker.upper())
        for key in ["chart_dates", "chart_prices", "chart_sma7", "chart_sma21"]:
            result.pop(key, None)
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


if __name__ == "__main__":
    print("Stock Market Price Prediction System")
    print("Running at: http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000)
