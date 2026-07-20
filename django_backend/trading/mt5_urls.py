from django.urls import path
from . import mt5_views

urlpatterns = [
    path('status', mt5_views.MT5StatusView.as_view(), name='mt5-status'),
    path('connect', mt5_views.MT5ConnectView.as_view(), name='mt5-connect'),
    path('disconnect', mt5_views.MT5DisconnectView.as_view(), name='mt5-disconnect'),
    path('start', mt5_views.MT5StartView.as_view(), name='mt5-start'),
    path('stop', mt5_views.MT5StopView.as_view(), name='mt5-stop'),
    path('close_all', mt5_views.MT5CloseAllView.as_view(), name='mt5-close_all'),
]
