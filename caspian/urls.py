from django.urls import path, re_path
from django.contrib.staticfiles.views import serve
from transit import views
from transit import accounts
from transit import operations
from transit import vessels
from transit import live_weather
from transit import optimization_views
urlpatterns = [
    path('api/optimization', optimization_views.optimization),
    path('api/weather/current', live_weather.current_api),
    path('vessels', vessels.vessel_page),
    path('api/vessels', vessels.vessel_api),
    path('operations', operations.shipments),
    path('accounts/login', accounts.sign_in),
    path('accounts/register', accounts.register),
    path('accounts/logout', accounts.sign_out),
    path('accounts/team', accounts.team),
    path('', views.index),
    path('session/start', views.start_session),
    path('api/health', views.health),
    path('api/workspace', views.workspace_api),
    path('api/map-config', views.map_config),
    path('api/receipt', views.receipt),
    path('api/clearance', views.clearance),
    path('api/gateway', views.gateway),
    path('api/export', views.export),
    path('api/weather', views.weather),
    re_path(
        '^static/(?P<path>.*)$',
        serve,
        {'insecure': True},
    ),
]
