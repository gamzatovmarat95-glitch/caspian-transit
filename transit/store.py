# SQLite uses BEGIN IMMEDIATE; select_for_update also supports a future PostgreSQL deployment.

from django.db import transaction
from django.conf import settings
from .models import Workspace
from .domain.sample import seed_workspace
from .domain.actions import ActionError, apply_action, validate_input
from .domain.engine import snapshot
from .domain.integrity import digest


def read_workspace(owner):
    row, _ = Workspace.objects.get_or_create(owner=owner, defaults={'state': seed_workspace()})
    return (row.state, row.version)


def mutate(owner, input):
    validate_input(input)
    with transaction.atomic():
        row = Workspace.objects.select_for_update().get(owner=owner)
        state = row.state
        if input['key'] in state.get('idempotency', {}):
            expected = state.get('idempotencyInputs', {}).get(input['key'])
            if expected != digest(input):
                raise ActionError('Этот ключ уже использован для другого или старого действия. Обновите страницу и повторите расчёт.', 409)
            return snapshot(state, row.version)
        if row.version != input['version']:
            raise ActionError(
                'Данные изменились в другой вкладке. Обновите экран и повторите действие.',
                409,
            )
        if (
            len(state['audit']) > 1000
            and input['type'] != 'reset'
        ):
            raise ActionError(
                'Демонстрационный журнал заполнен. Экспортируйте отчёт и сбросьте сценарий.',
                409,
            )
        state = apply_action(
            state,
            input,
            settings.GATEWAY_SECRET,
        )
        state.setdefault('idempotencyInputs', {})[input['key']] = digest(input)
        count = Workspace.objects.filter(pk=row.pk, version=row.version).update(
            state=state,
            version=row.version + 1,
        )
        if count != 1:
            raise ActionError(
                'Конфликт параллельных действий: изменения не применены. Обновите экран.',
                409,
            )
        return snapshot(state, row.version + 1)
