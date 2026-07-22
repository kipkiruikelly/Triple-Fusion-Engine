"""
predictor_api.py
Standalone REST API for the ML prediction service.

Thin Flask app exposing /predict and /health endpoints. Designed to run
as a separate Docker service (tfe-predictor) behind the web UI or
called directly by the trading engine.

Usage:
    gunicorn --bind 0.0.0.0:5001 predictor_api:app

Author: BullLogic
"""

import os
import sys
import logging
import time

from flask import Flask, request, jsonify

# Ensure the project root is on sys.path for sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("predictor_api")

app = Flask(__name__)
_app_start = time.time()
_request_count = 0


@app.route("/health")
def health():
    """Liveness/readiness probe for Docker and load balancers."""
    import predictor as _pred
    return jsonify({
        "status": "ok",
        "service": "predictor-api",
        "uptime_seconds": round(time.time() - _app_start, 1),
        "requests": _request_count,
        "ml_available": _pred._ML_AVAILABLE if hasattr(_pred, "_ML_AVAILABLE") else True,
    })


@app.route("/predict", methods=["POST"])
def predict():
    """Return a full prediction result for a given ticker and interval.

    Request JSON:
        {"ticker": "AAPL", "interval": "1d"}   # interval optional, default "1d"

    Response JSON:
        {"ticker": "AAPL", "direction": "Up", "confidence": 72.5, ...}
    """
    global _request_count
    _request_count += 1

    data = request.get_json(silent=True) or {}
    ticker   = data.get("ticker", "").strip().upper()
    interval = data.get("interval", "1d")

    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    try:
        from predictor import run_prediction
        result = run_prediction(ticker, interval)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e), "ticker": ticker}), 400
    except Exception as e:
        logger.exception("Prediction failed for %s", ticker)
        return jsonify({"error": "Internal prediction error", "ticker": ticker}), 500


@app.route("/signal", methods=["POST"])
def signal():
    """Return a compact trading signal for the MT5 engine.

    Request JSON:
        {"ticker": "AAPL", "interval": "1d"}

    Response JSON:
        {"action": "BUY", "confidence": 68.0, ...}
    """
    global _request_count
    _request_count += 1

    data = request.get_json(silent=True) or {}
    ticker   = data.get("ticker", "").strip().upper()
    interval = data.get("interval", "1d")

    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    try:
        from predictor import ml_signal
        result = ml_signal(ticker, interval)
        return jsonify(result)
    except Exception as e:
        logger.exception("Signal failed for %s", ticker)
        return jsonify({"action": "HOLD", "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
