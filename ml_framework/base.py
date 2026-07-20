from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any, List

class BaseConnector(ABC):
    """Abstract base class for all data ingestion connectors."""
    
    @abstractmethod
    def fetch_data(self, symbol: str, interval: str, **kwargs) -> pd.DataFrame:
        """Fetch raw historical OHLCV data for the given symbol and timeframe."""
        pass


class BaseFeatureBuilder(ABC):
    """Abstract base class for all feature engineering builders."""
    
    @abstractmethod
    def build_features(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """Transform raw OHLCV DataFrame into a features-enriched DataFrame."""
        pass


class BaseModelTrainer(ABC):
    """Abstract base class for all model training wrappers."""
    
    @abstractmethod
    def train(self, df: pd.DataFrame, features: List[str], target_col: str, **kwargs) -> Dict[str, Any]:
        """Train models using the prepared features and target column."""
        pass


class BasePredictor(ABC):
    """Abstract base class for all prediction & serving layers."""
    
    @abstractmethod
    def predict(self, df: pd.DataFrame, features: List[str], models: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Generate direction, targets, and confidence levels using active models."""
        pass
