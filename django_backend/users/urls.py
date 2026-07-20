from django.urls import path
from . import views

urlpatterns = [
    path('login', views.LoginView.as_view(), name='api-login'),
    path('register', views.RegisterView.as_view(), name='api-register'),
    path('logout', views.LogoutView.as_view(), name='api-logout'),
    path('me', views.MeView.as_view(), name='api-me'),
    path('csrf', views.CsrfView.as_view(), name='api-csrf'),
    path('settings', views.SettingsView.as_view(), name='api-settings'),
    path('profile', views.ProfileView.as_view(), name='api-profile'),
    path('profile/change-password', views.ChangePasswordView.as_view(), name='api-change-password'),
    
    # User Preferences
    path('preferences', views.PreferencesView.as_view(), name='api-preferences'),
    
    # 2FA
    path('2fa/setup', views.TwoFactorSetupView.as_view(), name='api-2fa-setup'),
    path('2fa/enable', views.TwoFactorEnableView.as_view(), name='api-2fa-enable'),
    path('2fa/disable', views.TwoFactorDisableView.as_view(), name='api-2fa-disable'),
    path('2fa/status', views.TwoFactorStatusView.as_view(), name='api-2fa-status'),
    
    # API Keys
    path('keys', views.ApiKeysListView.as_view(), name='api-keys-list'),
    path('keys/create', views.ApiKeysCreateView.as_view(), name='api-keys-create'),
    path('keys/delete', views.ApiKeysDeleteView.as_view(), name='api-keys-delete'),
    
    # Webhooks
    path('webhooks', views.WebhooksListView.as_view(), name='api-webhooks-list'),
    path('webhooks/add', views.WebhooksAddView.as_view(), name='api-webhooks-add'),
    path('webhooks/delete', views.WebhooksDeleteView.as_view(), name='api-webhooks-delete'),
    path('webhooks/test', views.WebhooksTestView.as_view(), name='api-webhooks-test'),
    
    # Gift Codes
    path('gift/redeem', views.GiftRedeemView.as_view(), name='api-gift-redeem'),
    
    # Gamification
    path('gamification/claim-xp', views.ClaimXpView.as_view(), name='api-gamification-claim-xp'),
    path('gamification/streak-boost', views.StreakBoostView.as_view(), name='api-gamification-streak-boost'),

    # Account actions
    path('account/export', views.AccountExportView.as_view(), name='api-account-export'),
    path('account/delete', views.AccountDeleteView.as_view(), name='api-account-delete'),
]
