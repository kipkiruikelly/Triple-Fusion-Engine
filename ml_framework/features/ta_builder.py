import pandas as pd
from ml_framework.base import BaseFeatureBuilder
import ict_features

class TechnicalAnalysisBuilder(BaseFeatureBuilder):
    """Modular feature builder for Technical Analysis indicators."""
    
    def build_features(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        df = df.copy()
        # Add basic TA indicators
        return ict_features.add_base_ta(df)
