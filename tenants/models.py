from django.conf import settings
from django.db import models
from django.urls import reverse
from django_tenants.models import TenantMixin, DomainMixin


class Client(TenantMixin):
    PLAN_SHARED = 'shared'
    PLAN_ENTERPRISE = 'enterprise'
    PLAN_CHOICES = [
        (PLAN_SHARED, 'Shared'),
        (PLAN_ENTERPRISE, 'Enterprise'),
    ]

    name = models.CharField(max_length=120)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_SHARED)
    is_active = models.BooleanField(default=True)
    created_on = models.DateField(auto_now_add=True)

    auto_create_schema = True

    def __str__(self):
        return f"{self.name} ({self.schema_name})"

    def get_absolute_url(self):
        return reverse("tenants:detail", kwargs={"pk": self.pk})


class Domain(DomainMixin):
    pass


class TenantMembership(models.Model):
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tenant_memberships')
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('tenant', 'user')
        verbose_name = 'Tenant membership'
        verbose_name_plural = 'Tenant memberships'

    def __str__(self):
        return f"{self.user} -> {self.tenant}"
