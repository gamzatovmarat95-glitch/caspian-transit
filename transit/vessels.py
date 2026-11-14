"""Read-only, keyless AIS snapshot. No fictional fallback or ETA inference."""
import json
import math
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import ensure_csrf_cookie

SOURCE = 'https://openwaters.io/api/ais/'
# Entire Caspian, 99.45 square degrees, under the anonymous 100-degree limit.
# Older observations stay visible but are explicitly marked; never extrapolate positions.
URL = 'https://ais.openwaters.io/v1/vessels?bbox=35.8,46.5,47.5,55&max_age=24h&max_age_moving=24h&kind=vessel'
CACHE_KEY = 'caspian-public-ais-v2'


def normalize(data):
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
        raise ValueError('Неверный формат AIS')
    if len(data['features']) > 10000:
        raise ValueError('Слишком большой ответ AIS')
    rows = []
    for feature in data['features']:
        if not isinstance(feature, dict):
            continue
        geometry, props = feature.get('geometry') or {}, feature.get('properties') or {}
        if not isinstance(geometry, dict) or not isinstance(props, dict):
            continue
        coords = geometry.get('coordinates', [])
        if geometry.get('type') != 'Point' or not isinstance(coords, list) or len(coords) < 2:
            continue
        lon, lat = coords[:2]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon)) or not (35.8 <= lat <= 47.5 and 46.5 <= lon <= 55):
            continue
        mmsi = str(props.get('mmsi', feature.get('id', '')))
        if not re.fullmatch(r'\d{9}', mmsi):
            continue
        seen = props.get('seen')
        try:
            observed = datetime.fromisoformat(seen.replace('Z', '+00:00'))
            if observed.tzinfo is None:
                continue
            age = (datetime.now(timezone.utc) - observed).total_seconds()
        except (AttributeError, ValueError, TypeError):
            continue
        if age > 86400 or age < -300:
            continue
        speed = props.get('sog')
        course = props.get('heading')
        if type(course) not in (int, float) or not math.isfinite(course) or not 0 <= course < 360:
            course = props.get('cog')
        rows.append(dict(mmsi=mmsi, name=str(props.get('name') or 'Без названия')[:100], lat=lat, lon=lon, seen=seen,
                         course=course if type(course) in (int, float) and math.isfinite(course) and 0 <= course < 360 else None,
                         speed=speed if type(speed) in (int, float) and math.isfinite(speed) and 0 <= speed <= 102.2 else None,
                         stale=age > 1800 or age < -300, x=round((lon-47)/7*700, 2), y=round((47-lat)/11*700, 2)))
    return rows


def fetch_snapshot():
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    at = datetime.now(timezone.utc).isoformat()
    try:
        request = Request(URL, headers={'Accept': 'application/json', 'User-Agent': 'CaspianTransit/1.1 (educational hackathon)'})
        with urlopen(request, timeout=6) as reply:
            raw = reply.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Слишком большой ответ AIS')
        data = json.loads(raw)
        rows = normalize(data)
        result = dict(status='available' if rows else 'no_observations', fetchedAt=at, vessels=rows,
                      attribution=data.get('attribution', {}) if isinstance(data.get('attribution', {}), dict) else {}, source=SOURCE,
                      truncated=bool(data.get('truncated', False)),
                      message='Наблюдения AIS получены' if rows else 'Источник ответил, но за последние 24 часа нет наблюдений в выбранной области. Это не означает отсутствие судов в море.')
        ttl = 60
    except (OSError, URLError, HTTPError, ValueError, TypeError, KeyError):
        result = dict(status='unavailable', fetchedAt=at, vessels=[], attribution={}, source=SOURCE,
                      message='Источник AIS сейчас недоступен. Позиции не подменяются демонстрационными. Проверьте интернет и повторите позже.')
        ttl = 30
    cache.set(CACHE_KEY, result, ttl)
    return result


@require_GET
def vessel_api(request):
    from .views import owner, denied, response
    if not owner(request):
        return denied()
    if request.GET.get('provider') == 'marinetraffic':
        from .marine_traffic import snapshot as marine_snapshot
        return response(marine_snapshot())
    data = fetch_snapshot()
    data = dict(data, provider='openwaters', browserFallbackAllowed=True)
    return response(data, 503 if data['status'] == 'unavailable' else 200)


@require_GET
@ensure_csrf_cookie
def vessel_page(request):
    from .views import owner
    if not owner(request):
        return redirect('/accounts/login')
    from .store import read_workspace
    from .presentation import context_for
    state, version = read_workspace(owner(request))
    context = context_for(request, state, version, 'overview')
    context['full_vessels'] = True
    from .live_weather import browser_config
    context['live_config'] = browser_config(ais_enabled=True)
    response = render(request, 'transit/vessels-map.html', context)
    response['Cache-Control'] = 'no-store'
    return response
