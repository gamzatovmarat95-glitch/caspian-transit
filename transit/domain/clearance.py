from .integrity import digest, sign, verify_signature
from .sample import milliseconds
from .engine import find
import re
import time
import math
CLEARANCE_POLICY = 'CT-DEMO-2026.1'
PACK_FIELDS = [
    'invoice',
    'packingList',
    'hsCode',
    'consignee',
    'massTon',
    'reference',
]


def document_fields(pack):
    return {k: pack[k] for k in PACK_FIELDS}


def initial_declaration(cargo):
    return dict(
        originCountry='RU',
        destinationCountry='IR',
        transportDocument='',
        originCertificate='',
        description=cargo['name'],
        declaredMassTon=cargo['massTon'],
        declaredValueRub=0,
    )


def clearance_checks(cargo, pack, d):
    rules = [
        (
            'Поддерживаемый демонстрационный коридор',
            (
                d['originCountry'] == 'RU'
                and d['destinationCountry'] == 'IR'
            ),
            'Демо-модель покрывает только RU → IR; это ограничение прототипа, не запрет на перевозку.',
            'Коридор RU → IR поддерживается демо-моделью.',
        ),
        (
            'Инвойс и упаковочный лист',
            bool((
                pack['invoice'].strip()
                and pack['packingList'].strip()
            )),
            'Нужны реквизиты обоих документов.',
            'Реквизиты обоих документов указаны.',
        ),
        (
            'Транспортный документ',
            bool(d['transportDocument'].strip()),
            'Укажите демонстрационный номер транспортного документа.',
            'Реквизит транспортного документа указан.',
        ),
        (
            'Описание партии',
            len(d['description'].strip()) >= 5,
            'Добавьте описание партии не короче 5 символов.',
            'Описание партии заполнено.',
        ),
        (
            'Согласованность массы',
            (
                math.isfinite(d['declaredMassTon'])
                and abs(d['declaredMassTon'] - cargo['massTon']) <= 0.01
                and abs(pack['massTon'] - cargo['massTon']) <= 0.01
            ),
            'Масса в декларации, пакете и карточке груза должна совпадать.',
            'Масса согласована между тремя записями.',
        ),
        (
            'Стоимость для демонстрационной декларации',
            (
                math.isfinite(d['declaredValueRub'])
                and d['declaredValueRub'] > 0
            ),
            'Укажите положительную стоимость партии в рублях. Пошлины здесь не рассчитываются.',
            'Положительная стоимость указана; это не расчёт пошлины.',
        ),
        (
            'Документ о происхождении · правило демо',
            bool(d['originCertificate'].strip()),
            'В выбранном учебном процессе нужен номер документа о происхождении. Это условное правило демо, не правовое требование.',
            'Реквизит документа о происхождении указан по условному правилу демо.',
        ),
        (
            'Формат кода и референс партии',
            (
                bool(re.fullmatch(
                    '\\d{10}',
                    pack['hsCode'],
                    flags=re.ASCII,
                ))
                and pack['reference'] == 'DEMO-' + cargo['id'][4:]
                and bool(pack['consignee'].strip())
            ),
            'Проверьте формат кода, референс и получателя. Классификация товара по праву не выполняется.',
            'Технический формат кода, референс и получатель согласованы.',
        ),
    ]
    return [dict(
        id=f'CT-{i:02}',
        label=label,
        passed=passed,
        message=success if passed else issue,
    ) for i, (label, passed, issue, success) in enumerate(rules, 1)]


def clearance_gateway(payload, signature, secret, now=None):
    if not verify_signature(
        payload,
        signature,
        secret,
    ):
        raise ValueError('Неверная подпись запроса демо-шлюза')
    try:
        stamp = milliseconds(payload['at'])
    except (KeyError, ValueError):
        raise ValueError('Запрос демо-шлюза просрочен')
    if abs((time.time() * 1000 if now is None else now) - stamp) > 300000:
        raise ValueError('Запрос демо-шлюза просрочен')
    if (
        not re.fullmatch(
            'CSP-\\d+',
            payload['cargo']['id'],
            flags=re.ASCII,
        )
        or not re.fullmatch('[a-zA-Z0-9-]{8,64}', payload['nonce'])
        or type(payload['revision']) is not int
        or payload['revision'] < 1
    ):
        raise ValueError('Неверный номер заявки')
    checks = clearance_checks(
        payload['cargo'],
        payload['pack'],
        payload['declaration'],
    )
    status = 'rejected_demo' if not checks[0]['passed'] else 'ready_demo' if all((c['passed'] for c in checks)) else 'needs_changes'
    body = dict(
        id='CT-DEMO-' + digest(payload)[:16],
        at=payload['at'],
        status=status,
        policy=CLEARANCE_POLICY,
        cargoId=payload['cargo']['id'],
        revision=payload['revision'],
        packageHash=digest(payload['pack']),
        declarationHash=digest(payload['declaration']),
        checksHash=digest(checks),
    )
    return dict(checks=checks, decision={
        **body,
        'signature': sign(body, secret),
    })


def submit_clearance(state, cargo_id, declaration, at):
    cargo = find(state['cargo'], cargo_id)
    pack = state['packs'].get(cargo_id)
    if (
        not cargo
        or not pack
    ):
        raise ValueError('Груз не найден')
    if pack['status'] != 'validated':
        raise ValueError('Сначала выполните техническую проверку реквизитов пакета')
    applications = state.setdefault('clearances', {})
    previous = applications.get(cargo_id, {})
    if previous.get('status') == 'submitted':
        raise ValueError('Заявка уже отправлена: дождитесь проверки')
    revision = previous.get('revision', 0) + 1
    package_hash = digest(document_fields(pack))
    application = dict(
        revision=revision,
        status='submitted',
        declaration=declaration,
        submittedPackHash=package_hash,
        submittedAt=at,
        checks=[],
        history=[*previous.get('history', []), dict(
            at=at,
            revision=revision,
            status='submitted',
            detail='Редакция отправлена в демонстрационный процесс проверки',
            packageHash=package_hash,
        )],
    )
    applications[cargo_id] = application
    return application


def review_clearance(state, cargo_id, nonce, secret, at):
    cargo = find(state['cargo'], cargo_id)
    app = state.get('clearances', {}).get(cargo_id)
    pack = state['packs'].get(cargo_id)
    if (
        not cargo
        or not app
        or not pack
        or app['status'] != 'submitted'
    ):
        raise ValueError('Нет отправленной редакции для проверки')
    if (
        pack['status'] != 'validated'
        or app['submittedPackHash'] != digest(document_fields(pack))
    ):
        raise ValueError('Пакет изменён после отправки: отправьте новую редакцию')
    payload = dict(
        cargo={k: cargo[k] for k in [
            'id',
            'name',
            'massTon',
        ]},
        pack=document_fields(pack),
        declaration=app['declaration'],
        revision=app['revision'],
        at=at,
        nonce=nonce,
    )
    result = clearance_gateway(
        payload,
        sign(payload, secret),
        secret,
        milliseconds(at),
    )
    app.update(
        checks=result['checks'],
        decision=result['decision'],
        status=result['decision']['status'],
    )
    detail = 'Все условные правила пройдены. Готово только в рамках демо; не является выпуском таможни.' if app['status'] == 'ready_demo' else ' '.join((c['message'] for c in app['checks'] if not c['passed']))
    app['history'].append(
        dict(
            at=at,
            revision=app['revision'],
            status=app['status'],
            detail=detail,
            packageHash=app['submittedPackHash'],
        ),
    )
    return app


def invalidate_clearance(state, cargo_id, at):
    app = state.get('clearances', {}).get(cargo_id)
    if (
        not app
        or app['status'] == 'draft'
    ):
        return
    pack = state['packs'][cargo_id]
    if (
        pack['status'] == 'validated'
        and app['submittedPackHash'] == digest(document_fields(pack))
    ):
        return
    app.update(status='draft', checks=[])
    app.pop('decision', None)
    app['history'].append(
        dict(
            at=at,
            revision=app['revision'],
            status='draft',
            detail='Реквизиты пакета изменены; прежняя проверка больше не применима',
            packageHash=digest(document_fields(pack)),
        ),
    )


def verify_clearance(app, pack, secret):
    if not app.get('decision'):
        return dict(signatureValid=False, contentsValid=False)
    body = {k: v for k, v in app['decision'].items() if k != 'signature'}
    return dict(
        signatureValid=verify_signature(
            body,
            app['decision']['signature'],
            secret,
        ),
        contentsValid=(
            app['status'] == body['status']
            and app['revision'] == body['revision']
            and body['packageHash'] == digest(document_fields(pack))
            and body['declarationHash'] == digest(app['declaration'])
            and body['checksHash'] == digest(app['checks'])
        ),
    )
