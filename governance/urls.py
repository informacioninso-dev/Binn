from django.urls import path

from .views import (
    CorporateGroupBillingUpdateView,
    CorporateGroupCreateView,
    CorporateGroupDetailView,
    CorporateGroupEditView,
    CorporateGroupListView,
    CorporateGroupMembershipUpsertView,
    CorporateGroupSwitchView,
    CorporateGroupTenantAccessUpsertView,
    CorporateGroupTenantLinkUpsertView,
    GroupTenantAccessDeleteView,
    GroupTenantAccessToggleView,
    OperationalAccessGrantDecisionView,
    OperationalAccessRequestCreateView,
)


app_name = "governance"

urlpatterns = [
    path("groups/", CorporateGroupListView.as_view(), name="group_list"),
    path("groups/new/", CorporateGroupCreateView.as_view(), name="group_create"),
    path("groups/<int:pk>/", CorporateGroupDetailView.as_view(), name="group_detail"),
    path("groups/<int:pk>/edit/", CorporateGroupEditView.as_view(), name="group_edit"),
    path("groups/<int:pk>/switch/", CorporateGroupSwitchView.as_view(), name="group_switch"),
    path("groups/<int:pk>/billing/", CorporateGroupBillingUpdateView.as_view(), name="group_billing"),
    path("groups/<int:pk>/members/upsert/", CorporateGroupMembershipUpsertView.as_view(), name="group_membership_upsert"),
    path("groups/<int:pk>/tenants/upsert/", CorporateGroupTenantLinkUpsertView.as_view(), name="group_tenant_link_upsert"),
    path("groups/<int:pk>/tenant-access/upsert/", CorporateGroupTenantAccessUpsertView.as_view(), name="group_tenant_access_upsert"),
    path("tenant-access/<int:access_pk>/toggle/", GroupTenantAccessToggleView.as_view(), name="group_tenant_access_toggle"),
    path("tenant-access/<int:access_pk>/delete/", GroupTenantAccessDeleteView.as_view(), name="group_tenant_access_delete"),
    path("groups/<int:pk>/access/request/", OperationalAccessRequestCreateView.as_view(), name="operational_access_request"),
    path("grants/<int:grant_pk>/decide/", OperationalAccessGrantDecisionView.as_view(), name="operational_access_decide"),
]
