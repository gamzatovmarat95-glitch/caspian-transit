from django.db import models
from django.conf import settings


class Workspace(models.Model):
    owner = models.CharField(max_length=100, unique=True)
    version = models.PositiveIntegerField(default=0)
    state = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(version__gte=0),
            name='workspace_version_nonnegative',
        )]


class Membership(models.Model):
    """An account can collaborate in several independent workspaces."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='members')
    role = models.CharField(max_length=12, choices=[
        ('owner', 'Владелец'), ('operator', 'Логист'), ('viewer', 'Наблюдатель'),
    ])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'workspace'], name='unique_workspace_member'),
            models.CheckConstraint(condition=models.Q(role__in=['owner', 'operator', 'viewer']), name='valid_member_role'),
        ]
