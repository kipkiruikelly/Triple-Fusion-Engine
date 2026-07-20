import pandas as pd
from ml_framework.base import BaseFeatureBuilder
import ict_features

class ICTIndicatorsBuilder(BaseFeatureBuilder):
    """Modular feature builder for ICT indicators (Fair Value Gaps, Order Blocks, Liquidity Sweeps)."""
    
    def build_features(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        df = df.copy()
        # Add basic TA indicators if not already present
        if "SMA_7" not in df.columns:
            df = ict_features.add_base_ta(df)
            
        # Add intraday ICT features (Kill zones, session liquidity sweeps)
        df = ict_features.add_intraday_ict(df)
        return df
