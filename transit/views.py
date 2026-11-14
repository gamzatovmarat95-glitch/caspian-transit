from pathlib import Path
import copy
import json
import re
import uuid
from urllib.request import urlopen
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.db import DatabaseError
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect, Http404
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET
from .store import read_workspace, mutate
from .domain.engine import snapshot
from .domain.integrity import now_iso, digest, verify_signature, check_audit, technical_gateway
from .domain.clearance import verify_clearance, clearance_gateway, document_fields
from .domain.actions import ActionError, validate_fields, validate_declaration
from .domain.model import history_csv
from .presentation import context_for, TITLES
from .forms import PackForm, DeclarationForm, ScenarioForm, EventForm
from .accounts import membership, can_write


def response(value, status=200):
    r = JsonResponse(
        value,
        status=status,
        json_dumps_params={
            'ensure_ascii': False,
            'allow_nan': False,
        },
    )
    r['Cache-Control'] = 'no-store'
    r['Vary'] = 'Cookie'
    return r


def owner(request):
    if request.user.is_authenticated:
        member = membership(request)
        return member.workspace.owner if member else None
    return request.session.get('demo_owner')


def denied():
    return response({'error': 'Нужно войти в рабочее пространство'}, 401)


def local(request):
    return request.META.get('REMOTE_ADDR') in ('127.0.0.1', '::1')

@require_GET

def start_session(request):
    if not local(request):
        return HttpResponse('Демонстрационный вход доступен только локально', status=403)
    request.session.cycle_key()
    request.session['demo_owner'] = 'local-demo'
    read_workspace('local-demo')
    target = request.GET.get('return_to', '/')
    if (
        not target.startswith('/')
        or target.startswith('//')
        or '\\' in target
    ):
        target = '/'
    r = HttpResponseRedirect(target)
    r['Cache-Control'] = 'no-store'
    return r

@ensure_csrf_cookie

def index(request):
    if not owner(request):
        return render(request, 'transit/login.html')
    page = request.GET.get('page', 'overview')
    if page not in TITLES:
        raise Http404()
    errors = []
    status = 200
    if request.method == 'POST':
        if not can_write(request):
            return HttpResponse('Наблюдателю доступно только чтение', status=403)
        try:
            data = form_action(request)
            before = None
            if data['type'] == 'scenario':
                from .domain.engine import snapshot
                state, version = read_workspace(owner(request))
                before = snapshot(state, version)
            after = mutate(owner(request), data)
            if before is not None:
                from .scenario_results import summarize
                request.session['scenario_result'] = summarize(before, after, data.get('cargoId') or before['cargo'][0]['id'])
                request.session['scenario_result_owner'] = owner(request)
            messages.success(request, 'Изменения сохранены')
            params = {
                'page': page,
                'cargo': request.POST.get('cargoId', request.GET.get('cargo', 'CSP-1042')),
            }
            if data['type'] == 'accept':
                params['route'] = data['routeId']
            if (
                data['type'] == 'scenario'
                and data.get('portId')
            ):
                params['port'] = data['portId']
            return HttpResponseRedirect('/?' + urlencode(params))
        except ActionError as e:
            errors = (
                e.errors
                or [str(e)]
            )
            status = e.status
        except ValueError as e:
            errors = [str(e) or 'Проверьте параметры формы']
            status = 400
        except TypeError:
            errors = ['Проверьте параметры формы']
            status = 400
        except DatabaseError:
            errors = ['База данных временно недоступна']
            status = 503
    elif request.method != 'GET':
        return HttpResponse(status=405)
    state, version = read_workspace(owner(request))
    r = render(
        request,
        'transit/base.html',
        context_for(
            request,
            state,
            version,
            page,
            errors,
        ),
        status=status,
    )
    r['Cache-Control'] = 'no-store'
    return r


def form_action(request):
    p = request.POST
    action = p.get('type')
    data = dict(
        type=action,
        version=int(p.get('version', '-1')),
        key=p.get('key', ''),
        cargoId=p.get('cargoId', ''),
    )
    cls = {
        'document': PackForm,
        'clearance_submit': DeclarationForm,
        'cargo_event': EventForm,
    }.get(
        action,
    )
    if (
        action == 'scenario'
        and p.get('name') == 'custom'
    ):
        cls = ScenarioForm
    if cls:
        form = cls(p)
        if not form.is_valid():
            raise ActionError(
                'Исправьте поля формы',
                422,
                [f'{form.fields[k].label}: {e}' for k, v in form.errors.items() for e in v],
            )
        cleaned = {k: v for k, v in form.cleaned_data.items() if v is not None}
        if action == 'document':
            data.update(pack=cleaned, submit=p.get('submit') == '1')
        elif action == 'clearance_submit':
            data['declaration'] = cleaned
        else:
            data.update(cleaned)
    if action == 'scenario':
        data['name'] = p.get('name', '')
    if action == 'accept':
        data['routeId'] = p.get('routeId', '')
    if action == 'history':
        file = request.FILES.get('history')
        if (
            not file
            or file.size > 1200000
        ):
            raise ActionError('Выберите CSV до 1,2 МБ')
        data['csv'] = file.read().decode('utf-8-sig')
    return data


def parse_json(request, limit):
    raw = request.body
    if len(raw) > limit:
        raise ActionError('Слишком большой запрос', 413)

    def reject(v):
        raise ValueError('Нечисловое значение JSON')
    try:
        return json.loads(raw, parse_constant=reject)
    except (ValueError, UnicodeDecodeError):
        raise ActionError('Неверный JSON')


def workspace_api(request):
    user = owner(request)
    if not user:
        return denied()
    try:
        state, version = read_workspace(user)
        if request.method == 'GET':
            return response(snapshot(state, version))
        if request.method != 'POST':
            return response({'error': 'Метод недоступен'}, 405)
        if not can_write(request):
            return response({'error': 'Наблюдателю доступно только чтение'}, 403)
        if (
            request.headers.get('Origin') != request.scheme + '://' + request.get_host()
            or request.headers.get('X-Caspian-Request') != 'workspace'
        ):
            return response({'error': 'Недопустимый источник запроса'}, 403)
        return response(mutate(user, parse_json(request, 1250000)))
    except ActionError as e:
        return response({
            'error': str(e),
            **({'errors': e.errors} if e.errors else {}),
        }, e.status)
    except ValueError as e:
        return response({'error': str(e)}, 400)
    except DatabaseError:
        return response(
            {'error': 'Рабочее пространство недоступно. Проверьте локальный запуск и миграцию базы.'},
            503,
        )

@require_GET

def health(request):
    from caspian.runtime import installation_id
    return response(
        {
            'app': 'caspian-transit',
            'version': settings.APP_VERSION,
            'framework': 'Django',
            'instance': installation_id(settings.BASE_DIR, settings.DATABASES['default']['NAME']),
            'purpose': 'hackathon demonstration',
        },
    )

@require_GET

def map_config(request):
    if not owner(request):
        return denied()
    key = settings.YANDEX_MAPS_API_KEY
    r = response(
        {
            'provider': 'yandex',
            'apiKey': key if re.fullmatch('[a-zA-Z0-9_-]{16,160}', key) else None,
        },
    )
    r['Cache-Control'] = 'private, no-store'
    return r

@require_GET

def receipt(request):
    if not owner(request):
        return denied()
    state, _ = read_workspace(owner(request))
    pack = state['packs'].get(request.GET.get('cargoId', ''))
    if (
        not pack
        or not pack.get('receipt')
    ):
        return response({'error': 'Нет квитанции'}, 404)
    body = {k: v for k, v in pack['receipt'].items() if k != 'signature'}
    return response(
        dict(
            hashValid=digest({
                **document_fields(pack),
                'status': 'draft',
            }) == body['hash'],
            signatureValid=verify_signature(
                body,
                pack['receipt']['signature'],
                settings.GATEWAY_SECRET,
            ),
            auditChainValid=check_audit(state['audit']),
            note='Техническая проверка демонстрационного шлюза. Не решение таможни.',
        ),
    )

@csrf_exempt

def clearance(request):
    if request.method == 'GET':
        if not owner(request):
            return denied()
        state, _ = read_workspace(owner(request))
        cid = request.GET.get('cargoId', '')
        app = state.get('clearances', {}).get(cid)
        if not app:
            return response({'error': 'Заявка не найдена'}, 404)
        return response(
            {
                **verify_clearance(
                    app,
                    state['packs'][cid],
                    settings.GATEWAY_SECRET,
                ),
                'kind': 'demo_preclearance_only',
            },
        )
    if request.method != 'POST':
        return response({'error': 'Метод недоступен'}, 405)
    try:
        p = parse_json(request, 16000)
        if set(p) != set([
            'cargo',
            'pack',
            'declaration',
            'revision',
            'at',
            'nonce',
        ]):
            raise ValueError()
        validate_fields(
            p['cargo'],
            {
                'id': 40,
                'name': 200,
            },
            {'massTon': 100},
        )
        validate_fields(
            p['pack'],
            {
                'invoice': 100,
                'packingList': 100,
                'hsCode': 30,
                'consignee': 200,
                'reference': 100,
            },
            {'massTon': 100},
        )
        validate_declaration(p['declaration'])
        if (
            type(p['revision']) is not int
            or not 1 <= p['revision'] <= 1000
        ):
            raise ValueError()
        result = clearance_gateway(
            p,
            request.headers.get('X-Caspian-Signature', ''),
            settings.GATEWAY_SECRET,
        )
        return response({
            'kind': 'demo_preclearance_only',
            **result,
        })
    except ActionError as e:
        if e.status == 413:
            return response({'error': str(e)}, 413)
        return response({'error': 'Invalid or expired service request'}, 401)
    except (ValueError, KeyError, TypeError):
        return response({'error': 'Invalid or expired service request'}, 401)

@csrf_exempt

def gateway(request):
    if request.method != 'POST':
        return response({'error': 'Метод недоступен'}, 405)
    try:
        p = parse_json(request, 16000)
        if (
            not isinstance(p, dict)
            or set(p) != set([
                'cargoId',
                'pack',
                'at',
                'nonce',
            ])
        ):
            raise ValueError()
        return response(
            technical_gateway(
                p,
                request.headers.get('X-Caspian-Signature', ''),
                settings.GATEWAY_SECRET,
            ),
        )
    except ActionError as e:
        if e.status == 413:
            return response({'error': str(e)}, 413)
        return response({'error': 'Invalid or expired service request'}, 401)
    except (ValueError, KeyError, TypeError):
        return response({'error': 'Invalid or expired service request'}, 401)

@require_GET

def export(request):
    if not owner(request):
        return denied()
    state, version = read_workspace(owner(request))
    if request.GET.get('type') == 'pack':
        cargo_id = request.GET.get('cargo', '')
        pack = state['packs'].get(cargo_id)
        if not pack:
            return response({'error': 'Партия не найдена'}, 404)
        r = HttpResponse(json.dumps(document_fields(pack), ensure_ascii=False, indent=2, allow_nan=False), content_type='application/json; charset=utf-8')
        name = f'caspian-pack-{cargo_id}.json'
    elif request.GET.get('type') == 'history':
        r = HttpResponse(history_csv(state['history']), content_type='text/csv; charset=utf-8')
        name = 'caspian-history.csv'
    else:
        value = dict(
            exportedAt=now_iso(),
            scope='Demonstration, not real transport/customs execution',
            auditChainValid=check_audit(state['audit']),
            **snapshot(state, version),
        )
        r = HttpResponse(
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            content_type='application/json; charset=utf-8',
        )
        name = 'caspian-decision-report.json'
    r['Content-Disposition'] = f'attachment; filename="{name}"'
    r['Cache-Control'] = 'no-store'
    return r

@require_GET

def weather(request):
    if not owner(request):
        return denied()
    reference = json.loads(
        (settings.BASE_DIR / 'transit/data/weather-reference.json').read_text(encoding='utf-8'),
    )
    try:
        with urlopen(reference['url'], timeout=7) as source:
            raw = json.load(source)
        if (
            not isinstance(raw, list)
            or len(raw) != len(reference['ports'])
        ):
            raise ValueError()
        ports = []
        for i, row in enumerate(raw):
            if row['hourly_units']['wind_speed_10m'] != 'm/s':
                raise ValueError()
            hourly = row['hourly']
            points = []
            for j, t in enumerate(hourly['time']):
                w = hourly['wind_speed_10m'][j]
                g = hourly['wind_gusts_10m'][j]
                if (
                    type(t) not in (int, float)
                    or (
                        w is not None
                        and type(w) not in (int, float)
                    )
                    or (
                        g is not None
                        and type(g) not in (int, float)
                    )
                ):
                    raise ValueError()
                points.append(dict(
                    at=t * 1000,
                    windMs=w,
                    gustMs=g,
                ))
            ports.append(
                {
                    **reference['ports'][i],
                    'gridLat': row['latitude'],
                    'gridLon': row['longitude'],
                    'points': points,
                },
            )
        return response({
            **reference,
            'fetchedAt': now_iso(),
            'ports': ports,
            'fallback': False,
        })
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return response(
            {
                **reference,
                'fallback': True,
                'note': 'Источник недоступен: сохранённый прогноз, учитывайте возраст и временной горизонт.',
            },
        )
