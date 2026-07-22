"""
ict_features.py
Shared ICT (Inner Circle Trader) + base technical-analysis feature engineering.

Previously this logic was duplicated near-identically between predictor.py
(live inference) and train_all_tickers.py (training) - a classic drift risk,
since a model's saved feature_cols only match reality if both sides compute
every column exactly the same way. Extracted here so there is exactly one
implementation; both callers import from this module.

Column groups:
  add_base_ta(df)        - TA + ICT features that make sense on any timeframe
  add_intraday_ict(df)   - session/kill-zone features that only make sense
                           on sub-daily bars (need a time-of-day)
  add_smt_divergence(df, ref_df) - structure divergence vs a correlated
                           reference instrument (SPY/sector ETF already
                           fetched as aux data elsewhere)

All functions are pure: take a DataFrame, return it with new columns added.
"""

import numpy as np
import pandas as pd
import ta


# ── Higher Timeframe (HTF) Confluence Filter ────────────────────────────────

def add_htf_bias(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates Daily/H4 trend filters from intraday data via resampling."""
    if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 50:
        df["HTF_Bullish_Bias"] = 1
        return df

    try:
        # Check median time difference
        time_diffs = pd.Series(df.index).diff().median()
        is_intraday = time_diffs < pd.Timedelta(days=1)

        if is_intraday:
            # Resample to Daily
            resampled = df[["Open", "High", "Low", "Close"]].resample("D").agg({
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last"
            }).ffill()

            # 50-period SMA on resampled Daily
            daily_sma = resampled["Close"].rolling(min(50, len(resampled)), min_periods=1).mean()
            daily_bullish = (resampled["Close"] > daily_sma).astype(int)

            # Reindex back to original timeframe with forward-fill
            df["HTF_Bullish_Bias"] = daily_bullish.reindex(df.index, method="ffill").fillna(1)
        else:
            daily_sma = df["Close"].rolling(min(50, len(df)), min_periods=1).mean()
            df["HTF_Bullish_Bias"] = (df["Close"] > daily_sma).astype(int)
    except Exception as e:
        df["HTF_Bullish_Bias"] = 1
        print(f"[ICT FEATURE WARNING] HTF Resampling failed: {e}")

    return df


# ── Base TA + ICT (any timeframe) ───────────────────────────────────────────

def add_base_ta(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    open_ = df["Open"]

    df["SMA_7"]  = ta.trend.sma_indicator(close, window=7)
    df["SMA_21"] = ta.trend.sma_indicator(close, window=21)
    df["EMA_12"] = ta.trend.ema_indicator(close, window=12)
    df["EMA_26"] = ta.trend.ema_indicator(close, window=26)
    df["RSI_14"] = ta.momentum.rsi(close, window=14)

    macd_obj = ta.trend.MACD(close, window_fast=12, window_slow=26, window_sign=9)
    df["MACD"]        = macd_obj.macd()
    df["MACD_Signal"] = macd_obj.macd_signal()
    df["MACD_Hist"]   = macd_obj.macd_diff()

    bb_obj = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    df["BB_Upper"] = bb_obj.bollinger_hband()
    df["BB_Lower"] = bb_obj.bollinger_lband()
    df["BB_Mid"]   = bb_obj.bollinger_mavg()
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"]

    df["Volume_SMA_10"] = ta.trend.sma_indicator(df["Volume"], window=10)
    df["Daily_Return"]  = close.pct_change() * 100

    for lag in range(1, 6):
        df[f"Close_lag_{lag}"]  = close.shift(lag)
    for lag in range(1, 4):
        df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    atr14 = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    atr14 = atr14.fillna(close * 0.01)
    df["ATR_14"] = atr14   # kept for SL/TP sizing at inference; not itself a model feature

    # ── ICT: base structure ────────────────────────────────────────────────
    sma200 = close.rolling(200, min_periods=1).mean()
    df["Above_200SMA"] = (close > sma200).astype(int)
    df["Dist_200SMA"]  = ((close - sma200) / sma200 * 100).fillna(0)

    rng  = (high - low).replace(0, np.nan)
    body = (close - open_).abs()
    df["Body_Ratio"]   = (body / rng).fillna(0).clip(0, 1)
    df["Displacement"] = ((rng.fillna(0) > atr14 * 1.5) & (df["Body_Ratio"] > 0.6)).astype(int)

    sh20 = high.rolling(20).max()
    sl20 = low.rolling(20).min()
    df["Dist_to_SH"]        = ((sh20 - close) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SL"]        = ((close - sl20)  / (atr14 + 1e-8)).clip(-10, 10)
    
    # Apply Higher Timeframe Confluence to structure bias
    df = add_htf_bias(df)
    base_structure = (sh20 > high.rolling(60).max().shift(20)).astype(int)
    df["Structure_Bullish"] = (base_structure & df["HTF_Bullish_Bias"]).astype(int)

    rh = high.rolling(60).max()
    rl = low.rolling(60).min()
    df["PD_Position"] = ((close - rl) / (rh - rl).replace(0, np.nan)).fillna(0.5).clip(0, 1)

    # Refined Fair Value Gap (FVG) detection: Multi-candle series of upclose/downclose candles leaving a price gap
    bull_fvg = pd.Series(False, index=df.index)
    bear_fvg = pd.Series(False, index=df.index)
    bull_fvg_lo = pd.Series(np.nan, index=df.index)
    bull_fvg_hi = pd.Series(np.nan, index=df.index)
    bear_fvg_lo = pd.Series(np.nan, index=df.index)
    bear_fvg_hi = pd.Series(np.nan, index=df.index)

    close_val = close.values
    open_val = open_.values
    high_val = high.values
    low_val = low.values

    for i in range(3, len(df)):
        # Bullish FVG check: Series of upclose (bullish) candles where high of candle before series does not reach low of candle after series
        if close_val[i-1] > open_val[i-1]:
            n = 0
            while i - 1 - n >= 1 and close_val[i - 1 - n] > open_val[i - 1 - n]:
                n += 1
            if n >= 1:
                k = i - n
                before_high = high_val[k - 1]
                after_low = low_val[i]
                if after_low > before_high:
                    bull_fvg.iloc[i] = True
                    bull_fvg_lo.iloc[i] = before_high
                    bull_fvg_hi.iloc[i] = after_low

        # Bearish FVG check: Series of downclose (bearish) candles where low of candle before series does not reach high of candle after series
        if close_val[i-1] < open_val[i-1]:
            n = 0
            while i - 1 - n >= 1 and close_val[i - 1 - n] < open_val[i - 1 - n]:
                n += 1
            if n >= 1:
                k = i - n
                before_low = low_val[k - 1]
                after_high = high_val[i]
                if after_high < before_low:
                    bear_fvg.iloc[i] = True
                    bear_fvg_lo.iloc[i] = after_high
                    bear_fvg_hi.iloc[i] = before_low

    df["Bull_FVG_Count"] = bull_fvg.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_FVG_Count"] = bear_fvg.astype(int).rolling(10, min_periods=1).sum()
    bearish = (close < open_)
    bullish = (close > open_)

    # Refined Order Block detection: Change in state of delivery (multi-candle downclose/upclose series engulfed by displacement)
    bull_ob = pd.Series(False, index=df.index)
    bear_ob = pd.Series(False, index=df.index)
    bull_ob_lo = pd.Series(np.nan, index=df.index)
    bull_ob_hi = pd.Series(np.nan, index=df.index)
    bear_ob_lo = pd.Series(np.nan, index=df.index)
    bear_ob_hi = pd.Series(np.nan, index=df.index)

    close_val = close.values
    open_val = open_.values
    high_val = high.values
    low_val = low.values
    disp_val = df["Displacement"].values

    for i in range(3, len(df)):
        # Bullish OB: Series of downclose (bearish) candles engulfed by a displacement bullish candle
        if close_val[i] > open_val[i] and disp_val[i] == 1:
            n = 0
            while i - 1 - n >= 0 and close_val[i - 1 - n] < open_val[i - 1 - n]:
                n += 1
            if n >= 1:
                k = i - n
                first_open = open_val[k]
                if close_val[i] >= first_open:
                    bull_ob.iloc[i] = True
                    # Key level of OB is the Open of the first bearish candle
                    bull_ob_hi.iloc[i] = first_open
                    # Low bound of OB is the lowest low of the bearish series
                    bull_ob_lo.iloc[i] = np.min(low_val[k:i])

        # Bearish OB: Series of upclose (bullish) candles engulfed by a displacement bearish candle
        if close_val[i] < open_val[i] and disp_val[i] == 1:
            n = 0
            while i - 1 - n >= 0 and close_val[i - 1 - n] > open_val[i - 1 - n]:
                n += 1
            if n >= 1:
                k = i - n
                first_open = open_val[k]
                if close_val[i] <= first_open:
                    bear_ob.iloc[i] = True
                    # Key level of OB is the Open of the first bullish candle
                    bear_ob_lo.iloc[i] = first_open
                    # High bound of OB is the highest high of the bullish series
                    bear_ob_hi.iloc[i] = np.max(high_val[k:i])

    df["Bull_OB_Count"] = bull_ob.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_OB_Count"] = bear_ob.astype(int).rolling(10, min_periods=1).sum()

    pwh = high.rolling(5).max().shift(1)
    pwl = low.rolling(5).min().shift(1)
    df["Dist_PWH"] = ((pwh - close) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_PWL"] = ((close - pwl)  / (atr14 + 1e-8)).clip(-10, 10)

    df["Swept_High"] = ((high > sh20.shift(1)) & (close < sh20.shift(1))).astype(int)
    df["Swept_Low"]  = ((low  < sl20.shift(1)) & (close > sl20.shift(1))).astype(int)

    q = df.index.quarter
    m = df.index.month
    df["Quarter_Sin"] = np.sin(2 * np.pi * q / 4)
    df["Quarter_Cos"] = np.cos(2 * np.pi * q / 4)
    df["Month_Sin"]   = np.sin(2 * np.pi * m / 12)
    df["Month_Cos"]   = np.cos(2 * np.pi * m / 12)

    # ICT 2022, IPDA lookback levels (20 / 40 / 60 bars)
    for n in [20, 40, 60]:
        df[f"IPDA_{n}_High_Dist"] = ((high.rolling(n).max().shift(1) - close) / (atr14 + 1e-8)).clip(-20, 20)
        df[f"IPDA_{n}_Low_Dist"]  = ((close - low.rolling(n).min().shift(1))  / (atr14 + 1e-8)).clip(-20, 20)

    # ICT 2022, Equal Highs / Equal Lows (liquidity pools)
    tol  = close * 0.001
    r10h = high.rolling(10).max().shift(1)
    r10l = low.rolling(10).min().shift(1)
    df["Equal_Highs"] = ((high - r10h).abs() < tol).astype(int).rolling(10, min_periods=1).sum()
    df["Equal_Lows"]  = ((low  - r10l).abs() < tol).astype(int).rolling(10, min_periods=1).sum()

    # ICT 2022, OTE zone (Optimal Trade Entry: 0.62-0.79 Fibonacci of 20-bar swing)
    rng20 = (sh20 - sl20).replace(0, np.nan)
    df["In_OTE_Buy"]  = ((close >= sh20 - rng20 * 0.79) & (close <= sh20 - rng20 * 0.62)).astype(int)
    df["In_OTE_Sell"] = ((close >= sl20 + rng20 * 0.62) & (close <= sl20 + rng20 * 0.79)).astype(int)

    # ICT 2022, Consequent Encroachment (CE) of most recent FVG midpoint
    bull_ce_level = ((high.shift(2) + low) / 2).where(bull_fvg.astype(bool)).ffill()
    bear_ce_level = ((low.shift(2)  + high) / 2).where(bear_fvg.astype(bool)).ffill()
    df["CE_Bull_FVG_Dist"] = ((close - bull_ce_level) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["CE_Bear_FVG_Dist"] = ((bear_ce_level - close) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)

    # ── New ICT concepts ────────────────────────────────────────────────────

    # Equilibrium (EQ): the exact 50% midpoint of the 60-bar range. Premium/
    # Discount (PD_Position) is already the continuous 0-1 position; EQ is
    # specifically the distance from that midpoint, since ICT treats 50% as
    # its own decision line (price "respecting EQ" vs running through it).
    df["Dist_to_EQ"] = (df["PD_Position"] - 0.5).clip(-0.5, 0.5)

    # Breaker Block: an order block that failed (price closed through its
    # origin candle) and is expected to flip and act as opposite-role S/R.
    bull_breaker = (close < bull_ob_lo.ffill()) & bull_ob_lo.ffill().notna()
    bear_breaker = (close > bear_ob_hi.ffill()) & bear_ob_hi.ffill().notna()
    df["Bull_Breaker_Count"] = bull_breaker.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_Breaker_Count"] = bear_breaker.astype(int).rolling(10, min_periods=1).sum()
    bull_breaker_level = bull_ob_lo.ffill().where(bull_breaker).ffill()
    bear_breaker_level = bear_ob_hi.ffill().where(bear_breaker).ffill()
    df["Dist_Bull_Breaker"] = ((close - bull_breaker_level) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Dist_Bear_Breaker"] = ((bear_breaker_level - close) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)

    # Mitigation Block: a softer alternative to the Order Block - the last
    # opposing candle before two consecutive candles in the new direction,
    # without requiring a full displacement candle. Looser trigger than OB.
    two_bull = bullish & bullish.shift(1).fillna(False)
    two_bear = bearish & bearish.shift(1).fillna(False)
    bull_mitigation = bearish.shift(2).fillna(False) & two_bull.shift(0).fillna(False) & ~bull_ob.shift(1).fillna(False)
    bear_mitigation = bullish.shift(2).fillna(False) & two_bear.shift(0).fillna(False) & ~bear_ob.shift(1).fillna(False)
    df["Bull_Mitigation_Count"] = bull_mitigation.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_Mitigation_Count"] = bear_mitigation.astype(int).rolling(10, min_periods=1).sum()

    # Rejection Block: candle whose wick (not body) rejected a level - long
    # lower wick closing in the top half (bullish rejection) or long upper
    # wick closing in the bottom half (bearish rejection).
    lower_wick = (pd.concat([open_, close], axis=1).min(axis=1) - low)
    upper_wick = (high - pd.concat([open_, close], axis=1).max(axis=1))
    close_pos  = ((close - low) / rng).fillna(0.5)
    bull_rejection = (lower_wick > body * 2) & (close_pos > 0.5)
    bear_rejection = (upper_wick > body * 2) & (close_pos < 0.5)
    df["Bull_Rejection_Count"] = bull_rejection.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_Rejection_Count"] = bear_rejection.astype(int).rolling(10, min_periods=1).sum()

    # Turtle Soup: liquidity grab beyond the prior 20-bar extreme that
    # immediately reverses back inside the range (false breakout).
    df["Turtle_Soup_Buy"]  = ((low  < sl20.shift(1)) & (close > sl20.shift(1)) & (close > open_)).astype(int)
    df["Turtle_Soup_Sell"] = ((high > sh20.shift(1)) & (close < sh20.shift(1)) & (close < open_)).astype(int)

    # Power of Three (AMD): classify each bar's regime by comparing its
    # range to a short-term baseline - tight range vs prior 10 bars is
    # "Accumulation", a liquidity sweep is "Manipulation", and a displacement
    # continuing the sweep's implied direction is "Distribution". Encoded
    # as three mutually-exclusive flags rather than a single categorical,
    # so downstream models don't need to learn an ordinal encoding.
    avg_rng10 = rng.rolling(10, min_periods=1).mean()
    df["AMD_Accumulation"] = (rng < avg_rng10 * 0.6).astype(int)
    df["AMD_Manipulation"] = (df["Swept_High"] | df["Swept_Low"]).astype(int)
    df["AMD_Distribution"] = (
        (df["Displacement"] == 1) &
        ((df["Swept_Low"].shift(1).fillna(0) == 1) | (df["Swept_High"].shift(1).fillna(0) == 1))
    ).astype(int)

    # Unicorn Model: a Breaker Block whose zone overlaps a Fair Value Gap -
    # ICT's highest-confluence entry model, combining both concepts.
    bull_fvg_lo_f = bull_fvg_lo.ffill()
    bull_fvg_hi_f = bull_fvg_hi.ffill()
    bear_fvg_lo_f = bear_fvg_lo.ffill()
    bear_fvg_hi_f = bear_fvg_hi.ffill()
    bull_ob_lo_f = bull_ob_lo.ffill()
    bull_ob_hi_f = bull_ob_hi.ffill()
    bear_ob_lo_f = bear_ob_lo.ffill()
    bear_ob_hi_f = bear_ob_hi.ffill()
    df["Unicorn_Bull"] = (
        (bull_ob_lo_f <= bull_fvg_hi_f) & (bull_ob_hi_f >= bull_fvg_lo_f) &
        bull_ob_lo_f.notna() & bull_fvg_lo_f.notna()
    ).astype(int)
    df["Unicorn_Bear"] = (
        (bear_ob_lo_f <= bear_fvg_hi_f) & (bear_ob_hi_f >= bear_fvg_lo_f) &
        bear_ob_lo_f.notna() & bear_fvg_lo_f.notna()
    ).astype(int)

    # Propulsion Block: the last small-range candle before a displacement
    # candle that continues the PRIOR trend (as opposed to an Order Block,
    # which precedes a reversal). Signals trend continuation, not reversal.
    prior_trend_up   = df["Structure_Bullish"].astype(bool)
    small_range      = rng < avg_rng10
    propulsion_bull  = small_range.shift(1).fillna(False) & (df["Displacement"] == 1) & bullish & prior_trend_up
    propulsion_bear  = small_range.shift(1).fillna(False) & (df["Displacement"] == 1) & bearish & ~prior_trend_up
    df["Propulsion_Bull_Count"] = propulsion_bull.astype(int).rolling(10, min_periods=1).sum()
    df["Propulsion_Bear_Count"] = propulsion_bear.astype(int).rolling(10, min_periods=1).sum()

    # Inversion FVG (IFVG): a Fair Value Gap that gets fully filled/violated
    # and then flips to act as support (was resistance) or resistance (was
    # support) - the FVG equivalent of a Breaker Block.
    bull_ifvg = (close < bull_fvg_lo_f) & bull_fvg_lo_f.notna()
    bear_ifvg = (close > bear_fvg_hi_f) & bear_fvg_hi_f.notna()
    df["Bull_IFVG_Count"] = bull_ifvg.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_IFVG_Count"] = bear_ifvg.astype(int).rolling(10, min_periods=1).sum()

    # Standard Deviation projections: ICT projects 1x/2x (and -1x/-2x) of the
    # most recent Order Block's range from its origin as take-profit levels.
    # Encoded as the current close's position relative to those projections.
    bull_ob_range = (bull_ob_hi_f - bull_ob_lo_f)
    bear_ob_range = (bear_ob_hi_f - bear_ob_lo_f)
    df["Dist_StdDev_Bull_1x"] = ((close - (bull_ob_hi_f + bull_ob_range)) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Dist_StdDev_Bull_2x"] = ((close - (bull_ob_hi_f + bull_ob_range * 2)) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Dist_StdDev_Bear_1x"] = (((bear_ob_lo_f - bear_ob_range) - close) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Dist_StdDev_Bear_2x"] = (((bear_ob_lo_f - bear_ob_range * 2) - close) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)

    # ADR (Average Daily Range): how much of the typical daily range has
    # already been consumed by the current bar's range - used by ICT to
    # judge whether a move is "extended" and due for exhaustion/reversal.
    adr14 = rng.rolling(14, min_periods=1).mean()
    df["ADR_Consumed_Pct"] = (rng / (adr14 + 1e-8)).clip(0, 5).fillna(1.0)

    # Market Maker Buy/Sell Model (MMBM/MMSM), simplified: a liquidity sweep
    # (manipulation) followed within 5 bars by a structure shift in the
    # opposite direction (confirmation) followed by displacement (entry
    # trigger). This is a rule-based approximation of ICT's multi-step
    # sequence, not every nuance of the full teaching.
    swept_low_recent  = df["Swept_Low"].rolling(5, min_periods=1).max().astype(bool)
    swept_high_recent = df["Swept_High"].rolling(5, min_periods=1).max().astype(bool)
    struct_shift_up   = df["Structure_Bullish"].astype(bool) & ~df["Structure_Bullish"].shift(1).fillna(0).astype(bool)
    struct_shift_down = ~df["Structure_Bullish"].astype(bool) & df["Structure_Bullish"].shift(1).fillna(0).astype(bool)
    df["MMBM_Signal"] = (swept_low_recent.shift(1).fillna(False) & struct_shift_up & (df["Displacement"] == 1) & bullish).astype(int)
    df["MMSM_Signal"] = (swept_high_recent.shift(1).fillna(False) & struct_shift_down & (df["Displacement"] == 1) & bearish).astype(int)

    return df


# ── Intraday-only ICT (needs a time-of-day) ─────────────────────────────────

def add_intraday_ict(df: pd.DataFrame) -> pd.DataFrame:
    """Kill zones, session, and 2022 Silver Bullet / Asia range features.

    Kill zones are based on New York (ET) session times, converted from
    whatever tz yfinance returns (usually UTC for intraday).
    """
    idx = df.index
    if idx.tz is not None:
        et_idx = idx.tz_convert("America/New_York")
    else:
        et_idx = idx.tz_localize("UTC").tz_convert("America/New_York")

    hour = et_idx.hour

    df["In_London_KZ"]  = ((hour >= 3)  & (hour < 5)).astype(int)
    df["In_NY_Open_KZ"] = ((hour >= 9)  & (hour < 11)).astype(int)
    df["In_NY_PM_KZ"]   = ((hour >= 13) & (hour < 15)).astype(int)

    date_str = pd.Series(et_idx.date, index=df.index)
    midnight_open = df.groupby(date_str)["Open"].transform("first")
    df["Price_vs_MidnightOpen"] = ((df["Close"] - midnight_open) / (midnight_open + 1e-8) * 100)

    session_high = df.groupby(date_str)["High"].transform("cummax")
    session_low  = df.groupby(date_str)["Low"].transform("cummin")
    atr_h = ta.volatility.AverageTrueRange(df["High"], df["Low"], df["Close"], window=14) \
              .average_true_range().fillna(df["Close"] * 0.01)
    df["Session_High_Dist"] = ((session_high - df["Close"]) / (atr_h + 1e-8)).clip(-10, 10)
    df["Session_Low_Dist"]  = ((df["Close"] - session_low)  / (atr_h + 1e-8)).clip(-10, 10)

    df["Hour_Sin"] = np.sin(2 * np.pi * hour / 24)
    df["Hour_Cos"] = np.cos(2 * np.pi * hour / 24)
    dow = et_idx.dayofweek
    df["Day_Sin"] = np.sin(2 * np.pi * dow / 5)
    df["Day_Cos"] = np.cos(2 * np.pi * dow / 5)

    df["In_SilverBullet_AM"] = ((hour >= 10) & (hour < 11)).astype(int)
    df["In_SilverBullet_PM"] = ((hour >= 14) & (hour < 15)).astype(int)

    is_asia = (hour >= 20) | (hour < 2)
    atr_h2 = atr_h
    asia_high_ref = df["High"].where(is_asia).rolling(14, min_periods=1).max().ffill()
    asia_low_ref  = df["Low"].where(is_asia).rolling(14, min_periods=1).min().ffill()
    df["Asia_High_Dist"]    = ((asia_high_ref - df["Close"]) / (atr_h2 + 1e-8)).clip(-10, 10).fillna(0)
    df["Asia_Low_Dist"]     = ((df["Close"] - asia_low_ref)  / (atr_h2 + 1e-8)).clip(-10, 10).fillna(0)
    df["Asia_Range_Norm"]   = ((asia_high_ref - asia_low_ref) / (atr_h2 + 1e-8)).clip(0, 20).fillna(0)
    df["Price_vs_AsiaHigh"] = (df["Close"] > asia_high_ref).astype(int)
    df["Price_vs_AsiaLow"]  = (df["Close"] < asia_low_ref).astype(int)

    is_monday  = (et_idx.dayofweek == 0)
    prev_close = df["Close"].shift(1)
    nwog_open  = df["Open"].where(is_monday).ffill()
    nwog_close = prev_close.where(is_monday).ffill()
    nwog_lo    = nwog_close.clip(lower=0)
    nwog_hi    = nwog_open
    df["In_NWOG"] = (
        nwog_hi.notna() & nwog_lo.notna() &
        (df["Close"] >= nwog_lo) & (df["Close"] <= nwog_hi)
    ).astype(int)
    week_gap = (df["Open"] - prev_close).where(is_monday).ffill().fillna(0)
    df["NWOG_Gap_Norm"] = (week_gap / (atr_h2 + 1e-8)).clip(-5, 5)

    # ── New intraday-only ICT concepts ──────────────────────────────────────

    # Judas Swing: a false directional move in the first hour of the NY
    # session (09:30-10:30 ET) that reverses relative to where price ends
    # up moving for the rest of that session - the "manipulation" leg ICT
    # says precedes the real move of the day.
    in_open_hour = (hour >= 9) & (hour < 10)
    open_hour_start = df["Open"].where(in_open_hour).groupby(date_str).transform("first")
    open_hour_end   = df["Close"].where(in_open_hour).groupby(date_str).transform("last")
    day_close       = df.groupby(date_str)["Close"].transform("last")
    open_hour_dir = np.sign((open_hour_end - open_hour_start).fillna(0))
    day_dir       = np.sign((day_close - open_hour_end).fillna(0))
    df["Judas_Swing"] = ((open_hour_dir != 0) & (day_dir != 0) & (open_hour_dir != day_dir)).astype(int)

    # True Week/Month Open: NY-midnight open of the first trading day of
    # the week/month, distinct from the daily midnight open above - ICT
    # treats these as higher-timeframe reference/decision points.
    iso_week  = pd.Series(et_idx.isocalendar().week.values, index=df.index)
    year_week = pd.Series(et_idx.isocalendar().year.values, index=df.index).astype(str) + "-" + iso_week.astype(str)
    year_month = pd.Series(et_idx.year, index=df.index).astype(str) + "-" + pd.Series(et_idx.month, index=df.index).astype(str)
    true_week_open  = df.groupby(year_week)["Open"].transform("first")
    true_month_open = df.groupby(year_month)["Open"].transform("first")
    df["Price_vs_TrueWeekOpen"]  = ((df["Close"] - true_week_open)  / (true_week_open + 1e-8) * 100)
    df["Price_vs_TrueMonthOpen"] = ((df["Close"] - true_month_open) / (true_month_open + 1e-8) * 100)

    return df


# ── SMT Divergence (needs a correlated reference instrument) ───────────────

def add_smt_divergence(df: pd.DataFrame, ref_df) -> pd.DataFrame:
    """Smart Money Technique divergence: flag when this instrument makes a
    new swing high/low that its correlated reference (SPY/sector ETF,
    already fetched as aux data for VIX/sector features) does NOT confirm -
    a classic ICT tell that the move lacks broad participation.

    Simplification: ICT typically pairs specific correlated instruments
    (ES/NQ, EURUSD/DXY, etc.); here the reference is whatever aux data is
    already available (SPY, or the ticker's sector ETF), which won't be a
    genuine correlated pair for every asset class (crypto/forex/commodities
    have no real SPY correlation). Zero-filled when no reference exists,
    same pattern as VIX/sector features.
    """
    if ref_df is None or ref_df.empty:
        df["SMT_Bull_Divergence"] = 0
        df["SMT_Bear_Divergence"] = 0
        return df

    idx = df.index.normalize() if df.index.tz is None else df.index.tz_convert(None).normalize()
    ref = ref_df[["High", "Low"]].copy()
    ref.index = ref.index.normalize() if ref.index.tz is None else ref.index.tz_localize(None).normalize()
    ref = ref[~ref.index.duplicated(keep="last")]
    ref = ref.reindex(idx, method="ffill")
    ref.index = df.index

    self_high20 = df["High"].rolling(20).max()
    self_low20  = df["Low"].rolling(20).min()
    ref_high20  = ref["High"].rolling(20).max()
    ref_low20   = ref["Low"].rolling(20).min()

    self_new_high = df["High"] >= self_high20.shift(1)
    ref_new_high  = ref["High"] >= ref_high20.shift(1)
    self_new_low  = df["Low"]  <= self_low20.shift(1)
    ref_new_low   = ref["Low"] <= ref_low20.shift(1)

    df["SMT_Bear_Divergence"] = (self_new_high & ~ref_new_high.fillna(False)).astype(int)
    df["SMT_Bull_Divergence"] = (self_new_low  & ~ref_new_low.fillna(False)).astype(int)
    return df


BASE_ICT_COLS = [
    # Existing (unchanged)
    "Above_200SMA", "Dist_200SMA", "Body_Ratio", "Displacement",
    "Dist_to_SH", "Dist_to_SL", "Structure_Bullish", "PD_Position",
    "Bull_FVG_Count", "Bear_FVG_Count", "Bull_OB_Count", "Bear_OB_Count",
    "Dist_PWH", "Dist_PWL", "Swept_High", "Swept_Low",
    "IPDA_20_High_Dist", "IPDA_20_Low_Dist", "IPDA_40_High_Dist", "IPDA_40_Low_Dist",
    "IPDA_60_High_Dist", "IPDA_60_Low_Dist", "Equal_Highs", "Equal_Lows",
    "In_OTE_Buy", "In_OTE_Sell", "CE_Bull_FVG_Dist", "CE_Bear_FVG_Dist",
    "Quarter_Sin", "Quarter_Cos", "Month_Sin", "Month_Cos",
    # New concepts
    "Dist_to_EQ",
    "Bull_Breaker_Count", "Bear_Breaker_Count", "Dist_Bull_Breaker", "Dist_Bear_Breaker",
    "Bull_Mitigation_Count", "Bear_Mitigation_Count",
    "Bull_Rejection_Count", "Bear_Rejection_Count",
    "Turtle_Soup_Buy", "Turtle_Soup_Sell",
    "AMD_Accumulation", "AMD_Manipulation", "AMD_Distribution",
    "Unicorn_Bull", "Unicorn_Bear",
    "Propulsion_Bull_Count", "Propulsion_Bear_Count",
    "Bull_IFVG_Count", "Bear_IFVG_Count",
    "Dist_StdDev_Bull_1x", "Dist_StdDev_Bull_2x", "Dist_StdDev_Bear_1x", "Dist_StdDev_Bear_2x",
    "ADR_Consumed_Pct",
    "MMBM_Signal", "MMSM_Signal",
]

INTRADAY_ICT_COLS = [
    "In_London_KZ", "In_NY_Open_KZ", "In_NY_PM_KZ",
    "Session_High_Dist", "Session_Low_Dist", "Price_vs_MidnightOpen",
    "Hour_Sin", "Hour_Cos", "Day_Sin", "Day_Cos",
    "In_SilverBullet_AM", "In_SilverBullet_PM",
    "Asia_High_Dist", "Asia_Low_Dist", "Asia_Range_Norm",
    "Price_vs_AsiaHigh", "Price_vs_AsiaLow",
    "In_NWOG", "NWOG_Gap_Norm",
    # New concepts
    "Judas_Swing", "Price_vs_TrueWeekOpen", "Price_vs_TrueMonthOpen",
]

SMT_COLS = ["SMT_Bull_Divergence", "SMT_Bear_Divergence"]
