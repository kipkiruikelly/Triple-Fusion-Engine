"""
mt5_trading.py
MT5 algorithmic trading engine for ML-QTS.

Two modes:
  - LIVE: Connects to MetaTrader 5 via Wine/mt5linux rpyc bridge.
  - PAPER: Simulates trades against live yfinance data. No MT5 needed.

Triple-fusion signal (ICT primary, ML + tech as confirmation):
  1. ICT gate — 200 SMA + market structure bias required to enter
  2. ICT score — order blocks, FVGs, liquidity sweeps, PD zone
  3. ML models — LR + RF direction agreement adds 2 pts confirmation
  4. Tech indicators — RSI/MACD/EMA confluence adds score
  Entry fires when ICT bias present AND ICT score >= 3 AND total >= 5.
  Falls back to ML + tech fusion when ICT data unavailable.
  - ATR(14) dynamic SL/TP (SL=1.5×ATR, TP=3×ATR)
  - 1% account risk per trade (configurable)
  - Max 3 open positions, 5% daily loss circuit-breaker
"""

import asyncio
import time
import threading
import logging
from collections import deque
from datetime import datetime, date, timezone

import numpy as np
import pandas as pd

try:
    from predictor import ml_signal as _ml_signal, build_features as _build_features
    _ML_AVAILABLE = True
except Exception:
    _ml_signal = None
    _build_features = None
    _ML_AVAILABLE = False

# Try live MT5 bridge; fall back to paper mode
try:
    from mt5linux import MetaTrader5 as _MT5
    MT5_BACKEND = "mt5linux"
except ImportError:
    try:
        import MetaTrader5 as _MT5
        MT5_BACKEND = "native"
    except ImportError:
        _MT5 = None
        MT5_BACKEND = "paper"

# MetaApi timeframe mapping (MT5 name → MetaApi name)
_METAAPI_TF = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
               "H1": "1h", "H4": "4h", "D1": "1d"}


class MetaApiBackend:
    """
    Async MetaApi SDK wrapped for synchronous use inside Flask/threading.

    Runs a dedicated asyncio event loop in a background daemon thread.
    All public methods are synchronous and block until the coroutine completes.
    """
    TIMEOUT = 60  # seconds per API call

    def __init__(self):
        self._loop   = None
        self._thread = None
        self._api    = None
        self._conn   = None
        self._acct   = None

    # ── Internal loop management ──────────────────────────────────────────────

    def _start_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._start_loop, daemon=True,
                                         name="metaapi-loop")
        self._thread.start()

    def _run(self, coro):
        """Submit a coroutine to the MetaApi loop and block until done."""
        if not self._loop or not self._loop.is_running():
            raise RuntimeError("MetaApi event loop not running")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=self.TIMEOUT)

    # ── Connection ────────────────────────────────────────────────────────────

    async def _do_connect(self, token: str, account_id: str):
        from metaapi_cloud_sdk import MetaApi
        self._api  = MetaApi(token)
        self._acct = await self._api.metatrader_account_api.get_account(account_id)
        if self._acct.state not in ("DEPLOYING", "DEPLOYED"):
            await self._acct.deploy()
        await self._acct.wait_connected()
        self._conn = self._acct.get_rpc_connection()
        await self._conn.connect()
        await self._conn.wait_synchronized()
        return await self._conn.get_account_information()

    def connect(self, token: str, account_id: str):
        return self._run(self._do_connect(token, account_id))

    async def _do_disconnect(self):
        if self._conn:
            await self._conn.close()
        if self._api:
            self._api.close()
        self._conn = self._acct = self._api = None

    def disconnect(self):
        try:
            self._run(self._do_disconnect())
        except Exception:
            pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ── Market data ───────────────────────────────────────────────────────────

    async def _do_get_candles(self, symbol: str, tf: str, count: int):
        return await self._conn.get_candles(symbol, tf,
                                             datetime.now(timezone.utc), count)

    def get_candles(self, symbol: str, tf: str, count: int = 120):
        return self._run(self._do_get_candles(symbol, tf, count))

    async def _do_get_price(self, symbol: str):
        return await self._conn.get_symbol_price(symbol)

    def get_price(self, symbol: str):
        return self._run(self._do_get_price(symbol))

    async def _do_get_account_info(self):
        return await self._conn.get_account_information()

    def get_account_info(self):
        return self._run(self._do_get_account_info())

    # ── Trading ───────────────────────────────────────────────────────────────

    async def _do_place(self, symbol, action, lot, sl, tp):
        opts = {"comment": "ML-QTS algo", "clientId": "mp-algo"}
        if action == "BUY":
            return await self._conn.create_market_buy_order(symbol, lot, sl, tp, opts)
        else:
            return await self._conn.create_market_sell_order(symbol, lot, sl, tp, opts)

    def place_order(self, symbol, action, lot, sl, tp):
        return self._run(self._do_place(symbol, action, lot, sl, tp))

    async def _do_get_positions(self, symbol):
        positions = await self._conn.get_positions()
        return [p for p in positions if p["symbol"] == symbol]

    def get_positions(self, symbol):
        return self._run(self._do_get_positions(symbol))

    async def _do_close_all(self, symbol):
        positions = await self._conn.get_positions()
        closed = 0
        for p in positions:
            if p["symbol"] == symbol:
                await self._conn.close_position(p["id"])
                closed += 1
        return closed

    def close_all(self, symbol):
        return self._run(self._do_close_all(symbol))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("mt5_trading")

MAX_LOG_ENTRIES  = 200
MAX_POSITIONS    = 3
DAILY_LOSS_LIMIT = 0.05
PAPER_BALANCE    = 10_000.0   # virtual account balance


# ── Pure-Python indicator helpers ────────────────────────────────────────────

def _calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def _calc_macd(closes: np.ndarray, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    s = pd.Series(closes)
    ema_fast    = s.ewm(span=fast,   adjust=False).mean()
    ema_slow    = s.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(hist.iloc[-1])


def _calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return float(closes[-1]) * 0.001
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
    )
    return float(tr[-period:].mean())


def _signal_from_arrays(closes, highs, lows):
    """Core signal logic shared between live and paper modes."""
    rsi             = _calc_rsi(closes)
    prev_rsi        = _calc_rsi(closes[:-1])
    macd, sig, hist = _calc_macd(closes)
    _, _, prev_hist = _calc_macd(closes[:-1])
    atr             = _calc_atr(highs, lows, closes)
    price           = float(closes[-1])

    buy_score = sell_score = 0

    if prev_rsi < 30 and rsi >= 30:
        buy_score += 1
    elif rsi < 35:
        buy_score += 1

    if prev_rsi > 70 and rsi <= 70:
        sell_score += 1
    elif rsi > 65:
        sell_score += 1

    if prev_hist < 0 and hist >= 0:
        buy_score += 2
    elif hist > 0 and hist > prev_hist:
        buy_score += 1

    if prev_hist > 0 and hist <= 0:
        sell_score += 2
    elif hist < 0 and hist < prev_hist:
        sell_score += 1

    ema20 = float(pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1])
    if price > ema20:
        buy_score += 1
    else:
        sell_score += 1

    action = "HOLD"
    score  = 0
    if buy_score >= 3 and buy_score > sell_score:
        action, score = "BUY", buy_score
    elif sell_score >= 3 and sell_score > buy_score:
        action, score = "SELL", sell_score

    return {
        "action" : action,
        "score"  : score,
        "reason" : f"RSI={rsi:.1f} MACD_hist={hist:.5f} ATR={atr:.5f}",
        "rsi"    : round(rsi, 2),
        "macd"   : round(hist, 6),
        "atr"    : round(atr, 6),
        "price"  : round(price, 5),
    }


# ── Paper trading engine ─────────────────────────────────────────────────────

class PaperAccount:
    """Virtual account for paper trading."""

    def __init__(self, balance: float = PAPER_BALANCE):
        self.balance      = balance
        self.equity       = balance
        self.positions    = []   # list of dicts
        self.ticket_seq   = 1000
        self.day          = date.today()

    def open_position(self, symbol, action, lot, price, sl, tp):
        ticket = self.ticket_seq
        self.ticket_seq += 1
        self.positions.append({
            "ticket": ticket,
            "symbol": symbol,
            "action": action,
            "lot"   : lot,
            "price" : price,
            "sl"    : sl,
            "tp"    : tp,
            "pnl"   : 0.0,
        })
        return ticket

    def update_equity(self, current_prices: dict):
        """Recalculate equity based on current prices; auto-close if SL/TP hit."""
        closed = []
        pnl_total = 0.0
        for pos in self.positions:
            sym   = pos["symbol"]
            cprice = current_prices.get(sym, pos["price"])
            if pos["action"] == "BUY":
                pnl = (cprice - pos["price"]) * pos["lot"] * 1000
                if cprice <= pos["sl"] or cprice >= pos["tp"]:
                    closed.append((pos, pnl))
                    continue
            else:
                pnl = (pos["price"] - cprice) * pos["lot"] * 1000
                if cprice >= pos["sl"] or cprice <= pos["tp"]:
                    closed.append((pos, pnl))
                    continue
            pos["pnl"] = round(pnl, 2)
            pnl_total += pnl

        for pos, pnl in closed:
            self.positions.remove(pos)
            self.balance += pnl

        self.equity = self.balance + pnl_total
        return [p["ticket"] for p, _ in closed]

    def close_all(self, symbol):
        remaining = [p for p in self.positions if p["symbol"] != symbol]
        closed    = len(self.positions) - len(remaining)
        self.positions = remaining
        return closed

    def info(self):
        return {
            "login"      : 0,
            "name"       : "Paper Account",
            "server"     : "Paper Trading",
            "currency"   : "USD",
            "balance"    : round(self.balance, 2),
            "equity"     : round(self.equity, 2),
            "margin"     : 0.0,
            "free_margin": round(self.equity, 2),
            "leverage"   : 100,
        }


# ── Main trader class ────────────────────────────────────────────────────────

class MT5Trader:

    def __init__(self):
        self.mt5           = _MT5
        self.backend       = MT5_BACKEND
        self.connected     = False
        self.trading       = False
        self.use_ml        = True
        self._thread       = None
        self._lock         = threading.Lock()
        self.trade_log     = deque(maxlen=MAX_LOG_ENTRIES)
        self.account       = {}
        self.status_msg    = "Disconnected"
        self.equity_open   = None
        self.last_signal   = {}
        self.last_ml       = {}
        self._mt5_instance = None
        self._paper        = None       # PaperAccount when in paper mode
        self._mapi         = None       # MetaApiBackend when in metaapi mode

    @property
    def is_paper(self):
        return self._paper is not None

    @property
    def is_metaapi(self):
        return self._mapi is not None

    # ── Connection ───────────────────────────────────────────────────────────

    def connect(self, account_num: int, password: str, server: str,
                host: str = "localhost", port: int = 18812,
                metaapi_token: str = "", metaapi_account_id: str = "") -> dict:

        # ── MetaApi mode ─────────────────────────────────────────────────────
        if metaapi_token and metaapi_account_id:
            try:
                mapi = MetaApiBackend()
                mapi.start()
                self._log("INFO", "Connecting to MetaApi — deploying account, please wait…")
                info = mapi.connect(metaapi_token, metaapi_account_id)
                self._mapi       = mapi
                self._paper      = None
                self._mt5_instance = None
                self.connected   = True
                self.account     = {
                    "login"      : info.get("login", 0),
                    "name"       : info.get("name", "MetaApi Account"),
                    "server"     : info.get("server", ""),
                    "currency"   : info.get("currency", "USD"),
                    "balance"    : round(info.get("balance", 0), 2),
                    "equity"     : round(info.get("equity", 0), 2),
                    "margin"     : round(info.get("margin", 0), 2),
                    "free_margin": round(info.get("freeMargin", 0), 2),
                    "leverage"   : info.get("leverage", 100),
                }
                self.equity_open = self.account["equity"]
                self.status_msg  = f"Connected (MetaApi) — {self.account['name']} @ {self.account['server']}"
                self._log("INFO", f"MetaApi connected: {self.account['name']} balance {self.account['currency']} {self.account['balance']:,.2f}")
                return {"ok": True, "account": self.account, "mode": "metaapi"}
            except Exception as e:
                return {"ok": False, "error": f"MetaApi connection failed: {e}"}

        # ── Paper mode ───────────────────────────────────────────────────────
        if account_num == 0 or self.backend == "paper":
            self._paper      = PaperAccount()
            self.connected   = True
            self.account     = self._paper.info()
            self.equity_open = self._paper.balance
            self.status_msg  = "Connected (Paper Trading)"
            self._log("INFO", "Paper trading mode activated — $10,000 virtual balance")
            return {"ok": True, "account": self.account, "mode": "paper"}

        # Live MT5 bridge
        if self.mt5 is None:
            return {"ok": False, "error": (
                "MT5 bridge unavailable. Either use paper mode (account=0) or "
                "install wine-devel >= 10.12 to fix the ucrtbase.dll.crealf issue."
            )}

        try:
            mt5 = self.mt5(host=host, port=port) if self.backend == "mt5linux" else self.mt5

            if not mt5.initialize():
                return {"ok": False, "error": f"MT5 initialize() failed: {mt5.last_error()}"}

            if not mt5.login(account_num, password=password, server=server):
                mt5.shutdown()
                return {"ok": False, "error": f"Login failed: {mt5.last_error()}"}

            info = mt5.account_info()
            if info is None:
                mt5.shutdown()
                return {"ok": False, "error": "Could not fetch account info"}

            self._mt5_instance = mt5
            self._paper        = None
            self.connected     = True
            self.account       = {
                "login"      : info.login,
                "name"       : info.name,
                "server"     : info.server,
                "currency"   : info.currency,
                "balance"    : round(info.balance, 2),
                "equity"     : round(info.equity, 2),
                "margin"     : round(info.margin, 2),
                "free_margin": round(info.margin_free, 2),
                "leverage"   : info.leverage,
            }
            self.equity_open = info.equity
            self.status_msg  = f"Connected (Live) — {info.name} @ {info.server}"
            self._log("INFO", f"Connected to {info.server} as {info.name}")
            return {"ok": True, "account": self.account, "mode": "live"}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def disconnect(self):
        self.stop_trading()
        if self.connected:
            if self._mt5_instance:
                try:
                    self._mt5_instance.shutdown()
                except Exception:
                    pass
            if self._mapi:
                try:
                    self._mapi.disconnect()
                except Exception:
                    pass
        self.connected     = False
        self._paper        = None
        self._mt5_instance = None
        self._mapi         = None
        self.status_msg    = "Disconnected"
        self._log("INFO", "Disconnected")

    def refresh_account(self):
        if not self.connected:
            return
        if self.is_paper:
            self.account = self._paper.info()
            return
        if self.is_metaapi:
            try:
                info = self._mapi.get_account_info()
                self.account.update({
                    "balance"     : round(info.get("balance", 0), 2),
                    "equity"      : round(info.get("equity", 0), 2),
                    "margin"      : round(info.get("margin", 0), 2),
                    "free_margin" : round(info.get("freeMargin", 0), 2),
                })
            except Exception:
                pass
            return
        try:
            info = self._mt5_instance.account_info()
            if info:
                self.account.update({
                    "balance"     : round(info.balance, 2),
                    "equity"      : round(info.equity, 2),
                    "margin"      : round(info.margin, 2),
                    "free_margin" : round(info.margin_free, 2),
                })
        except Exception:
            pass

    # ── ICT feature helpers ──────────────────────────────────────────────────

    def _get_daily_bars_long(self, symbol: str, n: int = 300) -> "pd.DataFrame | None":
        """Fetch ~15 months of daily OHLCV for ICT feature computation (needs 200+ bars)."""
        import yfinance as yf
        try:
            yf_sym = symbol.replace(".", "-")
            df = yf.download(yf_sym, period="18mo", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.tail(n) if not df.empty else None
        except Exception as e:
            log.warning(f"Daily bars fetch error: {e}")
            return None

    def _ict_row(self, symbol: str) -> "dict | None":
        """
        Compute ICT features on daily bars and return a signal dict for the last bar.

        Returns bias flags, per-direction scores, and ATR.
        Returns None when data is unavailable or feature build fails.
        """
        if _build_features is None:
            return None
        df = self._get_daily_bars_long(symbol)
        if df is None or len(df) < 30:
            return None
        try:
            feat_df = _build_features(df)
            if feat_df.empty:
                return None
            row   = feat_df.iloc[-1]
            close = float(feat_df["Close"].iloc[-1])
            open_ = float(feat_df["Open"].iloc[-1])

            def _g(col, default=0.0):
                return float(row[col]) if col in row.index else default

            above_200 = _g("Above_200SMA")
            struct_b  = _g("Structure_Bullish")
            pd_pos    = _g("PD_Position", 0.5)
            bull_ob   = _g("Bull_OB_Count")
            bear_ob   = _g("Bear_OB_Count")
            bull_fvg  = _g("Bull_FVG_Count")
            bear_fvg  = _g("Bear_FVG_Count")
            swept_h   = _g("Swept_High")
            swept_l   = _g("Swept_Low")
            disp      = _g("Displacement")
            atr       = _g("ATR_14", close * 0.01)
            if atr <= 0:
                atr = close * 0.01

            bullish_bias = (above_200 >= 0.5) and (struct_b >= 0.5)
            bearish_bias = (above_200 < 0.5)  and (struct_b < 0.5)

            buy = sell = 0

            # PD zone (where to trade)
            if pd_pos < 0.40:    buy  += 3
            elif pd_pos < 0.50:  buy  += 1
            if pd_pos > 0.60:    sell += 3
            elif pd_pos > 0.50:  sell += 1

            # Order blocks
            if bull_ob > 0:  buy  += 2
            if bear_ob > 0:  sell += 2

            # Fair Value Gaps
            if bull_fvg > 0: buy  += 1
            if bear_fvg > 0: sell += 1

            # Liquidity sweeps
            if swept_l > 0:  buy  += 2
            if swept_h > 0:  sell += 2

            # Displacement
            if disp > 0 and close > open_: buy  += 1
            if disp > 0 and close < open_: sell += 1

            return {
                "bullish_bias": bullish_bias,
                "bearish_bias": bearish_bias,
                "buy_score"   : buy,
                "sell_score"  : sell,
                "atr"         : atr,
                "pd_pos"      : round(pd_pos, 3),
                "above_200"   : above_200,
            }
        except Exception as e:
            log.warning(f"ICT feature computation error: {e}")
            return None

    # ── Triple-fusion signal (ICT gate + ML + Technical) ─────────────────────

    def generate_signal_ml(self, symbol: str, timeframe=None) -> dict:
        """
        Triple-layer signal fusion — ICT has highest priority.

        Layer 1 (ICT gate): Above_200SMA + Structure_Bullish sets directional bias.
                            ICT score from OBs, FVGs, liquidity sweeps, PD zone.
                            Requires bias present AND ICT score >= 3.
        Layer 2 (ML):       LR + RF agreement adds +2 pts; disagreement subtracts -1.
        Layer 3 (Tech):     RSI/MACD/EMA confluence adds its score; conflict subtracts -1.
        Entry fires when total score (ICT + ML + Tech) >= 5.

        Falls back to original ML + tech fusion if ICT data is unavailable.
        """
        # 1. ICT features (daily bars — primary gate)
        ict = self._ict_row(symbol)

        # 2. ML signal (LR + RF on daily 18-month data from predictor)
        ml = (_ml_signal(symbol) if (_ML_AVAILABLE and _ml_signal)
              else {"action": "HOLD", "confidence": 0})
        self.last_ml = ml

        # 3. Technical signal (RSI/MACD/EMA)
        tec = self.generate_signal(symbol, timeframe)

        ml_action  = ml.get("action",  "HOLD")
        tec_action = tec.get("action", "HOLD")
        atr        = ml.get("atr", tec.get("atr", 0))

        action = "HOLD"
        score  = 0

        if ict is not None:
            # Use ICT's ATR (daily ATR, better for daily signal sizing)
            if ict["atr"] > 0:
                atr = ict["atr"]

            for side in ("BUY", "SELL"):
                bias_ok = ict["bullish_bias"] if side == "BUY" else ict["bearish_bias"]
                ict_raw = ict["buy_score"]    if side == "BUY" else ict["sell_score"]

                if not bias_ok or ict_raw < 3:
                    continue

                ml_pts  = 2 if ml_action == side else (0 if ml_action == "HOLD" else -1)
                tec_pts = tec.get("score", 0) if tec_action == side else (
                          0 if tec_action == "HOLD" else -1)

                total = ict_raw + ml_pts + tec_pts
                if total >= 5:
                    action = side
                    score  = total
                    break

            bias_str = ("bull" if ict["bullish_bias"] else
                        "bear" if ict["bearish_bias"] else "neutral")
            reason = (
                f"ICT_bias={bias_str} PD={ict['pd_pos']:.2f} "
                f"buy_pts={ict['buy_score']} sell_pts={ict['sell_score']} | "
                f"ML={ml_action} conf={ml.get('confidence',0):.0f}% | "
                f"Tech={tec_action} | "
                f"LR={ml.get('lr_pred',0):.2f} RF={ml.get('rf_pred',0):.2f}"
            )
            if action != "HOLD":
                reason = f"{action} total={score} | " + reason

        else:
            # ICT unavailable — fall back to ML + tech fusion
            if ml_action == "HOLD":
                reason = f"ML=HOLD | Tech={tec_action}"
            elif ml_action == tec_action:
                action = ml_action
                score  = tec.get("score", 0) + 2
                reason = (f"ML={ml_action} conf={ml.get('confidence',0):.0f}% | "
                          f"Tech={tec_action} | fallback (no ICT data)")
            elif tec_action == "HOLD":
                action = ml_action
                score  = 2
                reason = f"ML={ml_action} (tech neutral) | fallback (no ICT data)"
            else:
                reason = f"CONFLICT ML={ml_action} vs Tech={tec_action} | fallback"

        signal = {
            "action"    : action,
            "score"     : score,
            "reason"    : reason,
            "rsi"       : ml.get("rsi",  tec.get("rsi", 50)),
            "macd"      : ml.get("macd_hist", tec.get("macd", 0)),
            "atr"       : atr,
            "price"     : ml.get("current_price", tec.get("price", 0)),
            "lr_pred"   : ml.get("lr_pred", 0),
            "rf_pred"   : ml.get("rf_pred", 0),
            "confidence": ml.get("confidence", 0),
        }
        self.last_signal = signal
        return signal

    # ── Signal generation ────────────────────────────────────────────────────

    def _get_bars_paper(self, symbol: str, n: int = 120) -> pd.DataFrame | None:
        """Fetch OHLCV bars from yfinance for paper mode."""
        try:
            import yfinance as yf
            yf_sym = symbol.replace(".", "-")
            df = yf.download(yf_sym, period="60d", interval="5m",
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df.empty or len(df) < 60:
                df = yf.download(yf_sym, period="1y", auto_adjust=True, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
            return df.tail(n) if not df.empty else None
        except Exception as e:
            log.warning(f"yfinance error: {e}")
            return None

    def _get_bars_metaapi(self, symbol: str, timeframe: str, n: int = 120):
        """Fetch OHLCV bars from MetaApi and return as a DataFrame."""
        try:
            tf   = _METAAPI_TF.get(timeframe, "5m")
            bars = self._mapi.get_candles(symbol, tf, n)
            if not bars:
                return None
            df = pd.DataFrame([{
                "Close" : c["close"],
                "High"  : c["high"],
                "Low"   : c["low"],
                "Open"  : c["open"],
                "Volume": c.get("tickVolume", 1),
            } for c in bars])
            return df
        except Exception as e:
            log.warning(f"MetaApi get_candles error: {e}")
            return None

    def generate_signal(self, symbol: str, timeframe=None) -> dict:
        if self.is_paper:
            df = self._get_bars_paper(symbol)
            if df is None or len(df) < 60:
                return {"action": "HOLD", "reason": "Insufficient data", "score": 0,
                        "rsi": 50, "macd": 0, "atr": 0, "price": 0}
            closes = df["Close"].values.astype(float)
            highs  = df["High"].values.astype(float)
            lows   = df["Low"].values.astype(float)
        elif self.is_metaapi:
            df = self._get_bars_metaapi(symbol, timeframe or "M5")
            if df is None or len(df) < 60:
                return {"action": "HOLD", "reason": "Insufficient data", "score": 0,
                        "rsi": 50, "macd": 0, "atr": 0, "price": 0}
            closes = df["Close"].values.astype(float)
            highs  = df["High"].values.astype(float)
            lows   = df["Low"].values.astype(float)
        else:
            df = self.get_bars_live(symbol, timeframe, n=120)
            if df is None or len(df) < 60:
                return {"action": "HOLD", "reason": "Insufficient data", "score": 0,
                        "rsi": 50, "macd": 0, "atr": 0, "price": 0}
            closes = df["close"].values.astype(float)
            highs  = df["high"].values.astype(float)
            lows   = df["low"].values.astype(float)

        signal = _signal_from_arrays(closes, highs, lows)
        self.last_signal = signal
        return signal

    def get_bars_live(self, symbol: str, timeframe, n: int = 100) -> pd.DataFrame | None:
        try:
            rates = self._mt5_instance.copy_rates_from_pos(symbol, timeframe, 0, n)
            if rates is None or len(rates) == 0:
                return None
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            return df
        except Exception as e:
            log.warning(f"get_bars_live error: {e}")
            return None

    # ── Order execution ──────────────────────────────────────────────────────

    def _count_positions(self, symbol: str) -> int:
        if self.is_paper:
            return sum(1 for p in self._paper.positions if p["symbol"] == symbol)
        if self.is_metaapi:
            try:
                return len(self._mapi.get_positions(symbol))
            except Exception:
                return 0
        try:
            positions = self._mt5_instance.positions_get(symbol=symbol)
            return len(positions) if positions else 0
        except Exception:
            return 0

    def _calc_lot(self, risk_pct: float, sl_points: float, price: float) -> float:
        balance  = self.account.get("balance", PAPER_BALANCE)
        risk_amt = balance * (risk_pct / 100.0)
        if sl_points <= 0 or price <= 0:
            return 0.01
        sl_pct = sl_points / price
        if sl_pct <= 0:
            return 0.01
        lot = risk_amt / (sl_pct * price * 1000)
        return round(max(0.01, min(lot, 10.0)), 2)

    def place_order(self, symbol: str, action: str, risk_pct: float, atr: float) -> dict:
        sl_dist = atr * 1.5
        tp_dist = atr * 3.0

        if self.is_paper:
            df = self._get_bars_paper(symbol, n=5)
            price = float(df["Close"].iloc[-1]) if df is not None else 0
            if price <= 0:
                return {"ok": False, "error": "Cannot get current price"}
            if action == "BUY":
                sl = round(price - sl_dist, 5)
                tp = round(price + tp_dist, 5)
            else:
                sl = round(price + sl_dist, 5)
                tp = round(price - tp_dist, 5)
            lot    = self._calc_lot(risk_pct, sl_dist, price)
            ticket = self._paper.open_position(symbol, action, lot, price, sl, tp)
            trade  = {
                "time"  : datetime.now().strftime("%H:%M:%S"),
                "action": action,
                "symbol": symbol,
                "lot"   : lot,
                "price" : price,
                "sl"    : sl,
                "tp"    : tp,
                "ticket": ticket,
            }
            self._log("PAPER TRADE", f"{action} {lot} {symbol} @ {price:.5f}  SL={sl:.5f}  TP={tp:.5f}")
            return {"ok": True, "trade": trade}

        # MetaApi live order
        if self.is_metaapi:
            try:
                tick  = self._mapi.get_price(symbol)
                price = tick["ask"] if action == "BUY" else tick["bid"]
                if action == "BUY":
                    sl = round(price - sl_dist, 5)
                    tp = round(price + tp_dist, 5)
                else:
                    sl = round(price + sl_dist, 5)
                    tp = round(price - tp_dist, 5)
                lot    = self._calc_lot(risk_pct, sl_dist, price)
                result = self._mapi.place_order(symbol, action, lot, sl, tp)
                ticket = result.get("orderId", "?")
                trade  = {
                    "time"  : datetime.now().strftime("%H:%M:%S"),
                    "action": action,
                    "symbol": symbol,
                    "lot"   : lot,
                    "price" : price,
                    "sl"    : sl,
                    "tp"    : tp,
                    "ticket": ticket,
                }
                self._log("TRADE", f"{action} {lot} {symbol} @ {price:.5f}  SL={sl:.5f}  TP={tp:.5f}  #{ticket}")
                return {"ok": True, "trade": trade}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # Direct MT5 live order
        mt5  = self._mt5_instance
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"ok": False, "error": "No tick data"}

        if action == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price      = tick.ask
            sl         = round(price - sl_dist, 5)
            tp         = round(price + tp_dist, 5)
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price      = tick.bid
            sl         = round(price + sl_dist, 5)
            tp         = round(price - tp_dist, 5)

        lot = self._calc_lot(risk_pct, sl_dist, price)
        request = {
            "action"       : mt5.TRADE_ACTION_DEAL,
            "symbol"       : symbol,
            "volume"       : lot,
            "type"         : order_type,
            "price"        : price,
            "sl"           : sl,
            "tp"           : tp,
            "deviation"    : 20,
            "magic"        : 20250622,
            "comment"      : "ML-QTS algo",
            "type_time"    : mt5.ORDER_TIME_GTC,
            "type_filling" : mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else "None"
            return {"ok": False, "error": f"Order rejected: {err}"}

        trade = {
            "time"  : datetime.now().strftime("%H:%M:%S"),
            "action": action,
            "symbol": symbol,
            "lot"   : lot,
            "price" : price,
            "sl"    : sl,
            "tp"    : tp,
            "ticket": result.order,
        }
        self._log("TRADE", f"{action} {lot} {symbol} @ {price:.5f}  SL={sl:.5f}  TP={tp:.5f}")
        return {"ok": True, "trade": trade}

    def close_all(self, symbol: str) -> int:
        if self.is_paper:
            return self._paper.close_all(symbol)
        if self.is_metaapi:
            try:
                return self._mapi.close_all(symbol)
            except Exception as e:
                self._log("ERROR", f"close_all: {e}")
                return 0
        mt5       = self._mt5_instance
        positions = mt5.positions_get(symbol=symbol) or []
        closed    = 0
        for pos in positions:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                continue
            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price      = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
            req = {
                "action"       : mt5.TRADE_ACTION_DEAL,
                "symbol"       : symbol,
                "volume"       : pos.volume,
                "type"         : close_type,
                "position"     : pos.ticket,
                "price"        : price,
                "deviation"    : 20,
                "magic"        : 20250622,
                "comment"      : "ML-QTS close",
                "type_time"    : mt5.ORDER_TIME_GTC,
                "type_filling" : mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1
                self._log("CLOSE", f"Closed ticket {pos.ticket}")
        return closed

    # ── Trading loop ─────────────────────────────────────────────────────────

    def _trading_loop(self, symbol: str, timeframe, risk_pct: float, interval: int):
        tf_map = {}
        if not self.is_paper and self._mt5_instance:
            mt5 = self._mt5_instance
            tf_map = {
                "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
            }
        tf = tf_map.get(timeframe, None)

        mode = "Paper" if self.is_paper else "Live"
        self._log("INFO", f"{mode} trading started — {symbol} {timeframe} risk={risk_pct}% interval={interval}s")

        while self.trading:
            try:
                self.refresh_account()

                # Daily loss guard
                eq = self.account.get("equity", 0)
                if self.equity_open and eq and self.equity_open > 0:
                    drawdown = (self.equity_open - eq) / self.equity_open
                    if drawdown >= DAILY_LOSS_LIMIT:
                        self._log("WARN", f"Daily loss limit hit ({drawdown*100:.1f}%). Trading halted.")
                        self.trading    = False
                        self.status_msg = f"Halted — {DAILY_LOSS_LIMIT*100:.0f}% daily loss limit"
                        break

                # Max positions guard
                if self._count_positions(symbol) >= MAX_POSITIONS:
                    self._log("INFO", f"Max positions ({MAX_POSITIONS}) held, waiting")
                    time.sleep(interval)
                    continue

                signal = (self.generate_signal_ml(symbol, tf)
                          if self.use_ml and _ML_AVAILABLE
                          else self.generate_signal(symbol, tf))
                self._log("SIGNAL", f"{signal['action']} score={signal['score']} {signal['reason']}")

                if signal["action"] in ("BUY", "SELL"):
                    result = self.place_order(symbol, signal["action"], risk_pct, signal["atr"])
                    if not result["ok"]:
                        self._log("ERROR", result["error"])

                # Paper: update equity based on current prices
                if self.is_paper and self._paper.positions:
                    df = self._get_bars_paper(symbol, n=3)
                    if df is not None:
                        cur = float(df["Close"].iloc[-1])
                        closed_tickets = self._paper.update_equity({symbol: cur})
                        for t in closed_tickets:
                            self._log("PAPER CLOSE", f"Ticket {t} auto-closed (SL/TP hit)")

            except Exception as e:
                self._log("ERROR", f"Loop error: {e}")

            time.sleep(interval)

        self._log("INFO", "Trading loop stopped")

    def start_trading(self, symbol: str, timeframe: str = "M5",
                      risk_pct: float = 1.0, interval: int = 60,
                      use_ml: bool = True) -> dict:
        if not self.connected:
            return {"ok": False, "error": "Not connected. Use account=0 for paper mode."}
        if self.trading:
            return {"ok": False, "error": "Already trading"}
        self.use_ml     = use_ml and _ML_AVAILABLE
        self.trading    = True
        mode = "Paper" if self.is_paper else ("MetaApi" if self.is_metaapi else "Live")
        ml_tag = "+ML" if self.use_ml else ""
        self.status_msg = f"{mode} Trading{ml_tag} — {symbol} {timeframe}"
        self._thread = threading.Thread(
            target=self._trading_loop,
            args=(symbol, timeframe, risk_pct, interval),
            daemon=True,
        )
        self._thread.start()
        return {"ok": True, "mode": mode.lower(), "ml": self.use_ml}

    def stop_trading(self) -> dict:
        if not self.trading:
            return {"ok": False, "error": "Not currently trading"}
        self.trading = False
        mode = "Paper" if self.is_paper else "Live"
        self.status_msg = f"{mode} — trading stopped"
        if self._thread:
            self._thread.join(timeout=5)
        return {"ok": True}

    # ── Status & log ─────────────────────────────────────────────────────────

    def _log(self, level: str, msg: str):
        entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
        with self._lock:
            self.trade_log.appendleft(entry)
        log.info(f"[{level}] {msg}")

    def get_status(self) -> dict:
        self.refresh_account()
        positions = []
        if self.is_paper:
            positions = self._paper.positions
        mode = "paper" if self.is_paper else ("metaapi" if self.is_metaapi else "live")
        return {
            "connected"   : self.connected,
            "trading"     : self.trading,
            "backend"     : self.backend,
            "mode"        : mode,
            "use_ml"      : self.use_ml,
            "ml_available": _ML_AVAILABLE,
            "status_msg"  : self.status_msg,
            "account"     : self.account,
            "last_signal" : self.last_signal,
            "last_ml"     : self.last_ml,
            "positions"   : positions,
            "log"         : list(self.trade_log)[:50],
        }


# Global singleton
trader = MT5Trader()
