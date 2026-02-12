from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.generic import ListView, UpdateView, View
from django_tenants.utils import schema_context

from .forms import AddMemberForm, TenantCreateForm, TenantEditForm
from .models import Client, Domain, TenantMembership


class SuperAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser


class TenantListView(LoginRequiredMixin, SuperAdminRequiredMixin, ListView):
    model = Client
    template_name = "tenants/tenant_list.html"
    context_object_name = "tenants"
    paginate_by = 50

    def get_queryset(self):
        return Client.objects.prefetch_related("domains", "memberships").order_by("name")


class TenantCreateView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    template_name = "tenants/tenant_form.html"

    def get(self, request):
        form = TenantCreateForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = TenantCreateForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        schema_name = form.cleaned_data["schema_name"]
        name = form.cleaned_data["name"]
        plan = form.cleaned_data["plan"]
        domain = form.cleaned_data["subdomain"]

        try:
            with transaction.atomic():
                client = Client(
                    schema_name=schema_name,
                    name=name,
                    plan=plan,
                    is_active=True,
                )
                client.save()
                Domain.objects.create(domain=domain, tenant=client, is_primary=True)
        except IntegrityError as e:
            messages.error(request, f"El schema o dominio ya existe: {str(e)}")
            return render(request, self.template_name, {"form": form})
        except Exception as e:
            messages.error(request, f"Error al crear tenant: {str(e)}")
            return render(request, self.template_name, {"form": form})

        # Migrar schema y cargar seed base
        try:
            call_command("migrate_schemas", schema_name=client.schema_name, interactive=False, verbosity=0)
        except Exception as e:
            messages.error(request, f"Error al migrar schema: {str(e)}")
            # Eliminar el tenant creado si las migraciones fallan
            client.delete()
            return render(request, self.template_name, {"form": form})

        try:
            with schema_context(client.schema_name):
                call_command("seed_data", verbosity=0)
        except Exception as e:
            messages.warning(request, f"Tenant creado pero seed_data falló: {str(e)}")
            try:
                from core.models import CompanyConfig
                config = CompanyConfig.get()
                if config:
                    config.legal_name = client.name
                    if not config.trade_name:
                        config.trade_name = client.name
                    config.save(update_fields=["legal_name", "trade_name"])
            except Exception:
                pass

        # Crear o asociar usuario admin al tenant
        username = (form.cleaned_data.get("admin_username") or "").strip()
        email = (form.cleaned_data.get("admin_email") or "").strip()
        password = (form.cleaned_data.get("admin_password") or "").strip()

        if username:
            User = get_user_model()
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": email, "is_staff": True},
            )
            if created or password:
                if email and not user.email:
                    user.email = email
                user.is_staff = True
                user.set_password(password)
                user.save()

            admin_group, _ = Group.objects.get_or_create(name="admin")
            user.groups.add(admin_group)

            TenantMembership.objects.get_or_create(
                tenant=client,
                user=user,
                defaults={"is_admin": True, "is_active": True},
            )

        messages.success(request, f"Empresa '{client.name}' creada correctamente.")
        return redirect("tenants:list")


class TenantEditView(LoginRequiredMixin, SuperAdminRequiredMixin, UpdateView):
    model = Client
    form_class = TenantEditForm
    template_name = "tenants/tenant_edit.html"

    def get_success_url(self):
        messages.success(self.request, f"Empresa '{self.object.name}' actualizada.")
        return self.object.get_absolute_url()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["domains"] = self.object.domains.all()
        return ctx


class TenantDetailView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        tenant = Client.objects.filter(pk=pk).prefetch_related("domains", "memberships__user").first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")
        form = AddMemberForm()
        return render(request, "tenants/tenant_detail.html", {"tenant": tenant, "form": form})

    def post(self, request, pk):
        tenant = Client.objects.filter(pk=pk).prefetch_related("domains", "memberships__user").first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")

        form = AddMemberForm(request.POST)
        if form.is_valid():
            User = get_user_model()
            try:
                user = User.objects.get(username=form.cleaned_data["username"])
            except User.DoesNotExist:
                messages.error(request, "Usuario no encontrado.")
                return render(request, "tenants/tenant_detail.html", {"tenant": tenant, "form": form})

            _, created = TenantMembership.objects.get_or_create(
                tenant=tenant,
                user=user,
                defaults={"is_admin": form.cleaned_data["is_admin"], "is_active": True},
            )
            if created:
                messages.success(request, f"Usuario '{user.username}' agregado.")
            else:
                messages.info(request, f"'{user.username}' ya es miembro de esta empresa.")
            return redirect("tenants:detail", pk=tenant.pk)

        return render(request, "tenants/tenant_detail.html", {"tenant": tenant, "form": form})


class TenantToggleActiveView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")
        tenant.is_active = not tenant.is_active
        tenant.save(update_fields=["is_active"])
        estado = "activada" if tenant.is_active else "desactivada"
        messages.success(request, f"Empresa '{tenant.name}' {estado}.")
        return redirect("tenants:detail", pk=tenant.pk)


class MembershipToggleView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        membership = TenantMembership.objects.select_related("tenant", "user").filter(pk=pk).first()
        if not membership:
            messages.error(request, "Membresia no encontrada.")
            return redirect("tenants:list")
        membership.is_active = not membership.is_active
        membership.save(update_fields=["is_active"])
        estado = "activado" if membership.is_active else "desactivado"
        messages.success(request, f"Usuario '{membership.user.username}' {estado}.")
        return redirect("tenants:detail", pk=membership.tenant.pk)


class MembershipDeleteView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        membership = TenantMembership.objects.select_related("tenant", "user").filter(pk=pk).first()
        if not membership:
            messages.error(request, "Membresia no encontrada.")
            return redirect("tenants:list")
        tenant_pk = membership.tenant.pk
        username = membership.user.username
        membership.delete()
        messages.success(request, f"Usuario '{username}' removido de la empresa.")
        return redirect("tenants:detail", pk=tenant_pk)


class TenantSwitchView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        tenant = Client.objects.filter(pk=pk).prefetch_related("domains").first()
        if not tenant:
            messages.error(request, "Empresa no encontrada.")
            return redirect("tenants:list")

        domain = tenant.domains.filter(is_primary=True).first() or tenant.domains.first()
        if not domain:
            messages.error(request, "La empresa no tiene dominio configurado.")
            return redirect("tenants:list")

        host = request.get_host()  # ej: localhost:8000
        port = ""
        if ":" in host:
            port = ":" + host.split(":")[-1]
        target = f"{request.scheme}://{domain.domain}{port}/"
        return redirect(target)
