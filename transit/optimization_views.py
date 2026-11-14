from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
import math
import uuid
from .domain.optimizer import optimize
from .route_weather import fetch_profile, normalize_openmeteo, WeatherUnavailable
from .store import read_workspace
from .accounts import can_write
from .domain.integrity import sign


@require_http_methods(['GET', 'POST'])
def optimization(request):
    from .views import owner, denied, response, parse_json
    workspace = owner(request)
    if not workspace:
        return denied()
    try:
        data = parse_json(request, 1_000_000) if request.method == 'POST' else request.GET
        if not hasattr(data, 'get'):
            raise ValueError('Неверный запрос')
        wind_limit, gust_limit = float(data.get('windLimit', 15)), float(data.get('gustLimit', 22))
        if data.get('objective', 'time') not in ('time','cost','carbon') or not all(math.isfinite(v) and 1 <= v <= 60 for v in (wind_limit,gust_limit)) or gust_limit < wind_limit:
            raise ValueError('Проверьте критерий и пределы ветра: от 1 до 60 м/с, порывы не ниже среднего ветра')
        if request.method == 'POST':
            if request.headers.get('X-Caspian-Request') != 'optimization' or request.headers.get('Origin') != request.scheme+'://'+request.get_host():
                return response({'error': 'Недопустимый источник запроса'}, 403)
            if not isinstance(data, dict) or data.get('source', 'openmeteo') != 'openmeteo':
                raise ValueError('Браузерный прогноз поддерживается только для явно указанного Open-Meteo')
            profile = normalize_openmeteo(data.get('forecast'), 'browser_provided_not_server_verified')
        else:
            profile = fetch_profile(data.get('source', 'openmeteo'))
        state, version = read_workspace(workspace)
        report = optimize(state, version, data.get('cargo', ''), profile,
                          data.get('objective', 'time'), wind_limit, gust_limit)
        report['weatherSignature'] = sign(profile, settings.GATEWAY_SECRET)
        report['canAccept'] = can_write(request)
        report['acceptanceKey'] = str(uuid.uuid4())
        report['html'] = render_to_string('transit/optimization-report.html', {'report': report})
        return response(report)
    except WeatherUnavailable as exc:
        return response({'status': 'weather_unavailable', 'error': str(exc), 'source': request.GET.get('source', 'openmeteo')}, 503)
    except (ValueError, TypeError) as exc:
        return response({'status': 'invalid_input', 'error': str(exc)}, getattr(exc, 'status', 400))
