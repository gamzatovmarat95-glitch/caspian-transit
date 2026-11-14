from .sample import HOUR
from .engine import find, number
import math
EVENT_LABELS = {
    'dispatched': 'Подвоз начат',
    'inland_delay': 'Задержка подвоза',
    'origin_arrival': 'Прибытие в порт отправления',
    'queue_changed': 'Изменилась очередь',
    'weather_hold': 'Ограничено окно порта',
    'loaded': 'Погрузка и отправление',
    'sea_arrival': 'Прибытие в порт назначения',
    'delivered': 'Доставлено получателю',
}
STAGE_LABELS = {
    'planned': 'Планирование',
    'inland': 'Подвоз',
    'origin_port': 'В порту отправления',
    'sea': 'В море',
    'destination_port': 'В порту назначения',
    'delivered': 'Доставлено',
}


def event_estimate(f):
    return {k: f[k] for k in [
        'routeId',
        'feasible',
        'departure',
        'arrival',
        'costRub',
        'co2Kg',
        'lateHours',
    ]}


def finite(value):
    return (
        type(value) in (int, float)
        and math.isfinite(value)
    )


def apply_tracking_event(state, input, event_id, recorded_at, before):
    cargo = find(state['cargo'], input['cargoId'])
    if not cargo:
        raise ValueError('Груз не найден')
    route = find(state['routes'], cargo.get('acceptedRoute', cargo['plannedRoute']))
    model_at = state['baseTime'] + input['atHours'] * HOUR
    old = cargo.get('progress')
    if (
        not finite(model_at)
        or not 0 <= input['atHours'] <= 240
        or model_at < cargo['readyAt']
        or (
            old
            and model_at < old['modelAt']
        )
    ):
        raise ValueError('Время события должно быть не раньше готовности груза и последнего события')
    if len(state.get('cargoEvents', [])) >= 500:
        raise ValueError('Журнал событий заполнен: экспортируйте отчёт и начните новый сценарий')
    if (
        old
        and old['stage'] == 'delivered'
    ):
        raise ValueError('Перевозка уже завершена; новые операционные события недоступны')
    progress = dict(
        (
            old
            or dict(
                stage='planned',
                routeId=route['id'],
                modelAt=model_at,
                delayHours=0,
                lastEventId=event_id,
            )
        ),
    )
    origin = find(state['ports'], route['from'])
    destination = find(state['ports'], route['to'])
    kind = input['kind']
    if kind not in EVENT_LABELS:
        raise ValueError('Неизвестное событие')
    detail = EVENT_LABELS[kind]
    port_id = None
    pre_sea = (
        not old
        or old['stage'] in [
            'planned',
            'inland',
            'origin_port',
        ]
    )
    if kind == 'dispatched':
        if (
            old
            and old['stage'] != 'planned'
        ):
            raise ValueError('Подвоз уже зарегистрирован')
        progress['stage'] = 'inland'
        detail = f"Учебная отметка отправления: Волгоград → {origin['name']}"
    elif kind == 'inland_delay':
        if (
            old
            and old['stage'] not in ['planned', 'inland']
        ):
            raise ValueError('Задержку подвоза нельзя добавить после прибытия в порт')
        if (
            not finite(input.get('delayHours'))
            or not 0 < input['delayHours'] <= 72
        ):
            raise ValueError('Укажите задержку подвоза от 0 до 72 часов')
        progress['delayHours'] += input['delayHours']
        if progress['delayHours'] > 120:
            raise ValueError('Суммарная задержка выходит за пределы демо-сценария')
        detail = f"Подвоз задержан ещё на {number(input['delayHours'])} ч; всего {number(progress['delayHours'])} ч. Источник — оператор учебного сценария."
    elif kind == 'origin_arrival':
        if (
            old
            and old['stage'] not in ['planned', 'inland']
        ):
            raise ValueError('Прибытие в порт уже зарегистрировано или подвоз завершён')
        progress.update(
            stage='origin_port',
            routeId=route['id'],
            actualPortArrival=model_at,
        )
        port_id = origin['id']
        detail = f"Учебная отметка прибытия в {origin['name']}; это время заменяет плановый подвоз в расчёте."
    elif kind in ['queue_changed', 'weather_hold']:
        if not pre_sea:
            raise ValueError('Сценарий очереди/ограничения порта отправления недоступен после погрузки')
        port = find(state['ports'], input.get('portId', route['from']))
        if not port:
            raise ValueError('Порт не найден')
        port_id = port['id']
        if kind == 'queue_changed':
            if (
                not finite(input.get('queueUnits'))
                or int(input['queueUnits']) != input['queueUnits']
                or not 0 <= input['queueUnits'] <= 50
            ):
                raise ValueError('Очередь должна быть целым числом от 0 до 50')
            port['queueUnits'] = input['queueUnits']
            detail = f"В {port['name']} установлена очередь {input['queueUnits']} учебных партий. Пересчитаны все затронутые перевозки."
        else:
            if (
                not finite(input.get('holdHours'))
                or not 0 < input['holdHours'] <= 72
            ):
                raise ValueError('Укажите длительность ограничения от 0 до 72 часов')
            port.update(closureStart=model_at, closureEnd=model_at + input['holdHours'] * HOUR)
            detail = f"В {port['name']} введено учебное ограничение отправлений на {number(input['holdHours'])} ч. Это не сообщение фактического оператора порта."
        state['scenario'] = 'События: ' + EVENT_LABELS[kind]
    elif kind == 'loaded':
        if (
            not old
            or old['stage'] != 'origin_port'
            or 'actualPortArrival' not in old
        ):
            raise ValueError('Сначала зарегистрируйте прибытие в порт отправления')
        observed = find(state['routes'], old['routeId'])
        if observed['from'] != route['from']:
            raise ValueError('Принятый маршрут не соответствует порту наблюдаемого груза')
        if (
            not cargo.get('acceptedRoute')
            or not cargo.get('acceptedSlot')
            or state.get('clearances', {}).get(cargo['id'], {}).get('status') != 'ready_demo'
        ):
            raise ValueError('Для погрузки нужен принятый план и готовая демонстрационная заявка')
        if (
            not before['feasible']
            or before['departure'] is None
            or cargo['acceptedSlot'] != f"{route['id']}:{number(before['departure'])}"
        ):
            raise ValueError(
                'Принятый слот устарел: пересчитайте и примите актуальный план перед погрузкой',
            )
        if model_at < old['actualPortArrival'] + origin['handlingHours'] * HOUR:
            raise ValueError('Погрузка указана раньше минимального времени обработки')
        progress.update(
            stage='sea',
            routeId=route['id'],
            actualDeparture=model_at,
        )
        port_id = origin['id']
        detail = f"Учебная отметка погрузки: {route['name']}. После неё смена морского маршрута заблокирована."
    elif kind == 'sea_arrival':
        if (
            not old
            or old['stage'] != 'sea'
            or 'actualDeparture' not in old
        ):
            raise ValueError('Сначала зарегистрируйте отправление судна')
        if model_at <= old['actualDeparture']:
            raise ValueError('Прибытие судна должно быть позже отправления')
        progress.update(stage='destination_port', actualSeaArrival=model_at)
        port_id = destination['id']
        detail = f"Учебная отметка прибытия в {destination['name']}; прогноз пересчитан от этого времени."
    elif kind == 'delivered':
        if (
            not old
            or old['stage'] != 'destination_port'
            or 'actualSeaArrival' not in old
        ):
            raise ValueError('Сначала зарегистрируйте прибытие в порт назначения')
        if model_at < old['actualSeaArrival'] + (destination['handlingHours'] + route['finalHours']) * HOUR:
            raise ValueError('Доставка указана раньше минимальной обработки и последнего этапа')
        progress.update(stage='delivered', actualDeliveredAt=model_at)
        detail = 'Доставка подтверждена учебным событием. В карточке показано время события, а не прогноз.'
    progress.update(modelAt=model_at, lastEventId=event_id)
    cargo['progress'] = progress
    event = dict(
        id=event_id,
        cargoId=cargo['id'],
        kind=kind,
        happenedAt=model_at,
        recordedAt=recorded_at,
        source='demo_operator',
        detail=detail,
        before=before,
        after=before,
    )
    if port_id:
        event['portId'] = port_id
    state.setdefault('cargoEvents', []).append(event)
    return event
