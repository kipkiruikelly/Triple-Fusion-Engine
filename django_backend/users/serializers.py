from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    role_level = serializers.IntegerField(read_only=True)
    is_pro     = serializers.BooleanField(read_only=True)
    is_plus    = serializers.BooleanField(read_only=True)
    level      = serializers.IntegerField(read_only=True)
    xp_into_level = serializers.IntegerField(read_only=True)
    predictions_remaining = serializers.SerializerMethodField()
    total_predictions = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = [
            'id', 'username', 'email', 'role', 'role_level', 'plan',
            'status', 'created_at', 'last_seen', 'email_verified',
            'theme_preference', 'alerts_enabled', 'xp', 'level',
            'xp_into_level', 'current_streak', 'longest_streak',
            'paper_trading_opted_in', 'is_pro', 'is_plus',
            'predictions_remaining', 'predictions_today', 'total_predictions',
        ]
        read_only_fields = fields

    def get_predictions_remaining(self, obj):
        return obj.predictions_remaining

    def get_total_predictions(self, obj):
        from users.models import PredictionHistory
        return PredictionHistory.objects.filter(user=obj).count()
