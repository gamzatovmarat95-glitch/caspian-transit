"""Exhaustive discrete scheduling over configured corridors and departures."""
import bisect
import copy
import math
from datetime import datetime, timezone
from .engine import find, number, rounded, EMISSION_FACTORS
from .sample import HOUR
from .integrity import digest
from .corridors import sea_corridor, VERSION as GEOMETRY_VERSION

VERSION = 'discrete-corridor-optimizer-3'


def scenario_wind_reason(route, ports, wind_limit):
    for port_id in (route['from'], route['to']):
        port = find(ports, port_id)
        if port['windMs'] > wind_limit:
            return f"Сценарный ветер в узле {port['name']}: {port['windMs']:g} м/с выше заданного предела {wind_limit:g} м/с"
    return None


def distance(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2-lat1, math.radians(b[1]-a[1])
    return 6371*2*math.asin(min(1, math.sqrt(math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2)))


def sea_geometry(route, ports):
    overview = sea_corridor(route)
    if overview:
        return overview
    origin, destination = find(ports, route['from']), find(ports, route['to'])
    points = route['geometry']
    start = min(range(len(points)), key=lambda i: distance(points[i], (origin['lat'], origin['lon'])))
    end = min(range(start+1, len(points)), key=lambda i: distance(points[i], (destination['lat'], destination['lon'])))
    return points[start:end+1]


def position(points, fraction):
    lengths = [distance(a, b) for a, b in zip(points, points[1:])]
    remaining = sum(lengths)*fraction
    for i, length in enumerate(lengths):
        if remaining <= length:
            f = remaining/length if length else 0
            return [points[i][j]+(points[i+1][j]-points[i][j])*f for j in (0, 1)]
        remaining -= length
    return points[-1]


def at_time(point, at):
    samples = point['samples']
    times = [s['at'] for s in samples]
    index = bisect.bisect_left(times, at)
    if index < len(samples) and times[index] == at:
        values = [samples[index]]
    elif 0 < index < len(samples) and times[index]-times[index-1] <= 6*HOUR:
        # Conservative bounds between forecast steps; no smoothed-away gust peak.
        values = samples[index-1:index+1]
    else:
        return None
    if any(v.get('windMs') is None or v.get('gustMs') is None for v in values):
        return None
    return max(v['windMs'] for v in values), max(v['gustMs'] for v in values)


def weather_check(route, ports, departure, profile, wind_limit, gust_limit):
    path = sea_geometry(route, ports)
    peak_wind = peak_gust = 0
    evidence = []
    count = max(1, math.ceil(route['seaHours']))
    for step in range(count+1):
        fraction = step/count
        at = departure + route['seaHours']*fraction*HOUR
        location = position(path, fraction)
        point = min(profile['points'], key=lambda p: distance(location, (p['lat'], p['lon'])))
        value = at_time(point, at)
        if value is None:
            return dict(known=False, allowed=False, reason='Нет прогноза для всего морского этапа', samples=evidence)
        wind, gust = value
        peak_wind, peak_gust = max(peak_wind, wind), max(peak_gust, gust)
        evidence.append(dict(at=at, pointId=point['id'], windMs=wind, gustMs=gust))
    allowed = peak_wind <= wind_limit and peak_gust <= gust_limit
    return dict(known=True, allowed=allowed, peakWindMs=peak_wind, peakGustMs=peak_gust,
                reason='' if allowed else 'Превышен заданный предел ветра или порывов', samples=evidence)


def choose(candidates, objective, due_at):
    if not candidates:
        return None
    timely = [c for c in candidates if c['arrival'] <= due_at]
    if timely:
        pool = timely
    else:
        late = min(c['lateHours'] for c in candidates)
        pool = [c for c in candidates if abs(c['lateHours']-late) < 1e-8]
    keys = {'time': ('arrival', 'costRub', 'co2Kg'), 'cost': ('costRub', 'arrival', 'co2Kg'), 'carbon': ('co2Kg', 'arrival', 'costRub')}
    return min(pool, key=lambda c: tuple(c[k] for k in keys[objective]) + (c['routeId'], c['departure']))


def optimize(state, version, cargo_id, profile, objective='time', wind_limit=15, gust_limit=22, planning_at=None):
    if objective not in ('time', 'cost', 'carbon'):
        raise ValueError('Неизвестный критерий')
    for value in (wind_limit, gust_limit):
        if type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 60:
            raise ValueError('Пределы ветра должны быть от 1 до 60 м/с')
    if gust_limit < wind_limit:
        raise ValueError('Предел порывов не может быть меньше предела среднего ветра')
    cargo = find(state['cargo'], cargo_id)
    if not cargo:
        raise ValueError('Партия не найдена')
    if not profile.get('points'):
        raise ValueError('Нет числового прогноза')
    now = planning_at if planning_at is not None else math.floor(datetime.now(timezone.utc).timestamp()/300)*300000
    inputs = dict(baseTime=state['baseTime'], cargo=copy.deepcopy(cargo), routes=copy.deepcopy(state['routes']),
                  ports=copy.deepcopy(state['ports']), allocations=copy.deepcopy(state['allocations']),
                  version=version, planningAt=now, objective=objective, windLimit=wind_limit, gustLimit=gust_limit)
    for route in inputs['routes']:
        route['seaGeometry'] = sea_geometry(route, state['ports'])
    inputs['geometryVersion'] = GEOMETRY_VERSION
    obs = cargo.get('progress', {})
    candidates, rejected = [], []
    for route in state['routes']:
        origin, destination = find(state['ports'], route['from']), find(state['ports'], route['to'])
        if obs.get('stage') in ('sea', 'destination_port', 'delivered'):
            rejected.append(dict(routeId=route['id'], code='movement_locked', reason='После погрузки автоматическая смена коридора не выполняется'))
            continue
        observed = find(state['routes'], obs.get('routeId')) if obs else None
        if obs.get('stage') == 'origin_port' and observed and observed['from'] != route['from']:
            rejected.append(dict(routeId=route['id'], code='origin_locked', reason='Партия уже находится в другом порту; трансфер не задан'))
            continue
        physical = max(now, obs['actualPortArrival']) if obs.get('stage') == 'origin_port' and 'actualPortArrival' in obs else max(now, cargo['readyAt']) + (route['inlandHours'] + obs.get('delayHours', 0))*HOUR
        if obs and observed and observed['from'] != route['from']:
            physical = max(now,cargo['readyAt'],obs.get('modelAt',0)) + route['inlandHours']*HOUR
        origin_queue = origin['queueUnits']*origin['handlingHours']/max(1, origin.get('serviceLanes', 1))
        destination_queue = destination['queueUnits']*destination['handlingHours']/max(1, destination.get('serviceLanes', 1))
        processed = physical + (origin_queue + origin['handlingHours'])*HOUR
        available = max(processed, cargo['documentReadyAt'], obs.get('modelAt',0))
        for index in range(8):
            departure = state['baseTime']+(route['firstDeparture']+index*route['frequencyHours'])*HOUR
            common = dict(routeId=route['id'], departure=departure)
            reason = code = None
            key = route['id']+':'+number(departure)
            capacity = route['capacity']-state['allocations'].get(key, 0)+int(cargo.get('acceptedSlot') == key)
            if departure-route['cutoffHours']*HOUR < available:
                reason, code = 'Подвоз, очередь или документы не успевают к cutoff', 'cutoff'
            elif origin['closureStart'] is not None and origin['closureStart'] <= departure < origin['closureEnd']:
                reason, code = 'Отправление попадает в заданное сценарное закрытие порта', 'scenario_closure'
            elif capacity < 1:
                reason, code = 'Нет условной вместимости отправления', 'capacity'
            elif scenario_wind_reason(route, state['ports'], wind_limit):
                reason, code = scenario_wind_reason(route, state['ports'], wind_limit), 'scenario_wind'
            if reason:
                rejected.append(dict(common, reason=reason, code=code))
                continue
            weather = weather_check(route, state['ports'], departure, profile, wind_limit, gust_limit)
            if not weather['allowed']:
                rejected.append(dict(common, reason=weather['reason'], code='weather_limit' if weather['known'] else 'weather_unknown', weather=weather))
                continue
            sea_arrival = departure+route['seaHours']*HOUR
            if destination['closureStart'] is not None and destination['closureStart'] <= sea_arrival < destination['closureEnd']:
                sea_arrival = destination['closureEnd']
            arrival = sea_arrival+(destination_queue+destination['handlingHours']+route['finalHours'])*HOUR
            cost = route['costRub']*cargo['massTon']/20+max(0, (departure-processed)/HOUR)*200
            carbon = cargo['massTon']*(route['inlandKm']*EMISSION_FACTORS[route['inlandMode']]+route['seaKm']*EMISSION_FACTORS['sea']+route['finalKm']*EMISSION_FACTORS['road'])
            candidates.append(dict(common, routeName=route['name'], arrival=arrival, lateHours=max(0,(arrival-cargo['dueAt'])/HOUR),
                                   costRub=rounded(cost), co2Kg=rounded(carbon), weather=weather, capacityLeft=capacity,
                                   queueHours=origin_queue+destination_queue, slotKey=key))
    best = choose(candidates, objective, cargo['dueAt'])
    routes = []
    for route in state['routes']:
        selected = choose([c for c in candidates if c['routeId'] == route['id']], objective, cargo['dueAt'])
        routes.append(dict(id=route['id'], name=route['name'], best=selected,
                           rejected=[r for r in rejected if r['routeId'] == route['id']]))
    return dict(status='recommended' if best else 'no_supported_option', algorithm=VERSION,
                createdAt=datetime.now(timezone.utc).isoformat(), planningAt=now, cargoId=cargo_id, version=version,
                objective=objective, best=best, routes=routes, evaluated=len(candidates)+len(rejected), feasible=len(candidates),
                inputHash=digest(inputs), weatherHash=profile['hash'], inputs=inputs, weatherProfile=profile,
                executionReady=state['packs'][cargo_id]['status']=='validated' and state.get('clearances',{}).get(cargo_id,{}).get('status')=='ready_demo',
                limitations=[
                    'Точный перебор только трёх заданных коридоров и восьми отправлений каждого; не поиск по всем дорогам/морским путям.',
                    'Сначала варианты в срок; если их нет — минимальное опоздание, затем выбранный критерий и стабильное правило равенства.',
                    'Очередь: число условных партий × время обработки / число линий, по умолчанию одна линия. Расписания, очереди и тарифы учебные.',
                    'Погода проверяется по ближайшим точкам вдоль условной линии каждый час морского этапа. Это не навигационная оценка безопасности.',
                    'Пределы ветра задаёт пользователь; они не являются официальными ограничениями порта или характеристиками конкретного судна.',
                    'Сценарный ветер в узлах проверяется дополнительно к внешнему прогнозу и считается условием всего горизонта; он не заменяет фактическую погоду.',
                    'Волнение, глубины, осадка и характеристики конкретного судна не моделируются; это планирование логистического коридора, не судовождение.',
                    'Номинальный ETA не является гарантией. ML не выбирает вариант; точность зависит от входных данных.',
                    'Рекомендация не бронирует рейс и не выдаёт таможенный выпуск.',
                ])
