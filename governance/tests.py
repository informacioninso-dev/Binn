from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from tenants.models import Client

from .forms import GroupTenantAccessAssignForm
from .models import CorporateGroup, GroupMembership, GroupTenantAccess, GroupTenantLink
from .services import (
    _compute_usage_health,
    can_allocate_group_seat,
    can_allocate_manager_assignment,
    get_or_create_billing_account,
    resolve_group_tenant_detail_access,
)


class GroupMembershipPolicyTests(SimpleTestCase):
    def test_group_membership_role_helpers_match_governance_intent(self):
        group = CorporateGroup(status=CorporateGroup.STATUS_ACTIVE)

        owner = GroupMembership(group=group, role=GroupMembership.ROLE_OWNER, is_active=True)
        viewer = GroupMembership(group=group, role=GroupMembership.ROLE_VIEWER, is_active=True)
        executive = GroupMembership(group=group, role=GroupMembership.ROLE_EXECUTIVE, is_active=True)

        self.assertTrue(owner.can_manage_group())
        self.assertTrue(owner.can_manage_billing())
        self.assertTrue(executive.can_request_operational_access())
        self.assertFalse(viewer.can_manage_group())
        self.assertFalse(viewer.can_request_operational_access())


class GroupTenantDetailAccessTests(SimpleTestCase):
    def _user(self):
        return SimpleNamespace(is_authenticated=True, is_superuser=False)

    def _link(self, *, group):
        tenant = SimpleNamespace(
            name="Acme",
            tenant_config=SimpleNamespace(role_policies={"viewer": ["dashboard.view"], "operator": ["*"]}),
        )
        return SimpleNamespace(group=group, tenant=tenant, effective_mode=CorporateGroup.MODE_FULL)

    def test_group_admin_can_open_full_detail_without_extra_assignment(self):
        group = CorporateGroup(
            status=CorporateGroup.STATUS_ACTIVE,
            operating_model=CorporateGroup.OPERATING_MODEL_ISLANDS,
            consolidation_mode=CorporateGroup.MODE_FULL,
        )
        membership = GroupMembership(group=group, role=GroupMembership.ROLE_ADMIN, is_active=True)

        decision = resolve_group_tenant_detail_access(
            group=group,
            link=self._link(group=group),
            user=self._user(),
            membership=membership,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "group_admin")

    def test_group_user_without_assignment_cannot_open_tenant(self):
        group = CorporateGroup(
            status=CorporateGroup.STATUS_ACTIVE,
            operating_model=CorporateGroup.OPERATING_MODEL_FAMILY,
            consolidation_mode=CorporateGroup.MODE_FULL,
        )
        membership = GroupMembership(group=group, role=GroupMembership.ROLE_EXECUTIVE, is_active=True)
        original_get_access = resolve_group_tenant_detail_access.__globals__["get_group_tenant_access"]
        resolve_group_tenant_detail_access.__globals__["get_group_tenant_access"] = lambda **_: None
        try:
            decision = resolve_group_tenant_detail_access(
                group=group,
                link=self._link(group=group),
                user=self._user(),
                membership=membership,
            )
        finally:
            resolve_group_tenant_detail_access.__globals__["get_group_tenant_access"] = original_get_access

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "missing_group_tenant_access")

    def test_group_user_with_assignment_uses_tenant_role_permissions(self):
        group = CorporateGroup(
            status=CorporateGroup.STATUS_ACTIVE,
            operating_model=CorporateGroup.OPERATING_MODEL_FAMILY,
            consolidation_mode=CorporateGroup.MODE_FULL,
        )
        membership = GroupMembership(group=group, role=GroupMembership.ROLE_VIEWER, is_active=True)
        tenant = SimpleNamespace(
            name="Acme",
            tenant_config=SimpleNamespace(role_policies={"viewer": ["dashboard.view"], "operator": ["*"]}),
        )
        access = SimpleNamespace(role=GroupTenantAccess.ROLE_VIEWER, is_active=True)
        link = SimpleNamespace(group=group, tenant=tenant, effective_mode=CorporateGroup.MODE_FULL)

        original_get_access = resolve_group_tenant_detail_access.__globals__["get_group_tenant_access"]
        resolve_group_tenant_detail_access.__globals__["get_group_tenant_access"] = lambda **_: access
        try:
            access_decision = resolve_group_tenant_detail_access(
                group=group,
                link=link,
                user=self._user(),
                membership=membership,
                permission_code="dashboard.view",
            )
            deny_decision = resolve_group_tenant_detail_access(
                group=group,
                link=link,
                user=self._user(),
                membership=membership,
                permission_code="deals.edit",
            )
        finally:
            resolve_group_tenant_detail_access.__globals__["get_group_tenant_access"] = original_get_access

        self.assertTrue(access_decision.allowed)
        self.assertEqual(access_decision.reason, "group_tenant_access")
        self.assertFalse(deny_decision.allowed)
        self.assertEqual(deny_decision.reason, "tenant_role_denied")

    def test_group_detail_denies_when_effective_mode_is_blocked(self):
        group = CorporateGroup(
            status=CorporateGroup.STATUS_ACTIVE,
            operating_model=CorporateGroup.OPERATING_MODEL_FAMILY,
            consolidation_mode=CorporateGroup.MODE_FULL,
        )
        membership = GroupMembership(group=group, role=GroupMembership.ROLE_ADMIN, is_active=True)
        blocked_link = SimpleNamespace(group=group, tenant=SimpleNamespace(name="Acme"), effective_mode=CorporateGroup.MODE_BLOCKED)

        decision = resolve_group_tenant_detail_access(
            group=group,
            link=blocked_link,
            user=self._user(),
            membership=membership,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "effective_mode_blocked")

    def test_group_detail_denies_when_effective_mode_is_aggregate_only(self):
        group = CorporateGroup(
            status=CorporateGroup.STATUS_ACTIVE,
            operating_model=CorporateGroup.OPERATING_MODEL_FAMILY,
            consolidation_mode=CorporateGroup.MODE_FULL,
        )
        membership = GroupMembership(group=group, role=GroupMembership.ROLE_ADMIN, is_active=True)
        aggregate_link = SimpleNamespace(
            group=group,
            tenant=SimpleNamespace(name="Acme"),
            effective_mode=CorporateGroup.MODE_AGGREGATE_ONLY,
        )

        decision = resolve_group_tenant_detail_access(
            group=group,
            link=aggregate_link,
            user=self._user(),
            membership=membership,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "effective_mode_aggregate_only")


class GovernanceUsageHealthTests(SimpleTestCase):
    def test_compute_usage_health_marks_over_limit(self):
        health = _compute_usage_health(12, 10)

        self.assertTrue(health["is_over"])
        self.assertEqual(health["remaining"], 0)

    def test_compute_usage_health_tracks_remaining_capacity(self):
        health = _compute_usage_health(6, 10)

        self.assertFalse(health["is_over"])
        self.assertEqual(health["remaining"], 4)


class GovernanceCapacityTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.owner = self.user_model.objects.create_user(username="owner", password="x")
        self.member = self.user_model.objects.create_user(username="member", password="x")
        self.group = CorporateGroup.objects.create(
            name="Holding Uno",
            slug="holding-uno",
            status=CorporateGroup.STATUS_ACTIVE,
            operating_model=CorporateGroup.OPERATING_MODEL_FAMILY,
            consolidation_mode=CorporateGroup.MODE_FULL,
            owner=self.owner,
        )
        billing = get_or_create_billing_account(group=self.group)
        billing.seat_limit = 1
        billing.manager_limit = 1
        billing.enforce_limits = True
        billing.save(update_fields=["seat_limit", "manager_limit", "enforce_limits", "updated_at"])

    def _tenant(self, schema_name: str, name: str):
        tenant = Client(name=name, schema_name=schema_name, plan=Client.PLAN_SHARED, is_active=True)
        tenant.auto_create_schema = False
        tenant.save()
        return tenant

    def test_group_seat_limit_blocks_new_active_member(self):
        GroupMembership.objects.create(group=self.group, user=self.owner, role=GroupMembership.ROLE_OWNER, is_active=True)

        self.assertFalse(can_allocate_group_seat(group=self.group))

    def test_group_seat_limit_allows_existing_active_member_update(self):
        membership = GroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=GroupMembership.ROLE_OWNER,
            is_active=True,
        )

        self.assertTrue(can_allocate_group_seat(group=self.group, current_membership=membership))

    def test_manager_limit_blocks_new_manager_assignment(self):
        tenant = self._tenant("tenantmgr", "Tenant Mgr")
        GroupTenantAccess.objects.create(
            group=self.group,
            tenant=tenant,
            user=self.owner,
            role=GroupTenantAccess.ROLE_MANAGER,
            is_active=True,
        )

        self.assertFalse(
            can_allocate_manager_assignment(
                group=self.group,
                target_role=GroupTenantAccess.ROLE_MANAGER,
            )
        )

    def test_manager_limit_allows_existing_manager_update(self):
        tenant = self._tenant("tenantmgr2", "Tenant Mgr 2")
        access = GroupTenantAccess.objects.create(
            group=self.group,
            tenant=tenant,
            user=self.owner,
            role=GroupTenantAccess.ROLE_MANAGER,
            is_active=True,
        )

        self.assertTrue(
            can_allocate_manager_assignment(
                group=self.group,
                current_access=access,
                target_role=GroupTenantAccess.ROLE_MANAGER,
            )
        )


class GroupTenantLinkModeTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.owner = self.user_model.objects.create_user(username="holdingowner", password="x")
        self.group = CorporateGroup.objects.create(
            name="Holding Dos",
            slug="holding-dos",
            status=CorporateGroup.STATUS_ACTIVE,
            operating_model=CorporateGroup.OPERATING_MODEL_FAMILY,
            consolidation_mode=CorporateGroup.MODE_FULL,
            owner=self.owner,
        )

    def _tenant(self, schema_name: str, name: str, *, allow_consolidation: bool = True):
        tenant = Client(
            name=name,
            schema_name=schema_name,
            plan=Client.PLAN_SHARED,
            is_active=True,
            allow_consolidation=allow_consolidation,
        )
        tenant.auto_create_schema = False
        tenant.save()
        return tenant

    def test_effective_mode_respects_tenant_veto(self):
        tenant = self._tenant("tenantveto", "Tenant Veto", allow_consolidation=False)
        link = GroupTenantLink.objects.create(
            group=self.group,
            tenant=tenant,
            consolidation_mode=CorporateGroup.MODE_FULL,
            is_active=True,
        )

        self.assertEqual(link.effective_mode, CorporateGroup.MODE_BLOCKED)

    def test_effective_mode_uses_most_restrictive_layer(self):
        tenant = self._tenant("tenantagg", "Tenant Aggregate")
        self.group.consolidation_mode = CorporateGroup.MODE_AGGREGATE_ONLY
        self.group.save(update_fields=["consolidation_mode", "updated_at"])
        link = GroupTenantLink.objects.create(
            group=self.group,
            tenant=tenant,
            consolidation_mode=CorporateGroup.MODE_FULL,
            is_active=True,
        )

        self.assertEqual(link.effective_mode, CorporateGroup.MODE_AGGREGATE_ONLY)


class GroupTenantAccessAssignFormTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.group_owner = self.user_model.objects.create_user(username="groupowner", password="x")
        self.holding_user = self.user_model.objects.create_user(username="holdinguser", password="x")
        self.outsider = self.user_model.objects.create_user(username="outsider", password="x")
        self.group = CorporateGroup.objects.create(
            name="Holding Tres",
            slug="holding-tres",
            status=CorporateGroup.STATUS_ACTIVE,
            operating_model=CorporateGroup.OPERATING_MODEL_FAMILY,
            consolidation_mode=CorporateGroup.MODE_FULL,
            owner=self.group_owner,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.holding_user,
            role=GroupMembership.ROLE_ANALYST,
            is_active=True,
        )
        self.tenant = Client(name="Tenant Form", schema_name="tenantform", plan=Client.PLAN_SHARED, is_active=True)
        self.tenant.auto_create_schema = False
        self.tenant.save()
        GroupTenantLink.objects.create(
            group=self.group,
            tenant=self.tenant,
            consolidation_mode=CorporateGroup.MODE_FULL,
            is_active=True,
        )

    def test_form_accepts_active_group_member_and_linked_tenant(self):
        form = GroupTenantAccessAssignForm(
            data={"username": "holdinguser", "tenant": str(self.tenant.pk), "role": GroupTenantAccess.ROLE_VIEWER, "is_active": "on"},
            group=self.group,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.user, self.holding_user)
        self.assertEqual(form.link.tenant_id, self.tenant.pk)

    def test_form_rejects_user_without_active_group_membership(self):
        form = GroupTenantAccessAssignForm(
            data={"username": "outsider", "tenant": str(self.tenant.pk), "role": GroupTenantAccess.ROLE_VIEWER, "is_active": "on"},
            group=self.group,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)
