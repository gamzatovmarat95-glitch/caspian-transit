import json
import math
import re
from .sample import HOUR, DATA, seed_workspace
from .model import fit_model
EMISSION_FACTORS = {
    'road': 0.09502,
    'rail': 0.0347,
    'sea': 0.01726,
}


def rounded(v):
    return math.floor(v * 100 + 0.5) / 100


def number(v):
    return str(int(v)) if int(v) == v else str(v)


def find(items, key):
    return next((x for x in items if x['id'] == key), None)


def pack_errors(pack, cargo):
    errors = []
    if not pack['invoice'].strip():
        errors.append('Не указан номер инвойса')
    if not pack['packingList'].strip():
        errors.append('Не указан упаковочный лист')
    if not re.fullmatch(
        '\\d{10}',
        pack['hsCode'],
        flags=re.ASCII,
    ):
        errors.append('Код товара должен содержать 10 цифр (проверка формата демо)')
    if not pack['consignee'].strip():
        errors.append('Не указан получатель')
    if (
        not math.isfinite(pack['massTon'])
        or pack['massTon'] <= 0
        or abs(pack['massTon'] - cargo['massTon']) > 0.01
    ):
        errors.append('Масса в документах не совпадает с массой партии')
    if pack['reference'] != f"DEMO-{cargo['id'][4:]}":
        errors.append('Референс не соответствует демонстрационной партии')
    return errors


def forecast(state, cargo, route, model=None):
    mathematical = cargo.get('planningMethod') == 'mathematical'
    if mathematical:
        from .math_planning import QueueRules
        model = QueueRules()
    model = (
        model
        or fit_model(state['history'], state['historyOrigin'])
    )
    origin = find(state['ports'], route['from'])
    destination = find(state['ports'], route['to'])
    delay = model.predict({
        **origin,
        'portId': origin['id'],
    })
    destination_delay = model.predict({
        **destination,
        'portId': destination['id'],
    })
    obs = cargo.get('progress')
    observed_route = find(state['routes'], obs.get('routeId')) if obs else None
    same_origin = bool((
        observed_route
        and observed_route['from'] == route['from']
    ))
    after_loading = bool((
        obs
        and obs['stage'] in [
            'sea',
            'destination_port',
            'delivered',
        ]
    ))
    locked = (
        (
            after_loading
            and obs['routeId'] != route['id']
        )
        or (
            bool(obs)
            and obs['stage'] == 'origin_port'
            and not same_origin
        )
    )
    actual_departure = obs.get('actualDeparture') if (
        after_loading
        and not locked
    ) else None
    actual_sea = obs.get('actualSeaArrival') if (
        after_loading
        and not locked
    ) else None
    actual_delivery = obs.get('actualDeliveredAt') if (
        after_loading
        and not locked
    ) else None
    reasons = []
    physical = obs['actualPortArrival'] if (
        same_origin
        and 'actualPortArrival' in obs
    ) else max(cargo['readyAt'], cargo.get('mathPlanningAt', cargo['readyAt'])) + (route['inlandHours'] + (
        obs
        or {}
    ).get('delayHours', 0)) * HOUR
    if mathematical and same_origin and obs and 'actualPortArrival' in obs:
        physical = max(physical, cargo['mathPlanningAt'])
    if (
        obs
        and not same_origin
        and not after_loading
    ):
        physical = max(cargo['readyAt'], obs['modelAt'], cargo.get('mathPlanningAt',cargo['readyAt'])) + route['inlandHours'] * HOUR
        reasons.append(
            'Альтернативный порт: учебный расчёт полного подвоза заново с момента события; дислокация в пути не известна',
        )
    if (
        obs
        and obs.get('delayHours')
    ):
        reasons.append(f"Событие подвоза: накопленная задержка {number(obs['delayHours'])} ч")
    if locked:
        reasons.append(
            'Морской этап уже начат по другому маршруту: смена маршрута недоступна' if after_loading else 'Груз уже в другом порту. Межпортовый трансфер не моделируется; этот вариант недоступен',
        )
    processed = actual_departure if actual_departure is not None else physical + (origin['handlingHours'] + delay) * HOUR
    available = actual_departure if actual_departure is not None else max(
        processed,
        cargo['documentReadyAt'],
        (
            obs
            or {}
        ).get('modelAt', 0),
    )
    departure = None
    slot = None
    left = 0
    missed = 0
    if actual_departure is not None:
        departure = actual_departure
        slot = cargo.get('acceptedSlot')
        reasons.append(
            'Отправление подтверждено событием учебного оператора; прежнее окно не пересчитывается задним числом',
        )
    if (
        actual_departure is None
        and not locked
    ):
        for i in range(8):
            candidate = state['baseTime'] + (route['firstDeparture'] + i * route['frequencyHours']) * HOUR
            key = f"{route['id']}:{number(candidate)}"
            if candidate - route['cutoffHours'] * HOUR < available:
                missed += 1
                if i == 0:
                    if processed > candidate - route['cutoffHours'] * HOUR:
                        reasons.append('Обработка и очередь заканчиваются позже cutoff')
                    if cargo['documentReadyAt'] > candidate - route['cutoffHours'] * HOUR:
                        reasons.append('Документы не успевают к cutoff')
                continue
            if (
                origin['closureStart'] is not None
                and origin['closureEnd'] is not None
                and origin['closureStart'] <= candidate < origin['closureEnd']
            ):
                missed += 1
                reason = 'Отправление попадает в сценарное погодное ограничение'
                if reason not in reasons:
                    reasons.append(reason)
                continue
            capacity = route['capacity'] - state['allocations'].get(key, 0) + int(cargo.get('acceptedSlot') == key)
            if mathematical:
                from .optimizer import weather_check, scenario_wind_reason
                scenario_hold = scenario_wind_reason(route, state['ports'], cargo['mathWindLimit'])
                if scenario_hold:
                    missed += 1
                    if scenario_hold not in reasons:
                        reasons.append(scenario_hold)
                    continue
                profile = state.get('mathWeatherProfiles',{}).get(cargo.get('mathWeatherHash'))
                check = weather_check(route,state['ports'],candidate,profile,cargo['mathWindLimit'],cargo['mathGustLimit']) if profile else dict(allowed=False, reason='Нет сохранённого прогноза')
                if not check['allowed']:
                    missed += 1
                    if check['reason'] not in reasons:
                        reasons.append(check['reason'])
                    continue
            if capacity < 1:
                missed += 1
                if 'Нет свободного места на отправлении' not in reasons:
                    reasons.append('Нет свободного места на отправлении')
                continue
            departure = candidate
            slot = key
            left = capacity
            break
    sea_arrival = actual_sea if actual_sea is not None else None if departure is None else departure + route['seaHours'] * HOUR
    if (
        sea_arrival is not None
        and actual_sea is None
        and destination['closureStart'] is not None
        and destination['closureEnd'] is not None
        and destination['closureStart'] <= sea_arrival < destination['closureEnd']
    ):
        sea_arrival = destination['closureEnd']
        reasons.append('Ожидание открытия порта назначения в сценарии')
    predicted_discharge = None if sea_arrival is None else sea_arrival + (destination['handlingHours'] + destination_delay) * HOUR
    discharge = min(predicted_discharge, actual_delivery - route['finalHours'] * HOUR) if (
        actual_delivery is not None
        and predicted_discharge is not None
    ) else predicted_discharge
    arrival = actual_delivery if actual_delivery is not None else None if discharge is None else discharge + route['finalHours'] * HOUR
    radius = model.radius * (1 if actual_departure is not None else 2) * HOUR
    supported = (
        (
            actual_departure is not None
            or model.is_supported({
                **origin,
                'portId': origin['id'],
            })
        )
        and model.is_supported({
            **destination,
            'portId': destination['id'],
        })
    )
    valid = (
        supported
        and actual_delivery is None
        and not mathematical
    )
    limitations = [
        'Рейсы, ёмкости и ставки — демонстрационный сценарий',
        'Координаты и пути схематичны; маршрут не является навигационной рекомендацией',
        'Оценка выбросов по справочным факторам Великобритании, не калибровка Каспия',
    ]
    if state['packs'][cargo['id']]['status'] != 'validated':
        limitations.append(
            'Готовность документов условная, пакет ещё не прошёл техническую проверку',
        )
    if mathematical:
        limitations.append('Математический план: очередь по FIFO, погодный профиль и пределы из принятого отчёта; статистический интервал не заявляется.')
    if state['historyOrigin'] == 'synthetic' and not mathematical:
        limitations.append('Модель обучена на синтетической истории')
    if obs:
        limitations.append(
            'Отметки движения созданы оператором демо-сценария; это не AIS/GPS или сообщение перевозчика. Промежуточные времена остаются модельными.',
        )
    if actual_delivery is not None:
        limitations.append(
            'Доставка зафиксирована демо-событием; модельный интервал не применяется к этой отметке.',
        )
    if not supported:
        limitations.append(
            'Параметры вне обучающего диапазона или порт не представлен в обучении: интервал для этого варианта не подтверждён',
        )
    legs = [dict(
        label='Железная дорога' if route['inlandMode'] == 'rail' else 'Автоперевозка',
        mode=route['inlandMode'],
        start=cargo['readyAt'],
        end=physical,
        detail=f"Волгоград → {origin['name']}",
    ), dict(
        label='Очередь и обработка',
        mode='port',
        start=physical,
        end=processed,
        detail=f"{number(origin['queueUnits'])} условных партий · прогноз задержки {number(rounded(delay))} ч",
    )]
    if all((v is not None for v in [
        departure,
        sea_arrival,
        discharge,
        arrival,
    ])):
        legs += [
            dict(
                label='Ожидание отправления',
                mode='port',
                start=processed,
                end=departure,
                detail='Включая ожидание документов и следующего окна',
            ),
            dict(
                label='Морской переход',
                mode='sea',
                start=departure,
                end=sea_arrival,
                detail=f"{origin['name']} → {destination['name']}",
            ),
            dict(
                label='Выгрузка и обработка',
                mode='port',
                start=sea_arrival,
                end=discharge,
                detail=destination['name'],
            ),
            dict(
                label='Доставка получателю',
                mode='road',
                start=discharge,
                end=arrival,
                detail=f"{destination['name']} → Тегеран",
            ),
        ]
    result = dict(
        cargoId=cargo['id'],
        routeId=route['id'],
        routeName=route['name'],
        actualArrival=actual_delivery is not None,
        feasible=departure is not None,
        departure=departure,
        arrival=arrival,
        lowArrival=None if (
            arrival is None
            or not valid
        ) else max(discharge, arrival - radius),
        highArrival=None if (
            arrival is None
            or not valid
        ) else arrival + radius,
        uncertaintyValid=valid,
        readyAtPort=physical,
        availableAt=available,
        cutoffAt=None if (
            departure is None
            or actual_departure is not None
        ) else departure - route['cutoffHours'] * HOUR,
        missedSlots=missed,
        reasons=reasons,
        costRub=rounded(
            route['costRub'] * cargo['massTon'] / 20 + max(0, ((departure if departure is not None else available) - processed) / HOUR) * 200,
        ),
        co2Kg=rounded(
            cargo['massTon'] * (route['inlandKm'] * EMISSION_FACTORS[route['inlandMode']] + route['seaKm'] * EMISSION_FACTORS['sea'] + route['finalKm'] * EMISSION_FACTORS['road']),
        ),
        lateHours=None if arrival is None else max(0, (arrival - cargo['dueAt']) / HOUR),
        slackHours=None if (
            departure is None
            or actual_departure is not None
        ) else (departure - route['cutoffHours'] * HOUR - available) / HOUR,
        slotKey=slot,
        capacityLeft=left,
        legs=legs,
        dataLimitations=limitations,
        portDelay=delay,
        evidence=dict(
            queue=origin['queueUnits'],
            wind=origin['windMs'],
            documentsAt=cargo['documentReadyAt'],
        ),
    )
    if mathematical:
        result.update(calculationMethod='mathematical', mathWeatherHash=cargo['mathWeatherHash'])
    return result


def snapshot(state, version):
    model = fit_model(state['history'], state['historyOrigin'])
    sources = json.loads((DATA / 'sources.json').read_text(encoding='utf-8'))
    if state['historyOrigin'] != 'synthetic':
        sources[1].update(
            kind='Импорт',
            note='Данные пользователя. Проверены схема и временное разделение, не подлинность.',
        )
    return {
        **({'mathWeatherProfiles':state['mathWeatherProfiles']} if state.get('mathWeatherProfiles') else {}),
        **{k: state[k] for k in [
            'baseTime',
            'ports',
            'cargo',
            'routes',
            'packs',
            'audit',
            'scenario',
        ]},
        'version': version,
        'clearances': state.get('clearances', {}),
        'cargoEvents': state.get('cargoEvents', []),
        'forecasts': {c['id']: [forecast(
            state,
            c,
            r,
            model,
        ) for r in state['routes']] for c in state['cargo']},
        'model': model.report,
        'historyRows': len(state['history']),
        'sources': sources,
    }


def set_scenario(state, name, port_id=None, queue=None, wind=None, closure_hours=None):
    defaults = seed_workspace(state['baseTime'])['ports']
    if name == 'normal':
        state['ports'] = [{
            **p,
            'windMs': 6,
            'queueUnits': 2,
            'closureStart': None,
            'closureEnd': None,
        } for p in defaults]
        state['scenario'] = 'Обычная обработка'
    elif name == 'storm':
        state['ports'] = defaults
        state['scenario'] = 'Штормовое окно в Оле'
    elif name == 'queue':
        state['ports'] = [{
            **p,
            'queueUnits': 30 if p['id'] == 'makhachkala' else p['queueUnits'],
            'closureStart': None,
            'closureEnd': None,
        } for p in defaults]
        state['scenario'] = 'Очередь в Махачкале'
    elif name == 'blocked':
        state['ports'] = [{
            **p,
            'closureStart': state['baseTime'],
            'closureEnd': state['baseTime'] + 240 * HOUR,
        } for p in defaults]
        state['scenario'] = 'Все морские окна закрыты'
    elif name == 'custom':
        port = find(state['ports'], port_id)
        if (
            not port
            or queue is None
            or wind is None
        ):
            raise ValueError('Неверные параметры порта')
        port.update(queueUnits=queue, windMs=wind)
        if closure_hours is not None:
            port['closureStart'] = state['baseTime'] + 20 * HOUR if closure_hours > 0 else None
            port['closureEnd'] = state['baseTime'] + (20 + closure_hours) * HOUR if closure_hours > 0 else None
        state['scenario'] = f"Пользовательский сценарий: {port['name']}"
    else:
        raise ValueError('Неизвестный сценарий')


def accept_plan(state, cargo_id, route_id):
    cargo = find(state['cargo'], cargo_id)
    route = find(state['routes'], route_id)
    if (
        not cargo
        or not route
    ):
        raise ValueError('Груз или маршрут не найден')
    if cargo.get('planningMethod') == 'mathematical':
        raise ValueError('Математический план подтверждается после пересчёта кнопкой «Принять расчётный план».')
    if cargo.get('progress', {}).get('stage') in [
        'sea',
        'destination_port',
        'delivered',
    ]:
        raise ValueError('Перепланирование недоступно после фактической погрузки в демо-сценарии')
    if state['packs'][cargo_id]['status'] != 'validated':
        raise ValueError('Сначала выполните техническую проверку документов')
    if state.get('clearances', {}).get(cargo_id, {}).get('status') != 'ready_demo':
        raise ValueError('Сначала завершите демонстрационную предварительную проверку заявки')
    result = forecast(
        state,
        cargo,
        route,
    )
    if (
        not result['feasible']
        or not result['slotKey']
    ):
        raise ValueError('Нет допустимого отправления в горизонте сценария')
    if cargo.get('acceptedSlot') == result['slotKey']:
        return dict(unchanged=True, result=result)
    old = cargo.get('acceptedSlot')
    if old:
        state['allocations'][old] = max(0, state['allocations'].get(old, 0) - 1)
    key = result['slotKey']
    state['allocations'][key] = state['allocations'].get(key, 0) + 1
    cargo.update(acceptedSlot=key, acceptedRoute=route_id)
    return dict(unchanged=False, result=result)
