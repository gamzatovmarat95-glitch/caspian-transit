"""Mutation rules independent of Django and persistence; used under an ORM transaction."""
from .sample import HOUR, seed_workspace, iso
from .engine import snapshot, forecast, find, pack_errors, accept_plan, set_scenario
from .model import fit_model, parse_history_csv
from .integrity import append_audit, sign, technical_gateway, now_iso
from .clearance import submit_clearance, review_clearance, invalidate_clearance
from .tracking import apply_tracking_event, event_estimate, EVENT_LABELS
import math
import uuid


class ActionError(ValueError):

    def __init__(self, message, status=400, errors=None):
        super().__init__(message)
        self.status = status
        self.errors = errors


def validate_input(data):
    if (
        not isinstance(data, dict)
        or type(data.get('version')) not in (int, float)
        or not math.isfinite(data['version'])
        or int(data['version']) != data['version']
        or data['version'] < 0
    ):
        raise ActionError('Неверные параметры действия')
    data['version'] = int(data['version'])
    try:
        uuid.UUID(data['key'])
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ActionError('Неверный ключ идемпотентности')
    action = data.get('type')
    if action not in [
        'scenario',
        'document',
        'accept',
        'accept_mathematical',
        'clearance_submit',
        'clearance_review',
        'cargo_event',
        'history',
        'reset',
        'cargo_create',
        'cargo_update',
    ]:
        raise ActionError('Неизвестное действие')
    if (
        action in [
            'document',
            'accept',
            'clearance_submit',
            'clearance_review',
            'cargo_event',
        ]
        and (
            not isinstance(data.get('cargoId'), str)
            or len(data['cargoId']) > 40
        )
    ):
        raise ActionError('Неверный груз')

    def numeric(key, low, high, integer=False, required=False):
        if key not in data:
            if required:
                raise ActionError('Не указан параметр ' + key)
            return
        v = data[key]
        if (
            type(v) not in (int, float)
            or not math.isfinite(v)
            or not low <= v <= high
            or (
                integer
                and int(v) != v
            )
        ):
            raise ActionError('Неверный параметр ' + key)
    if action == 'scenario':
        if data.get('name') not in [
            'normal',
            'storm',
            'queue',
            'blocked',
            'custom',
        ]:
            raise ActionError('Неизвестный сценарий')
        numeric(
            'queue',
            0,
            50,
            True,
        )
        numeric(
            'wind',
            0,
            35,
        )
        numeric(
            'closureHours',
            0,
            72,
        )
    if action == 'cargo_event':
        if data.get('kind') not in EVENT_LABELS:
            raise ActionError('Неизвестное событие')
        numeric(
            'atHours',
            0,
            240,
            required=True,
        )
        numeric(
            'delayHours',
            0,
            72,
        )
        numeric(
            'queueUnits',
            0,
            50,
            True,
        )
        numeric(
            'holdHours',
            0,
            72,
        )
        if (
            'portId' in data
            and data['portId'] not in [
                'olya',
                'makhachkala',
                'anzali',
                'amirabad',
            ]
        ):
            raise ActionError('Неверный порт')
    if action == 'document':
        validate_fields(
            data.get('pack'),
            {
                'invoice': 100,
                'packingList': 100,
                'hsCode': 30,
                'consignee': 200,
                'reference': 100,
            },
            {'massTon': 100},
        )
        if type(data.get('submit')) is not bool:
            raise ActionError('Неверные параметры действия')
    if action == 'clearance_submit':
        validate_declaration(data.get('declaration'))
    if (
        action == 'accept'
        and (
            not isinstance(data.get('routeId'), str)
            or len(data['routeId']) > 40
        )
    ):
        raise ActionError('Неверный маршрут')
    if (
        action == 'history'
        and (
            not isinstance(data.get('csv'), str)
            or len(data['csv']) > 1200000
        )
    ):
        raise ActionError('CSV больше 1,2 МБ')
    return data


def validate_fields(value, strings, numbers):
    if (
        not isinstance(value, dict)
        or set(value) != set(strings) | set(numbers)
    ):
        raise ActionError('Неверная схема полей')
    for key, limit in strings.items():
        if (
            not isinstance(value[key], str)
            or len(value[key]) > limit
        ):
            raise ActionError('Неверное поле ' + key)
    for key, limit in numbers.items():
        if (
            type(value[key]) not in (int, float)
            or not math.isfinite(value[key])
            or not 0 <= value[key] <= limit
        ):
            raise ActionError('Неверное поле ' + key)


def validate_declaration(value):
    validate_fields(
        value,
        {
            'originCountry': 3,
            'destinationCountry': 3,
            'transportDocument': 100,
            'originCertificate': 100,
            'description': 300,
        },
        {
            'declaredMassTon': 100,
            'declaredValueRub': 1000000000000,
        },
    )


def apply_action(state, input, secret):
    validate_input(input)
    at = now_iso()
    action = input['type']
    cid = input.get('cargoId')
    if action in ('cargo_create', 'cargo_update'):
        from .shipments import save_shipment
        save_shipment(state, input)
    elif action == 'scenario':
        set_scenario(
            state,
            input['name'],
            input.get('portId'),
            input.get('queue'),
            input.get('wind'),
            input.get('closureHours'),
        )
        append_audit(
            state['audit'],
            'NETWORK',
            'Изменён сценарий',
            state['scenario'],
        )
    elif action == 'document':
        cargo = find(state['cargo'], cid)
        if not cargo:
            raise ActionError('Груз не найден', 404)
        pack = {
            **input['pack'],
            'status': 'draft',
        }
        if input['submit']:
            errors = pack_errors(pack, cargo)
            if errors:
                raise ActionError(
                    'Исправьте пакет документов',
                    422,
                    errors,
                )
            payload = dict(
                cargoId=cid,
                pack=pack,
                at=at,
                nonce=input['key'],
            )
            receipt = technical_gateway(
                payload,
                sign(payload, secret),
                secret,
            )
            state['packs'][cid] = {
                **pack,
                'status': 'validated',
                'receipt': receipt,
            }
            cargo['documentReadyAt'] = state['baseTime']
            append_audit(
                state['audit'],
                cid,
                'Пакет технически проверен',
                f"Демо-квитанция {receipt['id']}. Не является решением таможенного органа.",
            )
        else:
            state['packs'][cid] = pack
            cargo['documentReadyAt'] = max(cargo['documentReadyAt'], state['baseTime'] + 4 * HOUR)
            append_audit(
                state['audit'],
                cid,
                'Сохранён черновик',
                'Техническая проверка пакета не выполнена',
            )
        invalidate_clearance(
            state,
            cid,
            at,
        )
    elif action == 'clearance_submit':
        app = submit_clearance(
            state,
            cid,
            input['declaration'],
            at,
        )
        append_audit(
            state['audit'],
            cid,
            'Отправлена демо-заявка',
            f"Редакция {app['revision']}. Ожидает автоматической проверки учебных правил.",
        )
    elif action == 'clearance_review':
        app = review_clearance(
            state,
            cid,
            input['key'],
            secret,
            at,
        )
        cargo = find(state['cargo'], cid)
        cargo['documentReadyAt'] = state['baseTime'] if app['status'] == 'ready_demo' else max(cargo['documentReadyAt'], state['baseTime'] + 4 * HOUR)
        issues = (
            ', '.join((c['id'] for c in app['checks'] if not c['passed']))
            or 'Все условные правила пройдены'
        )
        append_audit(
            state['audit'],
            cid,
            'Проверена демо-заявка',
            f"Редакция {app['revision']}: {app['status']}. {issues}. Не является таможенным выпуском.",
        )
    elif action == 'cargo_event':
        cargo = find(state['cargo'], cid)
        if not cargo:
            raise ActionError('Груз не найден', 404)
        route = find(state['routes'], cargo.get('acceptedRoute', cargo['plannedRoute']))
        if cargo.get('planningMethod') == 'mathematical' and input.get('kind') == 'loaded':
            from datetime import datetime
            import time
            profile = state.get('mathWeatherProfiles',{}).get(cargo.get('mathWeatherHash'),{})
            try:
                age = time.time()-datetime.fromisoformat(profile['fetchedAt']).timestamp()
            except (KeyError, ValueError, TypeError):
                age = float('inf')
            if age > 3600 or age < -300:
                raise ActionError('Перед погрузкой обновите прогноз и подтвердите математический план.',409)
        model = None if cargo.get('planningMethod') == 'mathematical' else fit_model(state['history'], state['historyOrigin'])
        before = event_estimate(forecast(
            state,
            cargo,
            route,
            model,
        ))
        event = apply_tracking_event(
            state,
            input,
            input['key'],
            at,
            before,
        )
        event['after'] = event_estimate(forecast(
            state,
            cargo,
            route,
            model,
        ))
        append_audit(
            state['audit'],
            cid,
            'Событие учебной перевозки',
            event['detail'] + ' Время сценария: ' + iso(event['happenedAt']) + '.',
        )
    elif action == 'accept':
        accepted = accept_plan(
            state,
            cid,
            input['routeId'],
        )
        if not accepted['unchanged']:
            f = accepted['result']
            append_audit(
                state['audit'],
                cid,
                'Принят демонстрационный план',
                f"{f['routeName']}, слот {iso(f['departure'])}. Занята одна условная единица ёмкости.",
            )
    elif action == 'accept_mathematical':
        from .math_planning import accept_mathematical
        accept_mathematical(state, input, secret)
    elif action == 'history':
        rows = parse_history_csv(input['csv'], state['baseTime'])
        fit_model(rows, 'imported')
        state.update(
            history=rows,
            historyOrigin='imported',
            importedAt=at,
        )
        append_audit(
            state['audit'],
            'MODEL',
            'Импортирована история',
            f'{len(rows)} наблюдений; происхождение не верифицировано',
        )
    elif action == 'reset':
        if any(c.get('source') == 'manual' for c in state['cargo']):
            raise ActionError('В пространстве есть свои партии. Сброс учебного сценария заблокирован, чтобы сохранить данные.', 409)
        state = seed_workspace()
        append_audit(
            state['audit'],
            'NETWORK',
            'Новый демонстрационный сценарий',
            'Предыдущие учебные решения сброшены по явному действию пользователя',
        )
    state['idempotency'][input['key']] = at
    return state
