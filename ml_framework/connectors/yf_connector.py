import pandas as pd
import yfinance as yf
from ml_framework.base import BaseConnector
from market_data import get_history

class YFinanceConnector(BaseConnector):
    """Yahoo Finance modular data ingestion connector."""
    
    def fetch_data(self, symbol: str, interval: str, **kwargs) -> pd.DataFrame:
        period = kwargs.get("period")
        if not period:
            # yfinance periods lookup
            periods = {
                "1m":  "7d",
                "5m":  "60d",
                "15m": "60d",
                "30m": "60d",
                "1h":  "730d",
                "4h":  "730d",
                "1d":  "18mo",
            }
            period = periods.get(interval, "1y")
            
        # Clean symbol logic (handled inside database mapping/predictor files)
        clean_symbol = symbol.split(':').pop() if ':' in symbol else symbol
        
        # Call legacy safe downloader
        df, _ = get_history(clean_symbol, period=period, interval=interval)
        return df
