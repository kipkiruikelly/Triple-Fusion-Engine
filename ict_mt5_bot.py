#!/usr/bin/env python
"""
ict_mt5_bot.py

An institutional-grade trading robot integrating ICT (Inner Circle Trader) concepts
with machine learning models. Trades on MetaTrader 5 (MT5) with strict risk management.

Key Mechanics:
  1. Directional Bias: Derived using the 200 SMA and 60-bar Swing Highs/Lows.
  2. ICT Gate (Layer 1): Analyzes candle displacement, Order Blocks (OB), and Fair Value Gaps (FVG).
  3. ML Confluence (Layer 2): Aggregates voting flags from our top 5 models (Stacking Ensemble,
     XGBoost, Random Forest, Linear Regression, and LightGBM).
  4. Risk Management: 1:2 risk-reward ratios using ATR-based Stop Losses (1.5x) and Take Profits (3.0x),
     daily drawdown circuit breakers (5% halt), and max active position limits.

DISCLAIMER: All algorithmic trading systems carry risk. Due to price volatility, news events, slippage,
and broker spread, a 100% win rate is mathematically impossible in real-world markets. This robot focuses
on strict confluences and capital preservation to maintain a solid risk-adjusted return profile.
"""

import os
import sys
import time
import datetime
import numpy as np
import pandas as pd
import ta

# Initialize Paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mt5_config
import ict_features
from predictor import ml_signal

# Attempt to load MetaTrader5
MT5_AVAILABLE = False
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    pass


class ICTMT5Robot:
    def __init__(self, symbol: str = "EURUSD", timeframe: str = "M5", risk_pct: float = 1.0):
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.risk_pct = risk_pct
        self.cfg = mt5_config.load()
        self.running = False
        self.paper_mode = not MT5_AVAILABLE
        self.positions = {}
        self.ticket_counter = 1000

        # Initialize paper balance
        self.balance = self.cfg.get("paper_balance", 10000.0)
        self.equity = self.balance
        self.daily_start_equity = self.balance

        print("=== ICT + ML CONFLUENCE ROBOT INITIALIZED ===")
        if self.paper_mode:
            print("[INFO] MetaTrader 5 Python package not available. Running in Safe Paper-Trading Mode.")
        else:
            print("[INFO] MT5 integration active. Ready to connect to terminal.")

    def connect(self) -> bool:
        if self.paper_mode:
            print("[INFO] Connected to Local Paper Engine.")
            return True

        if not mt5.initialize():
            print(f"[ERROR] MT5 initialization failed: {mt5.last_error()}")
            self.paper_mode = True
            print("[WARN] Falling back to Paper-Trading Mode.")
            return True

        print("[INFO] MetaTrader 5 Terminal connected successfully.")
        return True

    def get_market_data(self, count: int = 150) -> pd.DataFrame:
        """Fetch candle data and compute base ICT + indicators features."""
        if self.paper_mode:
            # Simulate historical bars
            idx = pd.date_range(end=datetime.datetime.now(), periods=count, freq="5min")
            prices = 1.1000 + np.cumsum(np.random.normal(0, 0.0005, count))
            df = pd.DataFrame({
                "Open": prices - np.random.normal(0, 0.0002, count),
                "High": prices + abs(np.random.normal(0, 0.0003, count)),
                "Low": prices - abs(np.random.normal(0, 0.0003, count)),
                "Close": prices,
                "Volume": np.random.randint(100, 1000, count)
            }, index=idx)
            return ict_features.add_base_ta(df)

        # Map string timeframe to MT5 constant
        tf_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1,
            "D1": mt5.TIMEFRAME_D1
        }
        mt5_tf = tf_map.get(self.timeframe, mt5.TIMEFRAME_M5)

        rates = mt5.copy_rates_from_pos(self.symbol, mt5_tf, 0, count)
        if rates is None or len(rates) == 0:
            print(f"[ERROR] Failed to fetch rates from MT5 for {self.symbol}.")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "tick_volume": "Volume"
        }, inplace=True)
        return ict_features.add_base_ta(df)

    def evaluate_signals(self, df: pd.DataFrame) -> dict:
        """Triple-layer signal gate using ICT setups and ML prediction confluences."""
        if df.empty or len(df) < 50:
            return {"action": "HOLD", "score": 0, "reason": "Insufficient candles"}

        row = df.iloc[-1]
        
        # 1. Compute ICT Setup Indicators
        above_200 = bool(row.get("Above_200SMA", 0))
        structure_bull = bool(row.get("Structure_Bullish", 0))
        
        # Directional bias
        bullish_bias = above_200 and structure_bull
        bearish_bias = (not above_200) and (not structure_bull)
        
        # ICT scores
        ob_count = float(row.get("Bull_OB_Count", 0)) if bullish_bias else float(row.get("Bear_OB_Count", 0))
        fvg_count = float(row.get("Bull_FVG_Count", 0)) if bullish_bias else float(row.get("Bear_FVG_Count", 0))
        displacement = float(row.get("Displacement", 0))
        
        ict_score = int(ob_count * self.cfg["ob_pts"] + fvg_count * self.cfg["fvg_pts"] + displacement * self.cfg["displacement_pts"])
        
        # 2. Fetch ML signals from the top 5 models
        ml = ml_signal(self.symbol, "1d")
        ml_action = ml.get("action", "HOLD")
        
        # Calculate ML agreement points
        ml_score = 0
        if ml_action == "BUY" and bullish_bias:
            ml_score = self.cfg["ml_agreement_pts"]
        elif ml_action == "SELL" and bearish_bias:
            ml_score = self.cfg["ml_agreement_pts"]
        elif ml_action != "HOLD":
            ml_score = self.cfg["ml_conflict_pts"]
            
        total_score = ict_score + ml_score
        
        action = "HOLD"
        reason = "No confluences found."
        
        if bullish_bias and total_score >= self.cfg["total_score_threshold"]:
            action = "BUY"
            reason = f"ICT Bullish Bias (Score: {total_score}) | FVG: {fvg_count} | OB: {ob_count}"
        elif bearish_bias and total_score >= self.cfg["total_score_threshold"]:
            action = "SELL"
            reason = f"ICT Bearish Bias (Score: {total_score}) | FVG: {fvg_count} | OB: {ob_count}"
            
        atr = float(row.get("ATR_14", 0)) if "ATR_14" in row else float(row["Close"] * 0.01)
        
        return {
            "action": action,
            "score": total_score,
            "reason": reason,
            "atr": atr,
            "price": float(row["Close"])
        }

    def execute_order(self, action: str, price: float, atr: float):
        """Send trade execution to MT5 terminal or mock paper engine."""
        sl_dist = atr * self.cfg["sl_multiplier"]
        tp_dist = atr * self.cfg["tp_multiplier"]

        if action == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else:
            sl = price + sl_dist
            tp = price - tp_dist

        # Compute position lot size based on capital risk percentage
        risk_capital = self.balance * (self.risk_pct / 100.0)
        lot_size = max(self.cfg["min_lot"], min(self.cfg["max_lot"], risk_capital / (sl_dist * 100000)))

        print(f"[TRADE] Attempting {action} order. Lot: {lot_size:.2f} | Price: {price:.5f} | SL: {sl:.5f} | TP: {tp:.5f}")

        if self.paper_mode:
            ticket = self.ticket_counter
            self.ticket_counter += 1
            self.positions[ticket] = {
                "action": action,
                "price": price,
                "sl": sl,
                "tp": tp,
                "lot": lot_size,
                "created_at": datetime.datetime.now()
            }
            print(f"[PAPER] Trade opened successfully. Ticket: {ticket}")
            return

        # MT5 Order Request
        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 1010,
            "comment": "BullLogic ICT + ML EA",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"[ERROR] MT5 Order Send failed: {result.comment} (Code: {result.retcode})")
        else:
            print(f"[MT5] Order filled successfully. Ticket: {result.order}")

    def update_positions(self, current_price: float):
        """Update open trade tickets, checking Stop Loss and Take Profit triggers."""
        if not self.paper_mode:
            # MT5 manages SL/TP server-side, just report account balances
            account_info = mt5.account_info()
            if account_info:
                self.balance = account_info.balance
                self.equity = account_info.equity
            return

        closed_tickets = []
        for ticket, pos in list(self.positions.items()):
            action = pos["action"]
            entry = pos["price"]
            sl = pos["sl"]
            tp = pos["tp"]
            lot = pos["lot"]

            pnl = 0
            if action == "BUY":
                if current_price <= sl:
                    pnl = (sl - entry) * lot * 100000
                    closed_tickets.append((ticket, "SL HIT", pnl))
                elif current_price >= tp:
                    pnl = (tp - entry) * lot * 100000
                    closed_tickets.append((ticket, "TP HIT", pnl))
            else:
                if current_price >= sl:
                    pnl = (entry - sl) * lot * 100000
                    closed_tickets.append((ticket, "SL HIT", pnl))
                elif current_price <= tp:
                    pnl = (entry - tp) * lot * 100000
                    closed_tickets.append((ticket, "TP HIT", pnl))

        for ticket, reason, pnl in closed_tickets:
            self.balance += pnl
            self.equity = self.balance
            del self.positions[ticket]
            print(f"[PAPER] Position ticket {ticket} closed. Reason: {reason} | PnL: ${pnl:.2f}")

    def check_circuit_breakers(self) -> bool:
        """Monitor daily drawdowns. Stops trading if 5% account threshold is violated."""
        drawdown = (self.daily_start_equity - self.equity) / self.daily_start_equity
        if drawdown >= self.cfg["daily_loss_limit"]:
            print(f"[HALT] Circuit breaker triggered! Daily loss limit hit ({drawdown * 100.0:.1f}%). Halting robot.")
            return True
        return False

    def run(self):
        self.running = True
        if not self.connect():
            return

        print(f"[START] Running loop on {self.symbol} ({self.timeframe}) every {self.cfg['interval_sec']} seconds.")
        
        while self.running:
            try:
                # 1. Fetch candles
                df = self.get_market_data()
                if df.empty:
                    time.sleep(5)
                    continue

                current_price = float(df["Close"].iloc[-1])
                self.update_positions(current_price)

                # 2. Check risk limiters
                if self.check_circuit_breakers():
                    break

                # 3. Check position limits
                active_count = len(self.positions) if self.paper_mode else len(mt5.positions_get(symbol=self.symbol) or [])
                if active_count >= self.cfg["max_positions"]:
                    time.sleep(self.cfg["interval_sec"])
                    continue

                # 4. Check signals
                sig = self.evaluate_signals(df)
                
                if sig["action"] in ("BUY", "SELL") and active_count < self.cfg["max_positions"]:
                    print(f"[SIGNAL] {sig['action']} detected. Reason: {sig['reason']}")
                    self.execute_order(sig["action"], sig["price"], sig["atr"])

            except KeyboardInterrupt:
                print("[INFO] Robot shutting down.")
                break
            except Exception as e:
                print(f"[ERROR] Loop error: {e}")

            time.sleep(self.cfg["interval_sec"])

        if not self.paper_mode:
            mt5.shutdown()
        print("[STOP] Robot halted.")


if __name__ == "__main__":
    robot = ICTMT5Robot(
        symbol=mt5_config.load()["symbol"],
        timeframe=mt5_config.load()["timeframe"],
        risk_pct=mt5_config.load()["risk_pct"]
    )
    robot.run()
