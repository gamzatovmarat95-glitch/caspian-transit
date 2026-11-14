"""User-entered consignments; reference schedules and forecasts remain a simulation."""
import math
from .engine import find
from .integrity import append_audit, now_iso
from .clearance import invalidate_clearance


def save_shipment(state, data):
    # Import here to keep ActionError shared without a module initialization cycle.
    from .actions import ActionError
    fields = data.get('shipment')
    if not isinstance(fields, dict):
        raise ActionError('Не указаны параметры партии')
    clean = {}
    for key, limit in [('name', 200), ('customer', 200), ('externalReference', 100)]:
        value = fields.get(key, '')
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ActionError('Заполните поле ' + key)
        clean[key] = value.strip()
    for key, low, high in [('massTon', 0.001, 100), ('readyAt', 946684800000, 4102444800000), ('dueAt', 946684800000, 4102444800000)]:
        value = fields.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ActionError('Неверное значение ' + key)
        clean[key] = value
    if clean['dueAt'] <= clean['readyAt']:
        raise ActionError('Срок доставки должен быть позже готовности партии')
    if not find(state['routes'], fields.get('plannedRoute')):
        raise ActionError('Выберите маршрут из справочника')
    clean['plannedRoute'] = fields['plannedRoute']
    if fields.get('priority') not in ('Обычный', 'Высокий'):
        raise ActionError('Неверный приоритет')
    clean['priority'] = fields['priority']
    existing = find(state['cargo'], data.get('cargoId')) if data['type'] == 'cargo_update' else None
    if data['type'] == 'cargo_update' and not existing:
        raise ActionError('Партия не найдена', 404)
    if existing and (existing.get('acceptedSlot') or existing.get('progress') or existing.get('source') != 'manual'):
        raise ActionError('Изменять можно свою партию до принятия плана и начала перевозки', 409)
    if any(c.get('externalReference') == clean['externalReference'] and c is not existing for c in state['cargo']):
        raise ActionError('Партия с таким референсом уже существует', 409)
    if existing:
        cid = existing['id']
        existing.update(clean)
        # Changed shipment fields require a fresh document/clearance review.
        state['packs'][cid].update(massTon=clean['massTon'], status='draft')
        state['packs'][cid].pop('receipt', None)
        invalidate_clearance(state, cid, now_iso())
    else:
        if len(state['cargo']) >= 200:
            raise ActionError('В одном пространстве поддерживается до 200 партий', 409)
        cid = 'CSP-' + str(max([1041] + [int(c['id'][4:]) for c in state['cargo']]) + 1)
        state['cargo'].append(dict(clean, id=cid, source='manual', documentReadyAt=clean['readyAt']))
        # The technical demo gateway has its own reference namespace; the customer's
        # real order reference remains a separate consignment field.
        state['packs'][cid] = dict(invoice='', packingList='', hsCode='', consignee='', massTon=clean['massTon'], reference='DEMO-' + cid[4:], status='draft')
    append_audit(state['audit'], cid, 'Изменена партия' if existing else 'Создана партия', clean['externalReference'] + ' · ввод пользователя; расписания и прогноз являются расчётными.')
    return cid
