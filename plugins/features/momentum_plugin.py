import pandas as pd
from ml_framework.base import BaseFeatureBuilder
from ml_framework.features.base_builder import FEATURE_BUILDERS

class MomentumPluginBuilder(BaseFeatureBuilder):
    """Dynamic custom feature plugin to compute specialized momentum metrics."""
    
    def build_features(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        df = df.copy()
        # Compute custom momentum: close percent change over 5 periods
        df["Custom_Momentum_5"] = df["Close"].pct_change(5).fillna(0)
        return df

def register_plugin(orchestrator):
    """Registration hook called dynamically by the orchestrator loader."""
    print("Dynamically registering plugin: custom_momentum")
    FEATURE_BUILDERS["custom_momentum"] = MomentumPluginBuilder
