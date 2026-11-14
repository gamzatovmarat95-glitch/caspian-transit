"""Server-rendered page data; all routing and prediction stay in Python."""
from pathlib import Path
import json
import uuid
import re
from .domain.engine import snapshot, find
from .domain.sample import HOUR
from .domain.tracking import STAGE_LABELS
from .domain.clearance import initial_declaration, document_fields
from .forms import PackForm, DeclarationForm, ScenarioForm, EventForm
from .domain.integrity import check_audit
from django.conf import settings
from .legacy_ui import legacy_context
from .domain.corridors import sea_corridor, land_connections, COLORS
from .scenario_results import current_result
PAGES = [
    ('overview', 'Обзор коридора', 'compass'),
    ('cargo', 'Перевозки', 'container'),
    ('tracking', 'События груза', 'radio'),
    ('scenarios', 'Цифровой двойник', 'sliders'),
    ('documents', 'Документы', 'file'),
    ('validation', 'Проверка модели', 'chart'),
    ('audit', 'Журнал решений', 'clock'),
    ('sources', 'Источники и аналоги', 'database'),
]
TITLES = {
    'overview': ('Каспийский коридор', 'Планирование перевозок между Россией и Ираном'),
    'cargo': ('Перевозки', 'Грузы, сроки и готовность к отправлению'),
    'tracking': ('События перевозки', 'План, последняя отметка и обновлённый прогноз'),
    'scenarios': ('Цифровой двойник', 'Проверьте последствия до изменения плана'),
    'documents': ('Предварительная проверка', 'Документы выбранной партии и результат проверки'),
    'validation': ('Доверие к прогнозу', 'Измерения, временная проверка и ограничения'),
    'sources': ('Источники и аналоги', 'Что подтверждено, что смоделировано'),
    'audit': ('Журнал решений', 'От события до действия — с проверкой целостности'),
}


def state_of(s, c):
    f = next(
        (f for f in s['forecasts'][c['id']] if f['routeId'] == c.get('acceptedRoute', c['plannedRoute'])),
    )
    if c.get('progress', {}).get('stage') == 'delivered':
        return ('Доставлено · демо', 'warning' if (
            f['lateHours']
            or 0
        ) > 0 else 'success')
    if not f['feasible']:
        return ('Нет отправления', 'danger')
    if (
        f['lateHours']
        or 0
    ) > 0:
        return ('Риск опоздания', 'danger')
    if (
        s['packs'][c['id']]['status'] != 'validated'
        or s['clearances'].get(c['id'], {}).get('status') != 'ready_demo'
    ):
        return ('Проверить документы', 'warning')
    return ('План принят' if c.get('acceptedRoute') else 'В пределах срока', 'success')


def project(lat, lon):
    return ((lon - 42) / 14 * 900, (49.3 - lat) / 14.3 * 680)


def geometry_path(geometry):
    polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
    paths = []
    for polygon in polygons:
        for ring in polygon:
            paths.append(
                ' '.join(
                    (('M' if i == 0 else 'L') + f'{project(lat, lon)[0]:.1f},{project(lat, lon)[1]:.1f}' for i, (lon, lat) in enumerate(ring)),
                ) + 'Z',
            )
    return ' '.join(paths)


def context_for(request, state, version, page, errors=None):
    from .live_weather import browser_config
    from .route_weather import public_config
    s = snapshot(state, version)
    selected = (
        request.POST.get('cargoId')
        or request.GET.get('cargo')
        or s['cargo'][0]['id']
    )
    cargo = (
        find(s['cargo'], selected)
        or s['cargo'][0]
    )
    cid = cargo['id']
    forecasts = s['forecasts'][cid]
    base = next(
        (f for f in forecasts if f['routeId'] == cargo.get('acceptedRoute', cargo['plannedRoute'])),
    )
    recommended = next(
        iter(
            sorted(
                [f for f in forecasts if f['feasible']],
                key=lambda f: (
                    f['lateHours'] if f['lateHours'] is not None else float('inf'),
                    f['costRub'],
                    f['arrival'],
                ),
            ),
        ),
        None,
    )
    chosen = (
        next((f for f in forecasts if f['routeId'] == request.GET.get('route')), None)
        or base
    )
    rows = []
    risk = 0
    pending = 0
    query = request.GET.get('q', '')[:100].strip().lower()
    only_risk = request.GET.get('risk') == '1'
    for c in s['cargo']:
        f = next(
            (f for f in s['forecasts'][c['id']] if f['routeId'] == c.get('acceptedRoute', c['plannedRoute'])),
        )
        label, kind = state_of(s, c)
        is_risk = (
            not f['feasible']
            or (
                f['lateHours']
                or 0
            ) > 0
        )
        risk += int(is_risk)
        pending += int(
            (
                s['packs'][c['id']]['status'] != 'validated'
                or s['clearances'].get(c['id'], {}).get('status') != 'ready_demo'
            ),
        )
        if (
            query
            and query not in (c['id'] + ' ' + c['name'] + ' ' + c['customer']).lower()
        ):
            continue
        if (
            only_risk
            and not is_risk
        ):
            continue
        rows.append(dict(
            cargo=c,
            forecast=f,
            label=label,
            kind=kind,
        ))
    pack = s['packs'][cid]
    application = s['clearances'].get(cid)
    stages = []
    current_stage = cargo.get('progress', {}).get('stage', 'planned')
    current_index = list(STAGE_LABELS).index(current_stage)
    for i, (key, label) in enumerate(STAGE_LABELS.items()):
        stages.append(
            dict(
                label=label,
                state='passed' if i < current_index else 'current' if i == current_index else 'future',
            ),
        )
    port = (
        find(s['ports'], request.GET.get('port', 'olya'))
        or s['ports'][0]
    )
    closure = 0 if port['closureStart'] is None else (port['closureEnd'] - port['closureStart']) / HOUR
    pack_form = PackForm(initial=document_fields(pack))
    declaration_form = DeclarationForm(
        initial=(
            (
                application
                or {}
            ).get('declaration')
            or initial_declaration(cargo)
        ),
    )
    scenario_form = ScenarioForm(
        initial=dict(
            portId=port['id'],
            queue=port['queueUnits'],
            wind=port['windMs'],
            closureHours=closure,
        ),
    )
    event_form = EventForm(
        initial=dict(
            atHours=max(
                0,
                ((
                    cargo.get('progress')
                    or {}
                ).get('modelAt', cargo['readyAt']) - s['baseTime']) / HOUR,
            ),
            delayHours=12,
            queueUnits=12,
            holdHours=12,
        ),
    )
    if (
        request.method == 'POST'
        and errors
    ):
        if request.POST.get('type') == 'document':
            pack_form = PackForm(request.POST)
        if request.POST.get('type') == 'clearance_submit':
            declaration_form = DeclarationForm(request.POST)
        if request.POST.get('type') == 'cargo_event':
            event_form = EventForm(request.POST)
        if (
            request.POST.get('type') == 'scenario'
            and request.POST.get('name') == 'custom'
        ):
            scenario_form = ScenarioForm(request.POST)
    geography = json.loads(
        (settings.BASE_DIR / 'static/caspian-geography.json').read_text(encoding='utf-8'),
    )
    features = [dict(kind=f['kind'], path=geometry_path(f['geometry'])) for f in geography['features']]
    routes = []
    for r in s['routes']:
        sea = sea_corridor(r)
        if sea is None:
            from .domain.optimizer import sea_geometry
            sea = sea_geometry(r, s['ports'])
        routes.append(
            {
                **r,
                'geometry': sea,
                'color': COLORS.get(r['id'], '#536477'),
                'chain': 'Волгоград → ' + ('ж/д' if r['inlandMode'] == 'rail' else 'авто')
                    + ' → ' + find(s['ports'], r['from'])['name'] + ' → море → '
                    + find(s['ports'], r['to'])['name'] + ' → авто → Тегеран',
                'path': ' '.join(
                    (('M' if i == 0 else 'L') + f'{project(lat, lon)[0]},{project(lat, lon)[1]}' for i, (lat, lon) in enumerate(sea)),
                ),
            },
        )
    land_segments = land_connections(s['routes'], s['ports'])
    for segment in land_segments:
        segment['selected'] = chosen['routeId'] in segment['routeIds']
        segment['path'] = ' '.join(
            ('M' if i == 0 else 'L') + f'{project(lat, lon)[0]},{project(lat, lon)[1]}'
            for i, (lat, lon) in enumerate(segment['geometry'])
        )
    approaches = []
    for r in routes:
        for port_id, sea_point in ((r['from'], r['geometry'][0]), (r['to'], r['geometry'][-1])):
            if any(a['portId'] == port_id for a in approaches):
                continue
            p = find(s['ports'], port_id)
            coordinates = [[p['lat'], p['lon']], sea_point]
            approaches.append(dict(portId=port_id, geometry=coordinates,
                path=' '.join(('M' if i == 0 else 'L') + f'{project(lat, lon)[0]},{project(lat, lon)[1]}' for i, (lat, lon) in enumerate(coordinates))))
    ports = [{
        **p,
        'x': project(p['lat'], p['lon'])[0],
        'y': project(p['lat'], p['lon'])[1],
        'right': p['id'] in ['amirabad', 'makhachkala'],
    } for p in s['ports']]
    research = json.loads((settings.BASE_DIR / 'static/research.json').read_text(encoding='utf-8'))['solutions']
    category = request.GET.get('category', 'all')
    categories = sorted({a['category'] for a in research})
    if category == 'visibility':
        research = [a for a in research if re.search('visibility|predictive', a['category'])]
    elif category == 'port':
        research = [a for a in research if 'port_' in a['category']]
    elif category == 'simulation':
        research = [a for a in research if a['category'] == 'simulation_tool']
    elif category == 'other':
        research = [a for a in research if not re.search('visibility|predictive|port_|simulation', a['category'])]
    elif category != 'all':
        research = [a for a in research if a['category'] == category]
    model = s['model']
    series = model['series']
    max_value = max((
        [v for r in series for v in [
            r['actual'],
            r['predicted'],
            r['baseline'],
        ]]
        or [1]
    ))
    # A valid imported history may contain no delays at all.
    # Keep a nonzero chart scale without changing the model's zero values.
    max_value = max(1, max_value) * 1.15
    chart = {k: ' '.join(
        (f'{50 + i / max(1, len(series) - 1) * 1000:.2f},{235 - r[k] / max_value * 200:.2f}' for i, r in enumerate(series)),
    ) for k in [
        'actual',
        'predicted',
        'baseline',
    ]}
    return dict(
        **legacy_context(s, cargo, base, chosen, rows, list(reversed([e for e in s['cargoEvents'] if e['cargoId'] == cid]))),
        chart_ticks=[dict(y=235 - i * 50, label=max_value * i / 4, text_y=240 - i * 50) for i in range(5)],
        chart_dates=[dict(x=50 + i / max(1, len(series) - 1) * 1000, at=r['at']) for i, r in enumerate(series) if i % 12 == 0],
        s=s,
        page=page,
        title=TITLES[page][0],
        subtitle=TITLES[page][1],
        pages=PAGES,
        page_index=list(TITLES).index(page) + 1,
        cargo=cargo,
        base=base,
        chosen=chosen,
        forecasts=forecasts,
        recommended=recommended,
        rows=rows,
        risk=risk,
        pending=pending,
        pack=pack,
        application=application,
        pack_form=pack_form,
        declaration_form=declaration_form,
        scenario_form=scenario_form,
        event_form=event_form,
        stages=stages,
        stage_label=STAGE_LABELS[current_stage],
        events=list(reversed([e for e in s['cargoEvents'] if e['cargoId'] == cid])),
        stale=bool(
            (
                cargo.get('acceptedSlot')
                and base['departure'] is not None
                and cargo['acceptedSlot'] != f"{base['routeId']}:{int(base['departure'])}"
                and current_stage not in [
                    'sea',
                    'destination_port',
                    'delivered',
                ]
            ),
        ),
        can_accept=(
            chosen['feasible']
            and pack['status'] == 'validated'
            and (
                application
                or {}
            ).get('status') == 'ready_demo'
            and current_stage not in [
                'sea',
                'destination_port',
                'delivered',
            ]
        ),
        geographic_features=features,
        map_routes=routes,
        map_selected_route=next(r for r in routes if r['id'] == chosen['routeId']),
        map_approaches=approaches,
        map_land_segments=land_segments,
        map_ports=ports,
        port=port,
        research=research,
        categories=categories,
        category=category,
        chart=chart,
        errors=(
            errors
            or []
        ),
        action_key=str(uuid.uuid4()),
        scenario_result=current_result(request, version, cid),
        query=query,
        only_risk=only_risk,
        audit_valid=check_audit(s['audit']),
        live_config=browser_config(),
        optimization_config=public_config(),
        map_data=dict(
            ports=s['ports'],
            routes=routes,
            approaches=approaches,
            landSegments=land_segments,
            selectedRoute=chosen['routeId'],
            page=page,
            cargoId=cid,
            version=version,
        ),
        app_version=settings.APP_VERSION,
        project_folder=settings.BASE_DIR.name,
    )
