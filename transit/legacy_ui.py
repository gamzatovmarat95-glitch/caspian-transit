"""Presentation values for the original interface; domain decisions stay in domain/."""
import math
from .domain.engine import find
from .domain.sample import HOUR
from .domain.tracking import EVENT_LABELS


def legacy_context(s, cargo, base, chosen, rows, events):
    progress = cargo.get('progress') or {}
    stage = progress.get('stage', 'planned')
    pre_origin = stage in ['planned', 'inland']
    pre_sea = stage in ['planned', 'inland', 'origin_port']
    current = max(cargo['readyAt'], progress.get('modelAt', cargo['readyAt']))
    current = (current - s['baseTime']) / HOUR
    departure = (base['departure'] - s['baseTime']) / HOUR if base['departure'] is not None else math.inf
    arrival = (base['arrival'] - s['baseTime']) / HOUR if base['arrival'] is not None else math.inf
    route = find(s['routes'], base['routeId'])
    destination = find(s['ports'], route['to'])
    sea_leg = next((leg for leg in base['legs'] if leg['mode'] == 'sea'), None)
    sea_arrival = ((sea_leg['end'] if sea_leg else 0) - s['baseTime']) / HOUR
    stale = bool(cargo.get('acceptedSlot') and pre_sea and cargo['acceptedSlot'] != base['slotKey'])
    definitions = [
        ('dispatched', 'Начать подвоз', current, stage != 'planned', {}),
        ('inland_delay', 'Задержать подвоз на 12 ч', current + 1, not pre_origin, {'delayHours': 12}),
        ('origin_arrival', 'Прибытие в порт отправления', max(current + 1, (base['readyAtPort'] - s['baseTime']) / HOUR), not pre_origin, {}),
        ('queue_changed', 'Установить очередь 30', current + .5, not pre_sea, {'queueUnits': 30}),
        ('weather_hold', 'Закрыть окно порта на 18 ч', max(current + .5, departure - 2), not pre_sea, {'holdHours': 18}),
        ('loaded', 'Погрузка и отправление', max(current + 1, departure), stage != 'origin_port' or not cargo.get('acceptedSlot') or stale or s['clearances'].get(cargo['id'], {}).get('status') != 'ready_demo' or not base['feasible'], {}),
        ('sea_arrival', 'Прибытие в порт назначения', max(current + 1, sea_arrival), stage != 'sea', {}),
        ('delivered', 'Подтвердить доставку', max(current + destination['handlingHours'] + route['finalHours'], arrival), stage != 'destination_port', {}),
    ]
    controls = []
    for kind, label, at, disabled, params in definitions:
        finite = math.isfinite(at)
        controls.append(dict(kind=kind, label=label, at=at if finite else 0, time=s['baseTime'] + at * HOUR if finite else None, disabled=disabled or not finite or at > 240, params=params))
    alternatives = []
    for row in rows:
        possible = sorted([f for f in s['forecasts'][row['cargo']['id']] if f['feasible']], key=lambda f: (f['lateHours'], f['costRub'], f['arrival']))
        alternatives.append({**row, 'alternative': possible[0] if possible else None})
    last = events[0] if events else None
    eta_change = None
    if last and last['before']['arrival'] is not None and last['after']['arrival'] is not None:
        eta_change = (last['after']['arrival'] - last['before']['arrival']) / HOUR
    time_change = None
    if base['arrival'] is not None and chosen['arrival'] is not None:
        time_change = abs(base['arrival'] - chosen['arrival']) / HOUR
    legs = [{**leg, 'weight': max(.85, (leg['end'] - leg['start']) / HOUR / 8)} for leg in chosen['legs']]
    total = (legs[-1]['end'] - legs[0]['start']) / HOUR if legs else 0
    return dict(
        display_events=[{**event, 'label': EVENT_LABELS[event['kind']]} for event in events],
        last_event_label=EVENT_LABELS[last['kind']] if last else '',
        event_controls=controls, last_event=last, event_eta_change=eta_change,
        time_change=time_change, cost_change=chosen['costRub'] - base['costRub'],
        display_legs=legs, timeline_total=total, impact_rows=alternatives,
        route_locked=stage in ['sea', 'destination_port', 'delivered'],
        model_coverage=s['model']['intervalCoverage'] * 100,
        source_route=route,
    )
