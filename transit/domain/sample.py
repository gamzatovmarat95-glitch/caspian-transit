"""Deterministic educational RU–IR network. No real shipping data is claimed."""
from pathlib import Path
from datetime import datetime, timezone
import json
import math
import time
HOUR = 3600000
PORTS = [
    'olya',
    'makhachkala',
    'anzali',
    'amirabad',
]
DATA = Path(__file__).resolve().parents[1] / 'data'


def iso(at):
    return datetime.fromtimestamp(at / 1000, timezone.utc).isoformat(timespec='milliseconds').replace(
        '+00:00',
        'Z',
    )


def milliseconds(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000


def random(seed):
    n = seed & 4294967295

    def next_value():
        nonlocal n
        n = 1664525 * n + 1013904223 & 4294967295
        return n / 4294967296
    return next_value


def generate_history(base_time):
    rng = random(42126)
    rows = []
    for i in range(200):
        for p, port in enumerate(PORTS):
            queue = math.floor(rng() * 24)
            wind = 2 + rng() * 19
            handling = 2 + rng() * 4
            noise = (rng() + rng() + rng() - 1.5) * 2.5
            rows.append(
                dict(
                    at=iso(base_time - (201 - i) * 6 * HOUR),
                    portId=port,
                    queueUnits=queue,
                    windMs=wind,
                    handlingHours=handling,
                    delayHours=max(
                        0,
                        0.42 * queue + 0.045 * max(0, wind - 7) ** 2 + 0.32 * handling + p * 0.38 + noise,
                    ),
                ),
            )
    return rows


def seed_workspace(base_time=None):
    if base_time is None:
        base_time = math.floor(time.time() * 1000 / HOUR) * HOUR
    routes = json.loads((DATA / 'routes.json').read_text(encoding='utf-8'))
    names = [
        'Керамическая плитка',
        'Текстиль и фурнитура',
        'Полимерное сырьё',
        'Упаковочные материалы',
        'Бытовая техника',
        'Санитарная керамика',
        'Мебельная фурнитура',
        'Бумага и картон',
    ]
    masses = [
        22,
        16,
        20,
        18,
        21,
        23,
        17,
        19,
    ]
    cargo, packs = ([], {})
    for i, name in enumerate(names):
        cid = f'CSP-{1042 + i}'
        cargo.append(
            dict(
                id=cid,
                name=name,
                customer=f'Демо-грузовладелец {i + 1:02}',
                massTon=masses[i],
                readyAt=base_time + i % 3 * 3 * HOUR,
                dueAt=base_time + (76 + i * 5) * HOUR,
                plannedRoute=routes[i % 3]['id'],
                priority='Высокий' if i < 3 else 'Обычный',
                documentReadyAt=base_time + (34 if i == 2 else 4) * HOUR,
            ),
        )
        packs[cid] = dict(
            invoice=f'INV-DEMO-{1042 + i}',
            packingList='' if i in (0, 2) else f'PL-DEMO-{1042 + i}',
            hsCode='6907210000',
            consignee='Demo consignee / учебная партия',
            massTon=masses[i],
            reference=f'DEMO-{1042 + i}',
            status='draft',
        )
    specs = [
        ('olya', 'Оля', 'Россия', 45.79, 47.55, 12, 14, 3),
        ('makhachkala', 'Махачкала', 'Россия', 42.98, 47.51, 3, 9, 3),
        ('anzali', 'Энзели', 'Иран', 37.47, 49.47, 4, 7, 3),
        ('amirabad', 'Амирабад', 'Иран', 36.85, 53.37, 3, 6, 2.5),
    ]
    ports = [dict(
        id=p,
        name=n,
        country=c,
        lat=lat,
        lon=lon,
        queueUnits=q,
        windMs=w,
        handlingHours=h,
        closureStart=base_time + 20 * HOUR if p == 'olya' else None,
        closureEnd=base_time + 35 * HOUR if p == 'olya' else None,
    ) for p, n, c, lat, lon, q, w, h in specs]
    return dict(
        baseTime=base_time,
        routes=routes,
        cargo=cargo,
        packs=packs,
        ports=ports,
        allocations={},
        audit=[],
        history=generate_history(base_time),
        historyOrigin='synthetic',
        idempotency={},
        scenario='Штормовое окно в Оле',
    )
