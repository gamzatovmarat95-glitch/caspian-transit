"""Ridge least squares with chronological train/calibration/test groups."""
import math
import re
from .sample import PORTS, milliseconds, iso
FEATURE_NAMES = [
    'константа',
    'очередь',
    'ветер выше 7 м/с²',
    'обработка',
    'Махачкала',
    'Энзели',
    'Амирабад',
]


def features(r):
    return [
        1,
        r['queueUnits'],
        max(0, r['windMs'] - 7) ** 2,
        r['handlingHours'],
        *[int(p == r['portId']) for p in PORTS[1:]],
    ]


def solve(a, b):
    n = len(b)
    m = [[*r, b[i]] for i, r in enumerate(a)]
    for k in range(n):
        pivot = max(range(k, n), key=lambda j: abs(m[j][k]))
        m[k], m[pivot] = (m[pivot], m[k])
        if abs(m[k][k]) < 1e-10:
            raise ValueError('История не позволяет построить устойчивую модель')
        divisor = m[k][k]
        for c in range(k, n + 1):
            m[k][c] /= divisor
        for j in range(n):
            if j != k:
                factor = m[j][k]
                for c in range(k, n + 1):
                    m[j][c] -= factor * m[k][c]
    return [r[n] for r in m]


def mean(v):
    return sum(v) / len(v)


class PortModel:

    def __init__(self, input_rows, origin):
        if len(input_rows) < 80:
            raise ValueError('Для временной проверки нужно минимум 80 наблюдений')
        rows = sorted(input_rows, key=lambda r: r['at'])
        dates = sorted({r['at'] for r in rows})
        if len(dates) < 20:
            raise ValueError('Нужно минимум 20 разных временных отметок')
        cut1 = dates[math.floor(len(dates) * 0.7)]
        cut2 = dates[math.floor(len(dates) * 0.85)]
        train = [r for r in rows if r['at'] < cut1]
        calibration = [r for r in rows if cut1 <= r['at'] < cut2]
        test = [r for r in rows if r['at'] >= cut2]
        if (
            len(train) < 40
            or len(calibration) < 10
            or len(test) < 10
        ):
            raise ValueError('Недостаточно наблюдений в временных выборках')
        d = 7
        a = [[0.0] * d for _ in range(d)]
        b = [0.0] * d
        for r in train:
            x = features(r)
            for j in range(d):
                b[j] += x[j] * r['delayHours']
                for k in range(d):
                    a[j][k] += x[j] * x[k]
        for j in range(1, d):
            a[j][j] += 0.01
        self.beta = solve(a, b)
        self.bounds = {k: (min((r[k] for r in train)), max((r[k] for r in train))) for k in [
            'queueUnits',
            'windMs',
            'handlingHours',
        ]}
        self.trained_ports = {r['portId'] for r in train}
        baselines = {p: mean(
            (
                [r['delayHours'] for r in train if r['portId'] == p]
                or [r['delayHours'] for r in train]
            ),
        ) for p in PORTS}
        residuals = sorted((abs(r['delayHours'] - self.predict(r)) for r in calibration))
        self.radius = residuals[min(len(residuals) - 1, math.ceil((len(residuals) + 1) * 0.9) - 1)]
        errors = [self.predict(r) - r['delayHours'] for r in test]
        self.report = dict(
            origin=origin,
            trainN=len(train),
            calibrationN=len(calibration),
            testN=len(test),
            trainUntil=train[-1]['at'],
            testFrom=test[0]['at'],
            testUntil=test[-1]['at'],
            mae=mean([abs(e) for e in errors]),
            baselineMae=mean([abs(baselines[r['portId']] - r['delayHours']) for r in test]),
            rmse=math.sqrt(mean([e * e for e in errors])),
            intervalCoverage=sum((abs(e) <= self.radius for e in errors)) / len(test),
            intervalRadius=self.radius,
            features=FEATURE_NAMES,
            series=[dict(
                at=r['at'],
                actual=r['delayHours'],
                predicted=self.predict(r),
                baseline=baselines[r['portId']],
                portId=r['portId'],
            ) for r in test[-64:]],
            warnings=[
                'Проверка на синтетической истории; точность на реальных перевозках не установлена.' if origin == 'synthetic' else 'История загружена пользователем; происхождение и репрезентативность требуют проверки.',
                'Интервал откалиброван на отдельной временной выборке. Он не является гарантией для новой среды.',
                'В прогнозе используются известные на момент оценки признаки; плановые погодные сценарии не являются наблюдениями порта.',
            ],
        )

    def predict(self, row):
        return max(0, sum((x * self.beta[i] for i, x in enumerate(features(row)))))

    def is_supported(self, row):
        return (
            row['portId'] in self.trained_ports
            and all((lo - 1e-09 <= row[k] <= hi + 1e-09 for k, (lo, hi) in self.bounds.items()))
        )


def fit_model(rows, origin):
    return PortModel(rows, origin)


def parse_history_csv(text, cutoff_time=math.inf):
    if len(text) > 1200000:
        raise ValueError('CSV больше 1,2 МБ')
    lines = text.lstrip('\ufeff').strip().splitlines()
    if len(lines) > 5001:
        raise ValueError('Максимум 5000 наблюдений')
    if (
        not lines
        or lines[0] != 'at,portId,queueUnits,windMs,handlingHours,delayHours'
    ):
        raise ValueError('Неверная схема CSV. Скачайте образец истории.')
    seen = set()
    rows = []
    for i, line in enumerate(lines[1:], 2):
        cols = line.split(',')
        if len(cols) != 6:
            raise ValueError(f'Строка {i}: нужно 6 полей без кавычек')
        at, port, *rest = cols
        try:
            stamp = milliseconds(at)
            if (
                not re.fullmatch('\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d(?:\\.\\d{3})?Z', at)
                or stamp >= cutoff_time
            ):
                raise ValueError()
        except (ValueError, OverflowError):
            raise ValueError(f'Строка {i}: время UTC должно быть раньше операционного снимка')
        try:
            if (
                port not in PORTS
                or any((not x.strip() for x in rest))
            ):
                raise ValueError()
            q, w, h, d = map(float, rest)
            if not all((math.isfinite(v) for v in (q, w, h, d))):
                raise ValueError()
        except ValueError:
            raise ValueError(f'Строка {i}: неизвестный порт или нечисловое значение')
        if not (
            0 <= q <= 100
            and 0 <= w <= 45
            and 0 <= h <= 48
            and 0 <= d <= 240
        ):
            raise ValueError(f'Строка {i}: значения вне допустимого диапазона')
        key = (stamp, port)
        if key in seen:
            raise ValueError(f'Строка {i}: повтор порта и времени')
        seen.add(key)
        rows.append(
            dict(
                at=iso(stamp),
                portId=port,
                queueUnits=q,
                windMs=w,
                handlingHours=h,
                delayHours=d,
            ),
        )
    return rows


def history_csv(rows):

    def num(x):
        return str(int(x)) if int(x) == x else str(x)
    return 'at,portId,queueUnits,windMs,handlingHours,delayHours\n' + '\n'.join(
        (','.join(
            [
                r['at'],
                r['portId'],
                num(r['queueUnits']),
                f"{r['windMs']:.4f}",
                f"{r['handlingHours']:.4f}",
                f"{r['delayHours']:.4f}",
            ],
        ) for r in rows),
    )
