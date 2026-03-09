from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.core.management import call_command
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import ListView, UpdateView, View
from django_tenants.utils import schema_context

from .forms import AddMemberForm, TenantAuthenticationForm, TenantCreateForm, TenantEditForm
from .models import Client, Domain, TenantMembership


class SuperAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser


class TenantLoginView(LoginView):
    template_name = "auth/login.html"
    authentication_form = TenantAuthenticationForm

    def form_valid(self, form):
        user = form.get_user()
        tenant = getattr(self.request, "tenant", None)
        if tenant and tenant.schema_name == settings.PUBLIC_SCHEMA_NAME and not user.is_superuser:
            has_membership = TenantMembership.objects.filter(
                user=user,
                is_active=True,
                tenant__is_active=True,
            ).exists()
            if not has_membership:
                form.add_error(None, "No tienes clinicas activas asignadas.")
                return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        redirect_to = self.get_redirect_url()
        if redirect_to:
            return redirect_to

        tenant = getattr(self.request, "tenant", None)
        if tenant and tenant.schema_name == settings.PUBLIC_SCHEMA_NAME:
            if self.request.user.is_superuser:
                return reverse("tenants:list")

            memberships = TenantMembership.objects.filter(
                user=self.request.user,
                is_active=True,
                tenant__is_active=True,
            ).select_related("tenant")

            if memberships.count() == 1:
                return reverse("tenants:switch", kwargs={"pk": memberships.first().tenant_id})
            return reverse("dashboard")

        return reverse("dashboard")


class TenantAccessListView(LoginRequiredMixin, ListView):
    model = TenantMembership
    template_name = "tenants/my_tenants.html"
    context_object_name = "memberships"

    def get_queryset(self):
        qs = TenantMembership.objects.select_related("tenant").prefetch_related("tenant__domains").filter(
            is_active=True,
            tenant__is_active=True,
        )
        if self.request.user.is_superuser:
            return qs.order_by("tenant__name")
        return qs.filter(user=self.request.user).order_by("tenant__name")


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
        return render(request, self.template_name, {"form": TenantCreateForm()})

    def post(self, request):
        form = TenantCreateForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        client = None
        try:
            client = Client(
                schema_name=form.cleaned_data["schema_name"],
                name=form.cleaned_data["name"],
                plan=form.cleaned_data["plan"],
                is_active=True,
            )
            client.save()
            Domain.objects.create(
                domain=form.cleaned_data["subdomain"],
                tenant=client,
                is_primary=True,
            )
        except IntegrityError as e:
            if client and getattr(client, "pk", None):
                client.delete(force_drop=True)
            messages.error(request, f"El schema o dominio ya existe: {e}")
            return render(request, self.template_name, {"form": form})
        except Exception as e:
            if client and getattr(client, "pk", None):
                client.delete(force_drop=True)
            messages.error(request, f"Error al crear clinica: {e}")
            return render(request, self.template_name, {"form": form})

        try:
            with schema_context(client.schema_name):
                call_command("seed_data", verbosity=0)
        except Exception as e:
            messages.warning(request, f"Clinica creada pero seed_data fallo: {e}")

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

            TenantMembership.objects.get_or_create(
                tenant=client,
                user=user,
                defaults={"is_admin": True, "is_active": True},
            )

        messages.success(request, f"Clinica '{client.name}' creada correctamente.")
        return redirect("tenants:list")


class TenantEditView(LoginRequiredMixin, SuperAdminRequiredMixin, UpdateView):
    model = Client
    form_class = TenantEditForm
    template_name = "tenants/tenant_edit.html"

    def get_success_url(self):
        messages.success(self.request, f"Clinica '{self.object.name}' actualizada.")
        return self.object.get_absolute_url()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["domains"] = self.object.domains.all()
        return ctx


class TenantDetailView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        tenant = Client.objects.filter(pk=pk).prefetch_related("domains", "memberships__user").first()
        if not tenant:
            messages.error(request, "Clinica no encontrada.")
            return redirect("tenants:list")
        return render(request, "tenants/tenant_detail.html", {"tenant": tenant, "form": AddMemberForm()})

    def post(self, request, pk):
        tenant = Client.objects.filter(pk=pk).prefetch_related("domains", "memberships__user").first()
        if not tenant:
            messages.error(request, "Clinica no encontrada.")
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
                messages.info(request, f"'{user.username}' ya es miembro de esta clinica.")
            return redirect("tenants:detail", pk=tenant.pk)

        return render(request, "tenants/tenant_detail.html", {"tenant": tenant, "form": form})


class TenantToggleActiveView(LoginRequiredMixin, SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        tenant = Client.objects.filter(pk=pk).first()
        if not tenant:
            messages.error(request, "Clinica no encontrada.")
            return redirect("tenants:list")
        tenant.is_active = not tenant.is_active
        tenant.save(update_fields=["is_active"])
        estado = "activada" if tenant.is_active else "desactivada"
        messages.success(request, f"Clinica '{tenant.name}' {estado}.")
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
        messages.success(request, f"Usuario '{username}' removido de la clinica.")
        return redirect("tenants:detail", pk=tenant_pk)


class TenantSwitchView(LoginRequiredMixin, View):
    def get(self, request, pk):
        tenant = Client.objects.filter(pk=pk, is_active=True).prefetch_related("domains").first()
        if not tenant:
            messages.error(request, "Clinica no encontrada.")
            return redirect("dashboard")

        if not request.user.is_superuser:
            has_membership = TenantMembership.objects.filter(
                tenant=tenant,
                user=request.user,
                is_active=True,
            ).exists()
            if not has_membership:
                messages.error(request, "No tienes acceso a esta clinica.")
                return redirect("dashboard")

        domain = tenant.domains.filter(is_primary=True).first() or tenant.domains.first()
        if not domain:
            messages.error(request, "La clinica no tiene dominio configurado.")
            return redirect("dashboard")

        host = request.get_host()
        port = ""
        if ":" in host:
            port = ":" + host.split(":")[-1]
        return redirect(f"{request.scheme}://{domain.domain}{port}/")
