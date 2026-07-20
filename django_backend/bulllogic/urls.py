from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse, HttpResponseRedirect
from users import views as users_views

def api_root(request):
    # If a browser hits the Django root directly, send them to the React app
    accept = request.META.get('HTTP_ACCEPT', '')
    if 'text/html' in accept:
        return HttpResponseRedirect('http://localhost:5000')
    # API clients (Postman, curl, etc.) get a JSON status response
    return JsonResponse({
        'name': 'BullLogic API',
        'status': 'running',
        'version': '2.0',
        'frontend_url': 'http://localhost:5000',
        'docs': '/api/'
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

