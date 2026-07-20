from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from users import views as users_views

def api_root(request):
    return JsonResponse({
        'name': 'BullLogic API',
        'status': 'running',
        'frontend_url': 'http://localhost:5173'
    })

urlpatterns = [
    path('', api_root),
    path('admin/api/', include('trading.admin_urls')),
    path('admin/', admin.site.urls),
    path('api/', include('users.urls')),
    path('api/', include('trading.urls')),
    path('mt5/', include('trading.mt5_urls')),
    
    # Google OAuth 2.0 routes
    path('auth/google', users_views.GoogleLoginView.as_view(), name='google-login'),
    path('auth/google/callback', users_views.GoogleCallbackView.as_view(), name='google-callback'),
]

