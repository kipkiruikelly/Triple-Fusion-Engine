from ml_framework.base import BaseFeatureBuilder
from ml_framework.features.ta_builder import TechnicalAnalysisBuilder
from ml_framework.features.ict_builder import ICTIndicatorsBuilder
from ml_framework.features.market_features_builder import MarketFeaturesBuilder

# Registry mapping
FEATURE_BUILDERS = {
    "technical_analysis": TechnicalAnalysisBuilder,
    "ict_indicators": ICTIndicatorsBuilder,
    "auxiliary_market_features": MarketFeaturesBuilder
}
