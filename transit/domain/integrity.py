"""Canonical JSON interoperable with the original JS HMAC protocol."""
import hashlib
import hmac
import json
import math
import re
import time
import uuid
from .sample import iso, milliseconds


def canonical(value):
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, str):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(',', ':'),
        )
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return 'null'
        if value == 0:
            return '0'
        if (
            value.is_integer()
            and abs(value) < 1e+21
        ):
            return str(int(value))
        result = repr(value)
        if 'e' in result:
            mantissa, exponent = result.split('e')
            power = int(exponent)
            if -6 <= power < 21:
                from decimal import Decimal
                return format(Decimal(result), 'f')
            result = mantissa + 'e' + ('+' if power >= 0 else '-') + str(abs(power))
        return result
    if isinstance(value, list):
        return '[' + ','.join((canonical(v) for v in value)) + ']'
    if isinstance(value, dict):
        return '{' + ','.join((canonical(k) + ':' + canonical(value[k]) for k in sorted(value))) + '}'
    raise TypeError('Unsupported canonical JSON value')


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sign(value, secret):
    return hmac.new(
        secret.encode(),
        canonical(value).encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(value, signature, secret):
    return bool(
        (
            isinstance(signature, str)
            and re.fullmatch('[a-f0-9]{64}', signature)
            and hmac.compare_digest(sign(value, secret), signature)
        ),
    )


def now_iso():
    return iso(time.time() * 1000)


def append_audit(events, cargo_id, action, detail):
    event = dict(
        id=str(uuid.uuid4()),
        at=now_iso(),
        cargoId=cargo_id,
        action=action,
        detail=detail,
        previousHash=events[-1]['hash'] if events else 'GENESIS',
    )
    events.append({
        **event,
        'hash': digest(event),
    })


def check_audit(events):
    previous = 'GENESIS'
    for event in events:
        data = {k: v for k, v in event.items() if k != 'hash'}
        if (
            data.get('previousHash') != previous
            or digest(data) != event.get('hash')
        ):
            return False
        previous = event['hash']
    return True


def technical_gateway(payload, signature, secret, now=None):
    if not verify_signature(
        payload,
        signature,
        secret,
    ):
        raise ValueError('Недействительная подпись запроса')
    try:
        stamp = milliseconds(payload['at'])
    except (ValueError, KeyError):
        raise ValueError('Время запроса вне допустимого окна')
    if abs((time.time() * 1000 if now is None else now) - stamp) > 300000:
        raise ValueError('Время запроса вне допустимого окна')
    if (
        not re.fullmatch(
            'CSP-\\d+',
            payload.get('cargoId', ''),
            flags=re.ASCII,
        )
        or not re.fullmatch('[a-zA-Z0-9-]{8,64}', payload.get('nonce', ''))
    ):
        raise ValueError('Неверный референс пакета')
    pack = payload.get('pack')
    if (
        not isinstance(pack, dict)
        or any(
            ((
                not isinstance(pack.get(k), str)
                or not pack[k].strip()
            ) for k in [
                'invoice',
                'packingList',
                'consignee',
            ]),
        )
        or not re.fullmatch(
            '\\d{10}',
            str(pack.get('hsCode', '')),
            flags=re.ASCII,
        )
        or type(pack.get('massTon')) not in (int, float)
        or not math.isfinite(pack['massTon'])
        or not 0 < pack['massTon'] <= 100
        or pack.get('reference') != 'DEMO-' + payload['cargoId'][4:]
    ):
        raise ValueError('Неполный технический пакет')
    body = dict(
        id='DEMO-' + digest(payload)[:16],
        hash=digest(pack),
        submittedAt=payload['at'],
        gateway='Caspian technical-validation demo gateway',
    )
    return {
        **body,
        'signature': sign(body, secret),
    }
