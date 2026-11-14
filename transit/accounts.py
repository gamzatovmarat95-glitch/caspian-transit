"""Local accounts and explicit workspace membership; no external identity service."""
from django.contrib import messages
from django.contrib.auth import login, logout, get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST
from .models import Membership, Workspace
from .domain.sample import seed_workspace


def membership(request):
    if not request.user.is_authenticated:
        return None
    members = Membership.objects.select_related('workspace').filter(user=request.user)
    return members.filter(workspace_id=request.session.get('active_workspace')).first() or members.order_by('pk').first()


def can_write(request):
    member = membership(request)
    return member.role in ('owner', 'operator') if member else not request.user.is_authenticated and bool(request.session.get('demo_owner'))


@require_http_methods(['GET', 'POST'])
def sign_in(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        request.session.pop('demo_owner', None)
        return redirect('/')
    return render(request, 'transit/account.html', {'form': form, 'mode': 'login'})


@require_http_methods(['GET', 'POST'])
def register(request):
    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            workspace = Workspace.objects.create(owner=f'account:{user.pk}', state=seed_workspace())
            Membership.objects.create(user=user, workspace=workspace, role='owner')
        login(request, user)
        request.session.pop('demo_owner', None)
        request.session['active_workspace'] = workspace.pk
        messages.info(request, 'Создано отдельное пространство с учебными примерами. Свои партии добавляйте в разделе «Управление».')
        return redirect('/')
    return render(request, 'transit/account.html', {'form': form, 'mode': 'register'})


@require_POST
def sign_out(request):
    logout(request)
    return redirect('/')


@require_http_methods(['GET', 'POST'])
def team(request):
    if not request.user.is_authenticated:
        return redirect('/accounts/login')
    current = membership(request)
    errors = []
    if request.method == 'POST':
        if request.POST.get('action') == 'switch':
            selected = Membership.objects.filter(user=request.user, workspace_id=request.POST.get('workspace')).first()
            if not selected:
                return HttpResponseForbidden('Нет доступа к пространству')
            request.session['active_workspace'] = selected.workspace_id
            return redirect('/accounts/team')
        if not current or current.role != 'owner':
            return HttpResponseForbidden('Управление доступом разрешено владельцу')
        role = request.POST.get('role')
        user = get_user_model().objects.filter(username=request.POST.get('username', '')).first()
        if not user or role not in ('operator', 'viewer'):
            errors.append('Укажите существующий аккаунт и роль логиста или наблюдателя.')
        elif user.pk == request.user.pk or Membership.objects.filter(user=user, workspace=current.workspace, role='owner').exists():
            errors.append('Роль владельца менять нельзя.')
        elif request.POST.get('action') == 'remove':
            Membership.objects.filter(user=user, workspace=current.workspace).exclude(role='owner').delete()
            return redirect('/accounts/team')
        else:
            Membership.objects.update_or_create(user=user, workspace=current.workspace, defaults={'role': role})
            return redirect('/accounts/team')
    return render(request, 'transit/team.html', {
        'member': current, 'members': current.workspace.members.select_related('user') if current else [],
        'workspaces': Membership.objects.select_related('workspace').filter(user=request.user), 'errors': errors,
    })
