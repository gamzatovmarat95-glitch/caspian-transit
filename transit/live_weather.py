"""Current model weather over ports and the sea; never substitutes archived data."""
import json
import math
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from django.core.cache import cache
from django.views.decorators.http import require_GET

POINTS = [
    dict(id='olya', name='Оля', lat=45.79, lon=47.55, kind='port'),
    dict(id='makhachkala', name='Махачкала', lat=42.98, lon=47.51, kind='port'),
    dict(id='anzali', name='Энзели', lat=37.47, lon=49.47, kind='port'),
    dict(id='amirabad', name='Амирабад', lat=36.85, lon=53.37, kind='port'),
    dict(id='north-sea', name='Северный Каспий', lat=44.7, lon=49.0, kind='sea'),
    dict(id='middle-sea', name='Средний Каспий', lat=41.3, lon=50.3, kind='sea'),
    dict(id='south-sea', name='Южный Каспий', lat=38.3, lon=51.3, kind='sea'),
    dict(id='north-west', name='Северо-запад моря', lat=44.3, lon=48.2, kind='sea', detail=True),
    dict(id='north-east', name='Северо-восток моря', lat=44.3, lon=50.7, kind='sea', detail=True),
    dict(id='west-sea', name='Запад моря', lat=42.8, lon=48.7, kind='sea', detail=True),
    dict(id='east-sea', name='Восток моря', lat=42.8, lon=51.6, kind='sea', detail=True),
    dict(id='middle-west', name='Центральный запад', lat=40.5, lon=50.0, kind='sea', detail=True),
    dict(id='middle-east', name='Центральный восток', lat=40.5, lon=52.0, kind='sea', detail=True),
    dict(id='south-west', name='Юго-запад моря', lat=38.8, lon=49.8, kind='sea', detail=True),
    dict(id='south-east', name='Юго-восток моря', lat=38.8, lon=52.4, kind='sea', detail=True),
    dict(id='south-coast', name='Южное побережье', lat=37.4, lon=51.5, kind='sea', detail=True),
]
SOURCE = 'https://open-meteo.com/en/docs'
CURRENT_POINTS = [p for p in POINTS if not p.get('detail')]
URL = 'https://api.open-meteo.com/v1/forecast?' + urlencode(dict(
    latitude=','.join(str(p['lat']) for p in CURRENT_POINTS),
    longitude=','.join(str(p['lon']) for p in CURRENT_POINTS),
    current='temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code',
    wind_speed_unit='ms', timeformat='unixtime', timezone='UTC', forecast_days=1, cell_selection='nearest',
))


def normalize(data):
    if not isinstance(data, list) or len(data) != len(CURRENT_POINTS):
        raise ValueError('Неверное число погодных точек')
    rows = []
    for point, item in zip(CURRENT_POINTS, data):
        if not isinstance(item, dict):
            continue
        current, units = item.get('current', {}), item.get('current_units', {})
        if not isinstance(current, dict) or not isinstance(units, dict) or units.get('wind_speed_10m') != 'm/s' or units.get('wind_gusts_10m') != 'm/s':
            continue
        def numeric(key, low, high):
            value = current.get(key)
            return value if type(value) in (int, float) and math.isfinite(value) and low <= value <= high else None
        at = numeric('time', 946684800, 4102444800)
        wind = numeric('wind_speed_10m', 0, 150)
        if at is None or wind is None:
            continue
        age = datetime.now(timezone.utc).timestamp() - at
        rows.append(dict(point, at=at*1000, windMs=wind, gustMs=numeric('wind_gusts_10m', 0, 200),
                         directionDeg=numeric('wind_direction_10m', 0, 360), temperatureC=numeric('temperature_2m', -100, 100),
                         weatherCode=numeric('weather_code', 0, 99), stale=age > 3*3600 or age < -1800))
    if not rows:
        raise ValueError('Нет достоверных погодных значений')
    return rows


def fetch_current():
    cached = cache.get('caspian-current-weather-v3')
    if cached is not None:
        return cached
    at = datetime.now(timezone.utc).isoformat()
    try:
        request = Request(URL, headers={'Accept': 'application/json', 'User-Agent': 'CaspianTransit/1.1.1'})
        with urlopen(request, timeout=6) as reply:
            raw = reply.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('Слишком большой ответ')
        rows = normalize(json.loads(raw))
        result = dict(status='available' if all(not p['stale'] for p in rows) else 'stale', points=rows, fetchedAt=at,
                      source=SOURCE, attribution='Weather data by Open-Meteo.com, CC BY 4.0',
                      message='Текущая модель погоды; не измерение портовой метеостанции')
        ttl = 300
    except (OSError, ValueError, TypeError, KeyError):
        result = dict(status='unavailable', points=[], fetchedAt=at, source=SOURCE,
                      attribution='Weather data by Open-Meteo.com, CC BY 4.0',
                      message='Не удалось получить текущую погоду. Архивный прогноз не подставляется.')
        ttl = 30
    cache.set('caspian-current-weather-v3', result, ttl)
    return result


def browser_config(*, ais_enabled=False):
    from .vessels import URL as AIS_URL
    from django.conf import settings
    return dict(weatherUrl=URL, weatherPoints=CURRENT_POINTS, aisUrl=AIS_URL,
                marineTrafficConfigured=bool(settings.MARINETRAFFIC_API_KEY), windOverlayEnabled=False,
                shipOverlayEnabled=False, aisEnabled=ais_enabled)


@require_GET
def current_api(request):
    from .views import owner, denied, response
    if not owner(request):
        return denied()
    data = fetch_current()
    return response(data, 503 if data['status'] == 'unavailable' else 200)
