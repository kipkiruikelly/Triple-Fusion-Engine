"""mt5_config.py, persistent tunable configuration for the MT5 trading engine.

Defaults here mirror the values that were previously hardcoded inline in
mt5_trading.py (verified against that file, not against config.py's
TP_ATR_MULT/SL_ATR_MULT, which belong to a different subsystem and were
never actually read by mt5_trading.place_order). Saved to Data/mt5_config.json,
never to .env - this is algorithm tuning, not secrets.
"""

import os
import json

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data", "mt5_config.json")

DEFAULTS = {
    # ICT gate
    "ict_score_threshold":   3,
    "total_score_threshold": 5,
    # PD zone (position within the 60-bar range)
    "pd_zone_buy_strong":    0.40,
    "pd_zone_buy_weak":      0.50,
    "pd_zone_sell_strong":   0.60,
    "pd_zone_sell_weak":     0.50,
    # ICT score points
    "ob_pts":                2,
    "fvg_pts":               1,
    "sweep_pts":             2,
    "displacement_pts":      1,
    # ML layer
    "use_ml":                True,
    "ml_agreement_pts":      2,
    "ml_conflict_pts":       -1,
    # Technical indicators
    "rsi_period":            14,
    "rsi_oversold":          30,
    "rsi_overbought":        70,
    "rsi_soft_os":           35,
    "rsi_soft_ob":           65,
    "macd_fast":             12,
    "macd_slow":             26,
    "macd_signal_period":    9,
    "macd_cross_pts":        2,
    "macd_trend_pts":        1,
    "ema_period":            20,
    # Risk management
    "risk_pct":              1.0,
    "sl_multiplier":         1.5,
    "tp_multiplier":         3.0,
    "atr_period":            14,
    "max_positions":         3,
    "daily_loss_limit":      0.05,
    "max_lot":               10.0,
    "min_lot":               0.01,
    "paper_balance":         10000.0,
    # Trading loop
    "symbol":                "EURUSD",
    "timeframe":             "M5",
    "interval_sec":          60,
}


def load() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                saved = json.load(f)
            return {**DEFAULTS, **saved}   # merge so new keys always appear
        except Exception:
            pass
    return dict(DEFAULTS)


def save(config: dict) -> dict:
    merged = {**load(), **config}
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, sort_keys=True)
    return merged


def reset() -> dict:
    if os.path.exists(CONFIG_PATH):
        os.remove(CONFIG_PATH)
    return dict(DEFAULTS)
