# partners/views.py
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView

from .models import Partner
from .forms import PartnerForm


class PartnerListView(LoginRequiredMixin, ListView):
    model = Partner
    template_name = "partners/partner_list.html"
    context_object_name = "partners"
    paginate_by = 20

    def get_queryset(self):
        qs = Partner.objects.all().order_by("trade_name", "legal_name")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                Q(trade_name__icontains=q)
                | Q(legal_name__icontains=q)
                | Q(code__icontains=q)
                | Q(identification__icontains=q)
            )
        # Más adelante si quieres, puedes filtrar solo activos:
        # qs = qs.filter(is_active=True)
        return qs


class PartnerCreateView(LoginRequiredMixin, CreateView):
    model = Partner
    form_class = PartnerForm
    template_name = "partners/partner_form.html"
    success_url = reverse_lazy("partners:index")

    def form_valid(self, form):
        messages.success(self.request, "Socio creado correctamente.")
        return super().form_valid(form)


class PartnerUpdateView(LoginRequiredMixin, UpdateView):
    model = Partner
    form_class = PartnerForm
    template_name = "partners/partner_form.html"
    success_url = reverse_lazy("partners:index")

    def form_valid(self, form):
        messages.success(self.request, "Socio actualizado correctamente.")
        return super().form_valid(form)
