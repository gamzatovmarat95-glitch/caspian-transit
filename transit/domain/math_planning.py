"""Accept a reproducible mathematical recommendation into the existing cargo lifecycle."""
import math
import time
from datetime import datetime
from .integrity import verify_signature, append_audit


class QueueRules:
    radius = 0

    def predict(self, port):
        return port['queueUnits']*port['handlingHours']/max(1, port.get('serviceLanes', 1))

    def is_supported(self, port):
        return True


def accept_mathematical(state, data, secret):
    from .actions import ActionError
    from .engine import find, forecast
    from .optimizer import optimize
    profile = data.get('weatherProfile')
    if not isinstance(profile, dict) or not verify_signature(profile, data.get('weatherSignature',''), secret):
        raise ActionError('Погодный профиль изменён или не подписан сервером. Пересчитайте рекомендацию.', 409)
    try:
        fetched = datetime.fromisoformat(profile['fetchedAt']).timestamp()*1000
    except (KeyError, ValueError, TypeError):
        raise ActionError('Неверное время прогноза')
    now = time.time()*1000
    planning_at = math.floor(now/300000)*300000
    if now-fetched > 3600000 or fetched-now > 300000 or data.get('planningAt') != planning_at:
        raise ActionError('Прогноз или время планирования устарели. Нажмите «Пересчитать» перед подтверждением.', 409)
    cargo = find(state['cargo'], data.get('cargoId'))
    if not cargo:
        raise ActionError('Партия не найдена', 404)
    if state['packs'][cargo['id']]['status'] != 'validated' or state.get('clearances',{}).get(cargo['id'],{}).get('status') != 'ready_demo':
        raise ActionError('Сначала завершите техническую и предварительную проверку документов', 409)
    report = optimize(state, data['version'], cargo['id'], profile, data.get('objective','time'), data.get('windLimit',15), data.get('gustLimit',22), planning_at)
    best = report['best']
    if not best or report['inputHash'] != data.get('inputHash') or best['routeId'] != data.get('routeId'):
        raise ActionError('Условия или лучший вариант изменились. Пересчитайте и проверьте новый отчёт.', 409)
    # The profile is stored once per hash. No external provider credential is stored here.
    state.setdefault('mathWeatherProfiles', {})[profile['hash']] = profile
    cargo.update(planningMethod='mathematical', mathPlanningAt=planning_at, mathWeatherHash=profile['hash'],
                 mathWindLimit=data.get('windLimit',15), mathGustLimit=data.get('gustLimit',22), mathObjective=data.get('objective','time'))
    check = forecast(state, cargo, find(state['routes'], best['routeId']))
    if not check['feasible'] or check['slotKey'] != best['slotKey'] or abs(check['arrival']-best['arrival']) > 1 or check['costRub'] != best['costRub'] or check['co2Kg'] != best['co2Kg']:
        raise ActionError('Расчёт плана и жизненный цикл не совпали. План не принят.', 409)
    old = cargo.get('acceptedSlot')
    if old:
        state['allocations'][old] = max(0, state['allocations'].get(old,0)-1)
    state['allocations'][best['slotKey']] = state['allocations'].get(best['slotKey'],0)+1
    cargo.update(acceptedRoute=best['routeId'], acceptedSlot=best['slotKey'])
    append_audit(state['audit'], cargo['id'], 'Принят математический демо-план',
                 f"{best['routeName']}; {report['inputHash']}; погода {profile['hash']}. Условный слот, не бронирование перевозчика.")
