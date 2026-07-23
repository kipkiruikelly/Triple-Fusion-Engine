import os
from pathlib import Path
from django.contrib import admin
from django.urls import path, include, re_path
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.views.generic import TemplateView
from users import views as users_views

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR.parent / 'frontend' / 'dist'

def serve_react_spa(request, path=''):
    """Serves index.html for all React frontend SPA client routes."""
    index_file = FRONTEND_DIST / 'index.html'
    if index_file.exists():
        with open(index_file, 'r', encoding='utf-8') as f:
            return HttpResponse(f.read(), content_type='text/html')
    
    # Fallback when dist is not built yet (dev mode API root response)
    accept = request.META.get('HTTP_ACCEPT', '')
    if 'text/html' in accept and os.getenv('DEBUG') == 'True':
        return HttpResponseRedirect('http://localhost:5000')

    return JsonResponse({
        'name': 'BullLogic API (Django)',
        'status': 'running',
        'version': '2.0',
        'docs': '/api/'
    })

urlpatterns = [
    # ── Admin & API Endpoints ─────────────────────────────────────
    path('admin/api/', include('trading.admin_urls')),
    path('admin/', admin.site.urls),
    path('api/', include('users.urls')),
    path('api/', include('trading.urls')),
    path('mt5/', include('trading.mt5_urls')),
    
    # ── Google OAuth 2.0 ─────────────────────────────────────────
    path('auth/google', users_views.GoogleLoginView.as_view(), name='google-login'),
    path('auth/google/callback', users_views.GoogleCallbackView.as_view(), name='google-callback'),

    # ── React SPA Catch-All Fallback Route ────────────────────────
    re_path(r'^(?P<path>.*)$', serve_react_spa),
]
