# Empty connector module setup
from ml_framework.base import BaseConnector
from ml_framework.connectors.yf_connector import YFinanceConnector

# Registry mapping
CONNECTORS = {
    "yfinance": YFinanceConnector
}
