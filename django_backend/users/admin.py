from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    User, PredictionHistory, Payment, TradingBot, WatchlistItem,
    PriceAlert, PortfolioPosition, ApiKey, PredictionAccuracy,
    PasswordResetToken, TelegramConfig, WhatsappConfig, Notification,
    TradeJournal, DiscordConfig, GiftCode, UserWebhook, ActivityLog,
    TwoFactorAuth, AdminAuditLog, AppSetting, TickerConfig, Broadcast,
    ErrorLog, PythFeed, ResourceLink, Feedback, PaperTrade, PaperTradeEvent,
    PaperEquitySnapshot, UserPreferences, Watchlist, UserPortfolio,
    UserAchievement, CompetitionModel, CompetitionEntry, ModelVersion,
    UserBotSubscription, UserPaperAccount, UserPaperOrder, UserPaperPosition,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display   = ['username', 'email', 'role', 'plan', 'status', 'created_at']
    list_filter    = ['role', 'plan', 'status', 'email_verified']
    search_fields  = ['username', 'email']
    ordering       = ['-created_at']
    fieldsets      = None
    add_fieldsets  = (
        (None, {'fields': ('username', 'email', 'password1', 'password2')}),
    )


admin.site.register(PredictionHistory)
admin.site.register(WatchlistItem)
admin.site.register(PriceAlert)
admin.site.register(PortfolioPosition)
admin.site.register(ApiKey)
admin.site.register(PredictionAccuracy)
admin.site.register(PasswordResetToken)
admin.site.register(TelegramConfig)
admin.site.register(WhatsappConfig)
admin.site.register(Notification)
admin.site.register(TradeJournal)
admin.site.register(DiscordConfig)
admin.site.register(Payment)
admin.site.register(GiftCode)
admin.site.register(UserWebhook)
admin.site.register(ActivityLog)
admin.site.register(TwoFactorAuth)
admin.site.register(AdminAuditLog)
admin.site.register(AppSetting)
admin.site.register(TickerConfig)
admin.site.register(Broadcast)
admin.site.register(ErrorLog)
admin.site.register(PythFeed)
admin.site.register(ResourceLink)
admin.site.register(Feedback)
admin.site.register(PaperTrade)
admin.site.register(PaperTradeEvent)
admin.site.register(PaperEquitySnapshot)
admin.site.register(UserPreferences)
admin.site.register(Watchlist)
admin.site.register(UserPortfolio)
admin.site.register(UserAchievement)
admin.site.register(CompetitionModel)
admin.site.register(CompetitionEntry)
admin.site.register(ModelVersion)
admin.site.register(TradingBot)
admin.site.register(UserBotSubscription)
admin.site.register(UserPaperAccount)
admin.site.register(UserPaperOrder)
admin.site.register(UserPaperPosition)
