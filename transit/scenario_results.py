"""Presentation of actual before/after forecasts; no invented effect when a slot stays unchanged."""
from .domain.sample import HOUR


def current_result(request, version, cargo_id):
    from .views import owner
    result = request.session.get('scenario_result')
    if (isinstance(result, dict) and result.get('version') == version
            and result.get('cargoId') == cargo_id
            and request.session.get('scenario_result_owner') == owner(request)):
        return result
    return None


def summarize(before, after, cargo_id):
    changed_ports = []
    for port in after['ports']:
        previous = next(p for p in before['ports'] if p['id'] == port['id'])
        if any(previous[k] != port[k] for k in ('queueUnits', 'windMs', 'closureStart', 'closureEnd')):
            def hours(p):
                return 0 if p['closureStart'] is None else (p['closureEnd']-p['closureStart'])/HOUR
            changed_ports.append(dict(name=port['name'], beforeQueue=previous['queueUnits'], queue=port['queueUnits'],
                beforeWind=previous['windMs'], wind=port['windMs'], beforeClosure=hours(previous), closure=hours(port)))
    changes = []
    for current in after['forecasts'].get(cargo_id, []):
        previous = next(f for f in before['forecasts'][cargo_id] if f['routeId'] == current['routeId'])
        def processing(f):
            # Waiting for departure absorbs small queue changes; show actual handling separately.
            return sum((leg['end']-leg['start'])/HOUR for i, leg in enumerate(f['legs'])
                       if leg['mode'] == 'port' and i > 0 and f['legs'][i-1]['mode'] != 'port')
        changed = any(previous[k] != current[k] for k in ('departure','arrival','availableAt','feasible','costRub'))
        changes.append(dict(routeName=current['routeName'], beforeArrival=previous['arrival'], arrival=current['arrival'],
            beforeDeparture=previous['departure'], departure=current['departure'], beforeProcessing=processing(previous), processing=processing(current),
            beforeCost=previous['costRub'], cost=current['costRub'], changed=changed,
            sameSlot=previous['departure']==current['departure'], sameArrival=previous['arrival']==current['arrival']))
    return dict(version=after['version'], cargoId=cargo_id, ports=changed_ports, routes=changes,
                changedRoutes=sum(r['changed'] for r in changes), scenario=after['scenario'])
