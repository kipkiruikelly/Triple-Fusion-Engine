import pandas as pd
import numpy as np
from ml_framework.base import BaseFeatureBuilder
import predictor

class MarketFeaturesBuilder(BaseFeatureBuilder):
    """Modular feature builder for market-wide auxiliary features (VIX regimes, Sector metrics, Earnings windows)."""
    
    def build_features(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        df = df.copy()
        ticker = kwargs.get("ticker", "SPY")
        interval = kwargs.get("interval", "1d")
        
        # Call legacy helper logic for VIX, Sector, Earnings and SMT Confluences
        aux = predictor._fetch_aux(ticker, interval)
        df = predictor.build_features(df, interval, ticker, aux)
        return df
