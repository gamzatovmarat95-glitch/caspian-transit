"""Numeric future weather for calculations; independent of the Windy iframe."""
import json
import math
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from django.conf import settings
from django.core.cache import cache
from .live_weather import POINTS
from .domain.integrity import digest

SITES = [p for p in POINTS if not p.get('detail')]
FORECAST_URL = 'https://api.open-meteo.com/v1/ecmwf?' + urlencode({
    'latitude': ','.join(str(p['lat']) for p in SITES),
    'longitude': ','.join(str(p['lon']) for p in SITES),
    'hourly': 'wind_speed_10m,wind_gusts_10m',
    'wind_speed_unit': 'ms', 'timeformat': 'unixtime',
    'timezone': 'UTC', 'forecast_days': 7, 'cell_selection': 'nearest',
})


class WeatherUnavailable(ValueError):
    pass


def finite(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def make_profile(points, provider, model, provenance):
    value = dict(provider=provider, model=model, points=points, provenance=provenance)
    value['hash'] = digest(value)
    value['fetchedAt'] = datetime.now(timezone.utc).isoformat()
    return value


def normalize_openmeteo(raw, provenance='server_https'):
    if not isinstance(raw, list) or len(raw) != len(SITES):
        raise ValueError('Неверное число точек прогноза')
    points = []
    for site, row in zip(SITES, raw):
        if not isinstance(row, dict):
            raise ValueError('Неверный формат прогноза')
        units, hourly = row.get('hourly_units', {}), row.get('hourly', {})
        if not isinstance(units, dict) or not isinstance(hourly, dict):
            raise ValueError('Неверная схема прогноза')
        if units.get('wind_speed_10m') != 'm/s' or units.get('wind_gusts_10m') != 'm/s':
            raise ValueError('Прогноз должен быть в м/с')
        times, wind, gust = (hourly.get(k) for k in ('time', 'wind_speed_10m', 'wind_gusts_10m'))
        if not all(isinstance(v, list) for v in (times, wind, gust)) or not 12 <= len(times) <= 400 or len(times) != len(wind) or len(times) != len(gust):
            raise ValueError('Неверная длина прогноза')
        samples, previous = [], 0
        for at, w, g in zip(times, wind, gust):
            if not finite(at, 946684800, 4102444800) or at <= previous:
                raise ValueError('Времена прогноза должны возрастать')
            previous = at
            samples.append(dict(at=at*1000, windMs=w if finite(w, 0, 150) else None, gustMs=g if finite(g, 0, 200) else None))
        points.append(dict(site, samples=samples))
    return make_profile(points, 'Open-Meteo', 'ECMWF IFS', provenance)


def normalize_windy(raw, site):
    if not isinstance(raw, dict):
        raise ValueError('Неверный ответ Windy')
    units = raw.get('units', {})
    if not isinstance(units, dict):
        raise ValueError('Неверные единицы Windy')
    keys = ['wind_u-surface', 'wind_v-surface', 'gust-surface']
    if any(units.get(k) not in ('m*s-1', 'm/s') for k in keys):
        raise ValueError('Неверные единицы Windy')
    times = raw.get('ts')
    arrays = [raw.get(k) for k in keys]
    if not isinstance(times, list) or not 12 <= len(times) <= 400 or not all(isinstance(a, list) and len(a) == len(times) for a in arrays):
        raise ValueError('Неверная длина Windy-прогноза')
    samples, previous = [], 0
    for at, u, v, gust in zip(times, *arrays):
        if not finite(at, 946684800000, 4102444800000) or at <= previous:
            raise ValueError('Неверное время Windy')
        previous = at
        speed = math.hypot(u, v) if finite(u, -150, 150) and finite(v, -150, 150) else None
        samples.append(dict(at=at, windMs=speed if speed is not None and speed <= 150 else None,
                            gustMs=gust if finite(gust, 0, 200) else None))
    return dict(site, samples=samples)


def fetch_profile(source):
    if source not in ('openmeteo', 'windy'):
        raise ValueError('Неизвестный источник прогноза')
    key = settings.WINDY_POINT_API_KEY if source == 'windy' else ''
    if source == 'windy' and not key:
        raise WeatherUnavailable('Для числового прогноза Windy нужен отдельный Point Forecast API key. Виджет сам по себе этих данных приложению не передаёт.')
    cache_key = 'route-forecast-v1-' + source + '-' + digest(key)[:12]
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    lock_key = cache_key+'-fetching'
    if not cache.add(lock_key, True, 60):
        raise WeatherUnavailable('Прогноз уже обновляется. Повторите расчёт через несколько секунд.')
    try:
        if source == 'openmeteo':
            with urlopen(Request(FORECAST_URL, headers={'Accept': 'application/json'}), timeout=7) as reply:
                raw = reply.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError('Слишком большой ответ')
            profile = normalize_openmeteo(json.loads(raw))
        else:
            points = []
            for site in SITES:
                payload = dict(lat=site['lat'], lon=site['lon'], model='gfs', parameters=['wind', 'windGust'], levels=['surface'], key=key)
                request = Request('https://api.windy.com/api/point-forecast/v2', data=json.dumps(payload).encode(),
                                  headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
                with urlopen(request, timeout=6) as reply:
                    raw = reply.read(500_001)
                if len(raw) > 500_000:
                    raise ValueError('Слишком большой ответ Windy')
                points.append(normalize_windy(json.loads(raw), site))
            profile = make_profile(points, 'Windy Point Forecast', 'GFS', 'server_https')
    except (OSError, ValueError, KeyError, TypeError):
        cache.delete(lock_key)
        # Neither the request body nor exception strings containing credentials are exposed.
        raise WeatherUnavailable('Не удалось получить числовой прогноз выбранного поставщика. Расчёт без прогноза не выдаётся за погодную рекомендацию.') from None
    cache.set(cache_key, profile, 900)
    cache.delete(lock_key)
    return profile


def public_config():
    return dict(forecastUrl=FORECAST_URL, windyPointConfigured=bool(settings.WINDY_POINT_API_KEY))
