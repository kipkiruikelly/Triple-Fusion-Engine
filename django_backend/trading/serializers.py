"""trading/serializers.py — DRF serializers for trading resources."""

from rest_framework import serializers
from users.models import TradingBot, WatchlistItem, PortfolioPosition, UserBotSubscription


class TradingBotSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TradingBot
        fields = ['id', 'slug', 'name', 'description', 'asset_class', 'interval', 'is_active', 'created_at']


class WatchlistItemSerializer(serializers.ModelSerializer):
    class Meta:
        model  = WatchlistItem
        fields = ['id', 'ticker', 'added_at']


class PortfolioPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PortfolioPosition
        fields = ['id', 'ticker', 'side', 'entry_price', 'quantity', 'exit_price', 'status', 'opened_at', 'closed_at']
