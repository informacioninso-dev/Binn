from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from tenants.models import TenantMembership


class TenantAwareBackend(ModelBackend):
    """
    Allows username or email login and enforces tenant membership when
    authenticating against a tenant schema domain.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if password is None:
            return None

        UserModel = get_user_model()
        login_value = (username or kwargs.get(UserModel.USERNAME_FIELD) or "").strip()
        if not login_value:
            return None

        user = self._get_user_by_login(UserModel, login_value)
        if user is None:
            return None
        if not user.check_password(password):
            return None
        if not self.user_can_authenticate(user):
            return None

        tenant = getattr(request, "tenant", None) if request is not None else None
        if tenant is None or tenant.schema_name == settings.PUBLIC_SCHEMA_NAME:
            return user

        if not getattr(tenant, "is_active", True):
            return None

        if user.is_superuser:
            return user

        is_member = TenantMembership.objects.filter(
            tenant=tenant,
            user=user,
            is_active=True,
        ).exists()
        return user if is_member else None

    def _get_user_by_login(self, UserModel, login_value):
        username_lookup = {f"{UserModel.USERNAME_FIELD}__iexact": login_value}
        try:
            return UserModel._default_manager.get(**username_lookup)
        except UserModel.DoesNotExist:
            pass

        if "@" in login_value:
            users = UserModel._default_manager.filter(email__iexact=login_value).order_by("id")
            if users.count() != 1:
                return None
            return users.first()
        return None
