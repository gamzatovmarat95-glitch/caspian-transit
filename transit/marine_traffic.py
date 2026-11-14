"""Optional documented MarineTraffic custom-area API; credentials stay server-side."""
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from django.conf import settings
from django.core.cache import cache
from .domain.integrity import digest

DOCS = 'https://servicedocs.marinetraffic.com/tag/AIS-API/'
MAP_URL = 'https://www.marinetraffic.com/en/ais/home/centerx:51.2/centery:41.4/zoom:7'


def normalize(raw):
    from .vessels import normalize as normalize_geojson
    if not isinstance(raw, dict) or not isinstance(raw.get('DATA'), list) or len(raw['DATA']) > 5000:
        raise ValueError('Неверная схема MarineTraffic')
    def number(value):
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (ValueError, TypeError):
            return None
    features = []
    for row in raw['DATA']:
        if not isinstance(row, dict):
            continue
        speed = number(row.get('SPEED'))
        # MarineTraffic SPEED is knots x10; COURSE is degrees, not tenths.
        features.append(dict(type='Feature', geometry=dict(type='Point', coordinates=[number(row.get('LON')), number(row.get('LAT'))]),
            properties=dict(mmsi=row.get('MMSI'), name=row.get('SHIPNAME'), seen=row.get('TIMESTAMP'),
                sog=speed/10 if speed is not None else None, heading=number(row.get('HEADING')), cog=number(row.get('COURSE')))))
    return normalize_geojson(dict(type='FeatureCollection', features=features))


def snapshot():
    at = datetime.now(timezone.utc).isoformat()
    common = dict(provider='marinetraffic', source=DOCS, fetchedAt=at, browserFallbackAllowed=False,
                  attribution={'provider': 'MarineTraffic / Kpler'}, vessels=[], mapUrl=MAP_URL)
    key = settings.MARINETRAFFIC_API_KEY
    if not key:
        return dict(common, status='not_configured', message='Для MarineTraffic нужен ключ активной API-услуги Vessel Positions in an Area of Interest. Ссылка на веб-карту ключ не заменяет.')
    if not re.fullmatch(r'[0-9a-fA-F]{40}', key):
        return dict(common, status='not_configured', message='Формат ключа не подходит для документированной MarineTraffic custom-area API. Проверьте услугу и её документацию.')
    cache_key = 'caspian-marine-traffic-' + digest(key)[:20]
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    lock_key = cache_key + '-fetching'
    if not cache.add(lock_key, True, 30):
        return dict(common, status='loading', message='Обновление MarineTraffic уже выполняется. Повторный платный запрос не отправлен.')
    # The Caspian area must be assigned to this custom-area service by the provider.
    url = 'https://services.marinetraffic.com/api/exportvessels-custom-area/' + key + '?' + urlencode(dict(v=2, timespan=1440, limit=1000, protocol='jsono'))
    try:
        with urlopen(Request(url, headers={'Accept': 'application/json', 'User-Agent': 'CaspianTransit/1.2'}), timeout=8) as reply:
            payload = reply.read(4_000_001)
        if len(payload) > 4_000_000:
            raise ValueError('Слишком большой ответ')
        raw = json.loads(payload)
        rows = normalize(raw)
        # Do not follow paid pagination automatically. Explicitly report incomplete output.
        metadata = raw.get('METADATA', {})
        truncated = len(raw['DATA']) >= 1000 or bool(metadata.get('CURSOR') or metadata.get('NEXT_CURSOR')) if isinstance(metadata, dict) else len(raw['DATA']) >= 1000
        result = dict(common, status='available' if rows else 'no_observations', vessels=rows, truncated=truncated,
                      pollSeconds=settings.MARINETRAFFIC_CACHE_SECONDS, message='Позиции MarineTraffic в разрешённой области; после фильтрации по Каспию')
        ttl = settings.MARINETRAFFIC_CACHE_SECONDS
    except (OSError, ValueError, TypeError, KeyError):
        # Exception strings/URLs can contain the key. Never return or log them.
        result = dict(common, status='unavailable', message='MarineTraffic не вернул данные: проверьте активную API-услугу, назначенную область, квоту и соединение. Ключ остаётся на сервере.')
        ttl = max(120, settings.MARINETRAFFIC_CACHE_SECONDS)
    cache.set(cache_key, result, ttl)
    cache.delete(lock_key)
    return result
