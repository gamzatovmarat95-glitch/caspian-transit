from django import forms


class PackForm(forms.Form):
    invoice = forms.CharField(
        label='Номер инвойса',
        max_length=100,
        required=False,
    )
    packingList = forms.CharField(
        label='Упаковочный лист',
        max_length=100,
        required=False,
    )
    hsCode = forms.CharField(
        label='Код товара · формат демо',
        max_length=30,
        required=False,
    )
    consignee = forms.CharField(
        label='Получатель',
        max_length=200,
        required=False,
    )
    massTon = forms.FloatField(
        label='Масса, т',
        min_value=0,
        max_value=100,
    )
    reference = forms.CharField(
        label='Референс партии',
        max_length=100,
        required=False,
    )


class DeclarationForm(forms.Form):
    originCountry = forms.ChoiceField(
        label='Страна отправления',
        choices=[('RU', 'Россия · RU'), ('KZ', 'Казахстан · вне демо-коридора')],
        required=False,
    )
    destinationCountry = forms.ChoiceField(
        label='Страна назначения',
        choices=[('IR', 'Иран · IR'), ('KZ', 'Казахстан · вне демо-коридора')],
        required=False,
    )
    transportDocument = forms.CharField(
        label='Транспортный документ',
        max_length=100,
        required=False,
    )
    originCertificate = forms.CharField(
        label='Документ о происхождении · правило демо',
        max_length=100,
        required=False,
    )
    description = forms.CharField(
        label='Описание партии',
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
    )
    declaredMassTon = forms.FloatField(
        label='Масса в декларации, т',
        min_value=0,
        max_value=100,
    )
    declaredValueRub = forms.FloatField(
        label='Стоимость партии, ₽',
        min_value=0,
        max_value=1000000000000,
    )


class ScenarioForm(forms.Form):
    portId = forms.ChoiceField(
        label='Порт',
        choices=[
            ('olya', 'Оля · Россия'),
            ('makhachkala', 'Махачкала · Россия'),
            ('anzali', 'Энзели · Иран'),
            ('amirabad', 'Амирабад · Иран'),
        ],
    )
    queue = forms.IntegerField(
        label='Очередь, условных партий',
        min_value=0,
        max_value=50,
        widget=forms.NumberInput(attrs={'type': 'range', 'min': 0, 'max': 50, 'step': 1}),
    )
    wind = forms.FloatField(
        label='Ветер, м/с',
        min_value=0,
        max_value=35,
        widget=forms.NumberInput(attrs={'type': 'range', 'min': 0, 'max': 35, 'step': 'any'}),
    )
    closureHours = forms.FloatField(
        label='Ограничение окна, ч',
        min_value=0,
        max_value=72,
        widget=forms.NumberInput(attrs={'type': 'range', 'min': 0, 'max': 72, 'step': 1}),
    )


class EventForm(forms.Form):
    from .domain.tracking import EVENT_LABELS
    kind = forms.ChoiceField(label='Событие', choices=EVENT_LABELS.items())
    atHours = forms.FloatField(
        label='Часы от начала сценария',
        min_value=0,
        max_value=240,
    )
    delayHours = forms.FloatField(
        label='Дополнительная задержка, ч',
        min_value=0,
        max_value=72,
        required=False,
    )
    queueUnits = forms.IntegerField(
        label='Очередь, партий',
        min_value=0,
        max_value=50,
        required=False,
    )
    holdHours = forms.FloatField(
        label='Длительность ограничения, ч',
        min_value=0,
        max_value=72,
        required=False,
    )
