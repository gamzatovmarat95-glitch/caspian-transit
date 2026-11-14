"""Native consignment forms, backed by the same transactional domain as the API."""
import uuid
from datetime import datetime, timezone
from django import forms
from django.shortcuts import redirect, render
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from .accounts import can_write
from .domain.actions import ActionError
from .domain.engine import find
from .store import read_workspace, mutate


class ShipmentForm(forms.Form):
    name = forms.CharField(label='Название груза', max_length=200)
    customer = forms.CharField(label='Грузовладелец', max_length=200)
    externalReference = forms.CharField(label='Референс партии', max_length=100)
    massTon = forms.FloatField(label='Масса, т', min_value=0.001, max_value=100)
    readyAt = forms.DateTimeField(label='Готовность · московское время', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    dueAt = forms.DateTimeField(label='Срок доставки · московское время', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    plannedRoute = forms.ChoiceField(label='Планируемый маршрут')
    priority = forms.ChoiceField(label='Приоритет', choices=[('Обычный', 'Обычный'), ('Высокий', 'Высокий')])
    version = forms.IntegerField(widget=forms.HiddenInput)
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, routes, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plannedRoute'].choices = [(r['id'], r['name']) for r in routes]


@require_http_methods(['GET', 'POST'])
def shipments(request):
    from .views import owner
    workspace = owner(request)
    if not workspace:
        return redirect('/accounts/login')
    state, version = read_workspace(workspace)
    cid = request.GET.get('edit', '')
    cargo = find(state['cargo'], cid) if cid else None
    initial = dict(version=version, key=uuid.uuid4(), readyAt=datetime.fromtimestamp(state['baseTime']/1000, timezone.utc), dueAt=datetime.fromtimestamp(state['baseTime']/1000 + 120*3600, timezone.utc))
    if cargo:
        initial.update(cargo)
        initial.update({k: datetime.fromtimestamp(cargo[k]/1000, timezone.utc) for k in ('readyAt', 'dueAt')})
    form = ShipmentForm(request.POST if request.method == 'POST' else None, routes=state['routes'], initial=initial)
    status = 200
    if request.method == 'POST':
        if not can_write(request):
            return HttpResponseForbidden('Наблюдателю доступно только чтение')
        if form.is_valid():
            fields = {k: v for k, v in form.cleaned_data.items() if k not in ('version', 'key')}
            for key in ('readyAt', 'dueAt'):
                fields[key] = fields[key].timestamp()*1000
            data = dict(type='cargo_update' if cid else 'cargo_create', cargoId=cid, shipment=fields, version=form.cleaned_data['version'], key=str(form.cleaned_data['key']))
            try:
                result = mutate(workspace, data)
                selected = cid or next(c['id'] for c in result['cargo'] if c.get('externalReference') == fields['externalReference'])
                return redirect('/?page=cargo&cargo=' + selected)
            except ActionError as exc:
                form.add_error(None, str(exc))
                status = exc.status
        else:
            status = 400
    return render(request, 'transit/shipments.html', {'form': form, 'cargo_rows': state['cargo'], 'editing': cargo, 'can_write': can_write(request)}, status=status)
