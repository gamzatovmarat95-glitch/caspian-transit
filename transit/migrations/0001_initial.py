from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(
        name='Workspace',
        fields=[
            ('id', models.BigAutoField(
                auto_created=True,
                primary_key=True,
                serialize=False,
                verbose_name='ID',
            )),
            ('owner', models.CharField(max_length=100, unique=True)),
            ('version', models.PositiveIntegerField(default=0)),
            ('state', models.JSONField()),
            ('updated_at', models.DateTimeField(auto_now=True)),
        ],
        options={'constraints': [models.CheckConstraint(
            condition=models.Q(('version__gte', 0)),
            name='workspace_version_nonnegative',
        )]},
    )]
