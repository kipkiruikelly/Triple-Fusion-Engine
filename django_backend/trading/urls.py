from django.urls import path
from . import views
from . import prediction_views
from . import extra_views
from . import portfolio_views
from . import paper_views
from . import scanner_views
from . import tools_views
from . import macro_views
from . import mt5_views
from . import pipeline_views

urlpatterns = [
    # ── Bots ─────────────────────────────────────────────────────
    path('bots', views.BotsView.as_view(), name='api-bots'),
    path('bots/subscribe', views.BotSubscribeView.as_view(), name='api-bots-subscribe'),

    # ── Market ────────────────────────────────────────────────────
    path('market/movers', views.MarketMoversView.as_view(), name='api-market-movers'),
    path('market/history', views.MarketHistoryView.as_view(), name='api-market-history'),

    # ── Screener ──────────────────────────────────────────────────
    path('screener', extra_views.ScreenerView.as_view(), name='api-screener'),

    # ── Watchlist ─────────────────────────────────────────────────
    path('watchlist', views.WatchlistView.as_view(), name='api-watchlist'),
    path('watchlist/add', extra_views.WatchlistAddView.as_view(), name='api-watchlist-add'),
    path('watchlist/remove', extra_views.WatchlistRemoveView.as_view(), name='api-watchlist-remove'),

    # ── Portfolio (Manual Positions) ──────────────────────────────
    path('portfolio', views.PortfolioView.as_view(), name='api-portfolio'),
    path('portfolio/positions', portfolio_views.PortfolioPositionsView.as_view(), name='api-portfolio-positions'),
    path('portfolio/open', portfolio_views.PortfolioOpenView.as_view(), name='api-portfolio-open'),
    path('portfolio/close', portfolio_views.PortfolioCloseView.as_view(), name='api-portfolio-close'),
    path('portfolio/delete', portfolio_views.PortfolioDeleteView.as_view(), name='api-portfolio-delete'),
    path('risk/calculate', portfolio_views.RiskCalculateView.as_view(), name='api-risk-calculate'),

    # ── Predictions & Accuracy ────────────────────────────────────
    path('predict', prediction_views.PredictionView.as_view(), name='api-predict'),
    path('predict/history', prediction_views.PredictionHistoryView.as_view(), name='api-predict-history'),
    path('accuracy', prediction_views.PredictionAccuracyView.as_view(), name='api-accuracy'),
    path('model-metrics', prediction_views.ModelMetricsView.as_view(), name='api-model-metrics'),
    path('research/<str:ticker>', prediction_views.ResearchView.as_view(), name='api-research'),
    path('feature-importance/<str:ticker>', prediction_views.FeatureImportanceView.as_view(), name='api-feature-importance'),
    path('track-record', prediction_views.TrackRecordView.as_view(), name='api-track-record'),
    path('pipeline/stats', prediction_views.PipelineStatsView.as_view(), name='api-pipeline-stats'),
    path('ai/analyze/<str:ticker>', prediction_views.AiAnalyzeView.as_view(), name='api-ai-analyze'),

    # ── Notifications ─────────────────────────────────────────────
    path('notifications', extra_views.NotificationsView.as_view(), name='api-notifications'),
    path('notifications/read', extra_views.NotificationsReadView.as_view(), name='api-notifications-read'),
    path('notifications/clear', extra_views.NotificationsClearView.as_view(), name='api-notifications-clear'),
    
    path('notifications/list', tools_views.NotificationsListView.as_view(), name='api-notifications-list'),
    path('notifications/read-new', tools_views.NotificationsReadView.as_view(), name='api-notifications-read-new'),
    path('notifications/clear-all', tools_views.NotificationsClearView.as_view(), name='api-notifications-clear-all'),

    # ── Manual Paper Trading ──────────────────────────────────────
    path('manual-paper/account', extra_views.ManualPaperAccountView.as_view(), name='api-manual-paper-account'),
    path('manual-paper/order', extra_views.ManualPaperOrderView.as_view(), name='api-manual-paper-order'),
    path('manual-paper/cancel', extra_views.ManualPaperCancelView.as_view(), name='api-manual-paper-cancel'),

    # ── Simulated Paper Trading Engine ───────────────────────────
    path('paper/summary', paper_views.PaperSummaryView.as_view(), name='api-paper-summary'),
    path('paper/trades', paper_views.PaperTradesView.as_view(), name='api-paper-trades'),
    path('paper/opt-in', paper_views.PaperOptInView.as_view(), name='api-paper-opt-in'),
    path('paper/opt-out', paper_views.PaperOptOutView.as_view(), name='api-paper-opt-out'),
    path('paper/my-portfolio', paper_views.PaperMyPortfolioView.as_view(), name='api-paper-my-portfolio'),
    path('leaderboard/users', paper_views.TraderLeaderboardView.as_view(), name='api-trader-leaderboard'),

    # ── Scanners ──────────────────────────────────────────────────
    path('scanner/volume', scanner_views.ScannerVolumeView.as_view(), name='api-scanner-volume'),
    path('scanner/squeeze', scanner_views.ScannerSqueezeView.as_view(), name='api-scanner-squeeze'),
    path('scanner/sector', scanner_views.ScannerSectorView.as_view(), name='api-scanner-sector'),

    # ── Macro Intelligence ────────────────────────────────────────
    path('macro/data', macro_views.MacroDataView.as_view(), name='api-macro-data'),
    path('macro/heatmap', macro_views.MacroHeatmapView.as_view(), name='api-macro-heatmap'),
    path('macro/ticker-insights/<str:ticker>', macro_views.MacroTickerInsightsView.as_view(), name='api-macro-ticker-insights'),

    # ── Advanced Trading Tools & Settings ────────────────────────
    path('backtest', tools_views.BacktestView.as_view(), name='api-backtest'),
    path('pipeline/retrain', tools_views.PipelineRetrainView.as_view(), name='api-pipeline-retrain'),
    path('pipeline/config', pipeline_views.PipelineConfigView.as_view(), name='api-pipeline-config'),
    path('pipeline/run', pipeline_views.PipelineRunView.as_view(), name='api-pipeline-run'),
    path('calendar/earnings', tools_views.CalendarEarningsView.as_view(), name='api-calendar-earnings'),
    path('calendar/macro', tools_views.CalendarMacroView.as_view(), name='api-calendar-macro'),
    path('resources', tools_views.ResourcesPublicView.as_view(), name='api-resources'),
    path('digest/send', tools_views.DigestSendView.as_view(), name='api-digest-send'),

    # ── Alert Config Channels ─────────────────────────────────────
    path('alerts', tools_views.AlertsListView.as_view(), name='api-alerts-list'),
    path('alerts/add', tools_views.AlertsAddView.as_view(), name='api-alerts-add'),
    path('alerts/remove', tools_views.AlertsRemoveView.as_view(), name='api-alerts-remove'),
    path('telegram/configure', tools_views.TelegramConfigureView.as_view(), name='api-telegram-configure'),
    path('telegram/status', tools_views.TelegramStatusView.as_view(), name='api-telegram-status'),
    path('telegram/remove', tools_views.TelegramRemoveView.as_view(), name='api-telegram-remove'),
    path('whatsapp/configure', tools_views.WhatsappConfigureView.as_view(), name='api-whatsapp-configure'),
    path('whatsapp/status', tools_views.WhatsappStatusView.as_view(), name='api-whatsapp-status'),
    path('whatsapp/remove', tools_views.WhatsappRemoveView.as_view(), name='api-whatsapp-remove'),
    path('discord/configure', tools_views.DiscordConfigureView.as_view(), name='api-discord-configure'),
    path('discord/status', tools_views.DiscordStatusView.as_view(), name='api-discord-status'),
    path('discord/remove', tools_views.DiscordRemoveView.as_view(), name='api-discord-remove'),
    path('discord/test', tools_views.DiscordTestView.as_view(), name='api-discord-test'),

    # ── Journal ───────────────────────────────────────────────────
    path('journal', extra_views.JournalView.as_view(), name='api-journal'),

    # ── Static Content Pages ──────────────────────────────────────
    path('content/<str:page_id>', extra_views.ContentView.as_view(), name='api-content'),

    # ── Password Reset / Email Verify ─────────────────────────────
    path('forgot-password', extra_views.ForgotPasswordView.as_view(), name='api-forgot-password'),
    path('reset-password', extra_views.ResetPasswordView.as_view(), name='api-reset-password'),
    path('verify-email', extra_views.VerifyEmailView.as_view(), name='api-verify-email'),

    # ── Simulated Payments / Upgrade ──────────────────────────────
    path('stripe/checkout', extra_views.StripeCheckoutView.as_view(), name='api-stripe-checkout'),
    path('mpesa/pay', extra_views.MpesaPayView.as_view(), name='api-mpesa-pay'),

    # ── Live Portfolio Summary ───────────────────────────────────
    path('live/summary', mt5_views.LiveSummaryView.as_view(), name='api-live-summary'),
    path('live/trades', mt5_views.LiveTradesView.as_view(), name='api-live-trades'),
]
