from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from django import template
from django.utils.safestring import mark_safe
register = template.Library()


@register.filter
def cargo_stage(cargo):
    from ..domain.tracking import STAGE_LABELS
    progress = cargo.get('progress') or {}
    return STAGE_LABELS.get(progress.get('stage', 'planned'), 'Планирование')

@register.filter

def when(value):
    if (
        value is None
        or value == ''
    ):
        return 'Нет окна'
    if isinstance(value, str) and 'T' in value:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        stamp = datetime.fromtimestamp(float(value) / 1000, timezone.utc)
    stamp = stamp.astimezone(ZoneInfo('Europe/Moscow'))
    months = ['янв.', 'февр.', 'мар.', 'апр.', 'мая', 'июн.', 'июл.', 'авг.', 'сент.', 'окт.', 'нояб.', 'дек.']
    return f'{stamp.day:02d} {months[stamp.month - 1]}, {stamp:%H:%M}'

@register.filter

def num(value, digits=1):
    if value is None:
        return '—'
    try:
        return f'{float(value):,.{int(digits)}f}'.replace(',', '\xa0').replace('.', ',').rstrip('0').rstrip(
            ',',
        ) if int(digits) else f'{float(value):,.0f}'.replace(',', '\xa0')
    except (ValueError, TypeError):
        return '—'

@register.filter

def money(value):
    return num(value, 0) + ' ₽'

@register.filter

def get(value, key):
    return value.get(key) if isinstance(value, dict) else None

@register.filter

def app_status(value):
    return {
        'draft': 'Черновик',
        'submitted': 'Отправлена',
        'needs_changes': 'Нужны исправления',
        'ready_demo': 'Готово · демо',
        'rejected_demo': 'Отклонено · демо',
    }.get(
        value,
        value,
    )

@register.filter

def sub(a, b):
    return (
        a
        or 0
    ) - (
        b
        or 0
    )

@register.filter

def hours(value):
    return value / 3600000 if value is not None else None


@register.filter
def thousands(value):
    return value / 1000 if value is not None else None


@register.filter
def host(value):
    return urlsplit(value).hostname or value


LUCIDE_ICONS = json.loads((Path(__file__).resolve().parents[1] / 'data/icons.json').read_text(encoding='utf-8'))
ICONS = {
    'compass': 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM16 8l-3 5-5 3 3-5 5-3Z',
    'container': 'M3 6h18v14H3zM7 6v14M12 6v14M17 6v14M5 3h14',
    'radio': 'M8 8a6 6 0 0 0 0 8M16 8a6 6 0 0 1 0 8M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14M12 10v11M10 10h4v4h-4z',
    'sliders': 'M4 5h16M4 12h16M4 19h16M8 3v4M16 10v4M10 17v4',
    'file': 'M14 2H5v20h14V7l-5-5ZM14 2v5h5M8 12h8M8 16h5',
    'chart': 'M4 3v17h17M7 14l4-5 4 3 5-7',
    'clock': 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7v6l4 2',
    'database': 'M3 6c0-4 18-4 18 0s-18 4-18 0ZM3 6v12c0 4 18 4 18 0V6M3 12c0 4 18 4 18 0',
    'ship': 'M3 12l9-4 9 4-3 7H6l-3-7ZM8 10V5h8v5M12 2v3M3 22c3-3 6 3 9 0s6 3 9 0',
    'download': 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
    'arrow': 'M4 12h16m-6-6 6 6-6 6',
    'play': 'M8 5l11 7-11 7Z',
    'refresh': 'M20 7a9 9 0 1 0 1 9M20 3v5h-5',
    'help': 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM9 9a3 3 0 1 1 4 3c-1 1-1 1-1 2M12 17h.01',
    'check': 'M4 12l5 5L20 6',
    'alert': 'M12 3 2 21h20L12 3ZM12 9v5M12 17h.01',
    'leaf': 'M20 3C5 2 2 10 6 16s15 2 14-13ZM5 20 16 9',
    'truck': 'M2 6h13v11H2zM15 10h4l3 4v3h-7M7 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM18 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z',
    'rail': 'M6 3h12v14H6zM6 9h12M9 3v6M7 21l2-4m8 4-2-4M9 13h.01M15 13h.01',
    'port': 'M12 3v15m-4-6H4c0 9 16 9 16 0h-4M8 7h8M10 3h4',
    'sea': 'M2 8c4-5 6 5 10 0s6 5 10 0M2 14c4-5 6 5 10 0s6 5 10 0M2 20c4-5 6 5 10 0s6 5 10 0',
    'close': 'M5 5l14 14M19 5 5 19',
    'search': 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM15 15l6 6',
    'external': 'M14 3h7v7M21 3l-11 11M10 5H3v16h16v-7',
    'wind': 'M2 8h12a3 3 0 1 0-3-3M2 12h17a3 3 0 1 1-3 3M2 17h7',
}

@register.simple_tag

def icon(name, size=18):
    if name in LUCIDE_ICONS:
        value = re.sub(r'(width|height)="18"', lambda match: match.group(1) + f'="{int(size)}"', LUCIDE_ICONS[name], count=2)
        return mark_safe(value)
    path = ICONS.get(name, ICONS['compass'])
    size = int(size)
    return mark_safe(
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{path}"/></svg>',
    )
