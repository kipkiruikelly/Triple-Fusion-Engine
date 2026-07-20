import os
import time
import requests
import io
import pandas as pd
from flask import render_template, jsonify
from flask_login import login_required
import yfinance as yf

_MACRO_CACHE = {}
_MACRO_CACHE_TIMEOUT = 3600  # 1 hour cache

_HEATMAP_CACHE = {}
_HEATMAP_CACHE_TIMEOUT = 12 * 3600  # 12 hour cache

def register_macro_routes(app):


    @app.route("/api/macro/data")
    @login_required
    def macro_data():
        now = time.time()
        if "data" in _MACRO_CACHE and now - _MACRO_CACHE.get("timestamp", 0) < _MACRO_CACHE_TIMEOUT:
            return jsonify(_MACRO_CACHE["data"])

        try:
            # 1. Fetch Yield Curve from US Treasury API
            yield_curve = _fetch_yield_curve()

            # 2. Fetch Macro Indicators from FRED CSVs
            indicators = _fetch_fred_indicators()

            # 3. Fetch Market Assets from Yahoo Finance
            markets = _fetch_market_overview()

            result = {
                "yield_curve": yield_curve,
                "indicators": indicators,
                "markets": markets
            }

            _MACRO_CACHE["data"] = result
            _MACRO_CACHE["timestamp"] = now
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/macro/heatmap")
    @login_required
    def macro_heatmap():
        now = time.time()
        if "data" in _HEATMAP_CACHE and now - _HEATMAP_CACHE.get("timestamp", 0) < _HEATMAP_CACHE_TIMEOUT:
            return jsonify(_HEATMAP_CACHE["data"])

        try:
            res = _fetch_heatmap_data()
            _HEATMAP_CACHE["data"] = res
            _HEATMAP_CACHE["timestamp"] = now
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/macro/ticker-insights/<ticker>")
    @login_required
    def ticker_insights(ticker):
        ticker = ticker.upper().strip()
        token = os.environ.get("FINNHUB_API_KEY", "")
        
        # 1. Recommendation Trends (Consensus revisions)
        recs = []
        if token:
            try:
                url = f"https://finnhub.io/api/v1/stock/recommendation?symbol={ticker}&token={token}"
                res = requests.get(url, timeout=8).json()
                recs = res[:4] if isinstance(res, list) else []
            except Exception:
                pass
                
        # 2. Insider Transactions
        insiders = []
        if token:
            try:
                url = f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker}&token={token}"
                res = requests.get(url, timeout=8).json()
                insiders = res.get("data", [])[:25] if isinstance(res, dict) else []
            except Exception:
                pass
                
        return jsonify({
            "ticker": ticker,
            "recommendations": recs,
            "insiders": insiders
        })

def _fetch_yield_curve():
    try:
        url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/daily_treasury_yield_curve_rates?sort=-record_date&page[size]=260"
        res = requests.get(url, timeout=8).json()
        data = res.get("data", [])
        if not data:
            return {}

        curr = data[0]
        m1 = data[min(len(data)-1, 20)]
        y1 = data[min(len(data)-1, 250)]

        maturities = ["1 Mo", "2 Mo", "3 Mo", "4 Mo", "6 Mo", "1 Yr", "2 Yr", "3 Yr", "5 Yr", "7 Yr", "10 Yr", "20 Yr", "30 Yr"]
        keys = ["bc_1month", "bc_2month", "bc_3month", "bc_4month", "bc_6month", "bc_1year", "bc_2year", "bc_3year", "bc_5year", "bc_7year", "bc_10year", "bc_20year", "bc_30year"]

        def extract_yields(record):
            yields = []
            for k in keys:
                val = record.get(k)
                yields.append(float(val) if val is not None else None)
            return yields

        return {
            "maturities": maturities,
            "current": extract_yields(curr),
            "month_ago": extract_yields(m1),
            "year_ago": extract_yields(y1),
            "date_current": curr.get("record_date"),
            "date_month_ago": m1.get("record_date"),
            "date_year_ago": y1.get("record_date")
        }
    except Exception:
        return {}

def _fetch_fred_indicators():
    indicators = {}
    try:
        # Fed Funds Rate
        res = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS", timeout=8)
        df = pd.read_csv(io.StringIO(res.text))
        indicators["fed_funds"] = float(df.iloc[-1]["FEDFUNDS"])
        
        # Unemployment Rate
        res = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE", timeout=8)
        df = pd.read_csv(io.StringIO(res.text))
        indicators["unemployment"] = float(df.iloc[-1]["UNRATE"])

        # CPI (Inflation YoY approximation)
        res = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL", timeout=8)
        df = pd.read_csv(io.StringIO(res.text))
        val_curr = float(df.iloc[-1]["CPIAUCSL"])
        val_prev = float(df.iloc[-13]["CPIAUCSL"])
        indicators["inflation"] = round((val_curr - val_prev) / val_prev * 100, 2)

        # Real GDP Growth (YoY change of latest quarter)
        res = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDPC1", timeout=8)
        df = pd.read_csv(io.StringIO(res.text))
        val_gdp_curr = float(df.iloc[-1]["GDPC1"])
        val_gdp_prev = float(df.iloc[-5]["GDPC1"])
        indicators["gdp_growth"] = round((val_gdp_curr - val_gdp_prev) / val_gdp_prev * 100, 2)
    except Exception:
        pass
    return indicators

def _fetch_market_overview():
    tickers = {
        "S&P 500": "^GSPC",
        "Nasdaq 100": "^IXIC",
        "VIX Fear Index": "^VIX",
        "10-Year Treasury Yield": "^TNX",
        "US Dollar Index": "DX-Y.NYB",
        "Gold": "GC=F",
        "Crude Oil": "CL=F",
        "Bitcoin": "BTC-USD"
    }
    data = {}
    for name, sym in tickers.items():
        try:
            t = yf.Ticker(sym)
            info = t.fast_info
            last_price = info.last_price
            prev_close = info.previous_close
            change = last_price - prev_close
            pct_change = (change / prev_close * 100) if prev_close else 0.0
            data[name] = {
                "symbol": sym,
                "price": round(last_price, 2),
                "change": round(change, 2),
                "pct_change": round(pct_change, 2)
            }
        except Exception:
            pass
    return data


def _fetch_heatmap_data():
    indexes = {
        "S&P 500": "^GSPC",
        "Nasdaq 100": "^IXIC",
        "Dow Jones": "^DJI",
        "Russell 2000": "^RUT",
        "DAX (Germany)": "^GDAXI",
        "FTSE 100 (UK)": "^FTSE",
        "CAC 40 (France)": "^FCHI",
        "Nikkei 225 (Japan)": "^N225",
        "Hang Seng (HK)": "^HSI",
        "Nifty 50 (India)": "^NSEI",
        "Shanghai Comp (China)": "000001.SS",
        "ASX 200 (Australia)": "^AXJO"
    }
    
    heatmap = {}
    for name, sym in indexes.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="1y")
            if hist.empty or len(hist) < 20:
                continue
                
            curr_price = float(hist.iloc[-1]["Close"])
            prev_price = float(hist.iloc[-2]["Close"])
            week_price = float(hist.iloc[-6]["Close"]) if len(hist) >= 6 else prev_price
            month_price = float(hist.iloc[-21]["Close"]) if len(hist) >= 21 else prev_price
            
            df_2026 = hist[hist.index.year == 2026]
            if not df_2026.empty:
                ytd_price = float(df_2026.iloc[0]["Close"])
            else:
                ytd_price = float(hist.iloc[0]["Close"])
                
            heatmap[name] = {
                "symbol": sym,
                "price": round(curr_price, 2),
                "chg_1d": round((curr_price - prev_price) / prev_price * 100, 2),
                "chg_1w": round((curr_price - week_price) / week_price * 100, 2),
                "chg_1m": round((curr_price - month_price) / month_price * 100, 2),
                "chg_ytd": round((curr_price - ytd_price) / ytd_price * 100, 2)
            }
        except Exception:
            pass
    return heatmap
