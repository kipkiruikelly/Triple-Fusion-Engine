from django.urls import path
from . import admin_views

urlpatterns = [
    path('overview', admin_views.AdminOverviewView.as_view(), name='admin-api-overview'),
    path('dashboard/', admin_views.AdminDashboardHtmlView.as_view(), name='admin-dashboard'),
    path('users/', admin_views.AdminUsersHtmlView.as_view(), name='admin-users'),
    path('users/<int:user_id>/toggle-status/', admin_views.AdminUserToggleStatusView.as_view(), name='admin-user-toggle-status'),
    path('users/<int:user_id>/update-plan/', admin_views.AdminUserUpdatePlanView.as_view(), name='admin-user-update-plan'),
    
    # JSON APIs for React frontend
    path('users/list', admin_views.AdminUsersApiView.as_view(), name='admin-api-users-list'),
    path('users/<int:user_id>/toggle-status/json', admin_views.AdminUserToggleStatusApiView.as_view(), name='admin-api-user-toggle-status-json'),
    path('users/<int:user_id>/update-plan/json', admin_views.AdminUserUpdatePlanApiView.as_view(), name='admin-api-user-update-plan-json'),
    path('users/<int:user_id>/update-role/json', admin_views.AdminUserUpdateRoleApiView.as_view(), name='admin-api-user-update-role-json'),
    path('payments/list', admin_views.AdminPaymentsApiView.as_view(), name='admin-api-payments-list'),
    path('broadcasts/list', admin_views.AdminBroadcastsApiView.as_view(), name='admin-api-broadcasts-list'),
    path('broadcasts/create', admin_views.AdminBroadcastsApiView.as_view(), name='admin-api-broadcasts-create'),
    path('gift-codes/list', admin_views.AdminGiftCodesApiView.as_view(), name='admin-api-gift-codes-list'),
    path('gift-codes/generate', admin_views.AdminGiftCodesApiView.as_view(), name='admin-api-gift-codes-generate'),
    path('pillars/data', admin_views.AdminPillarsDataView.as_view(), name='admin-api-pillars-data'),
    path('pillars/action', admin_views.AdminPillarsActionView.as_view(), name='admin-api-pillars-action'),
]

