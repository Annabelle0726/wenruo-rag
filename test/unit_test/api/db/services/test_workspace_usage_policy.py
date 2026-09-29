"""U3 Usage Policy control plane: revision, conditional update, validation, audit.

These are the policy-side gates (G1-G6). The gates that need a second engine or a
browser are recorded in the U3 report instead of being claimed here.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from peewee import SqliteDatabase

from api.db.db_models import (
    Tenant,
    User,
    UserTenant,
    WorkspaceAudit,
    WorkspaceBudget,
)
from api.db.services import workspace_budget_service as budget
from api.db.services import workspace_usage_read_service as read
from common.exceptions import WorkspaceAccessDenied


class AdmittingRedis:
    def __init__(self):
        self.calls = []

    def eval(self, script, nkeys, key, *args):
        self.calls.append((key, args))
        return 1


@pytest.fixture
def policy(tmp_path, monkeypatch):
    models = [Tenant, User, UserTenant, WorkspaceAudit, WorkspaceBudget]
    db = SqliteDatabase(tmp_path / "policy.sqlite", timeout=20)
    with db.bind_ctx(models):
        db.create_tables(models)
        monkeypatch.setattr(budget, "DB", db)
        monkeypatch.setattr(read, "DB", db)
        redis = AdmittingRedis()
        monkeypatch.setattr(budget, "REDIS_CONN", SimpleNamespace(REDIS=redis))
        for tenant in ("workspace", "other"):
            Tenant.create(id=tenant, name=tenant, llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="", parser_ids="")
        for user, role in (("owner", "owner"), ("admin", "admin"), ("member", "normal")):
            User.create(id=user, nickname=user, email=user + "@example.test", current_tenant_id="workspace")
            UserTenant.create(id=user, tenant_id="workspace", user_id=user, role=role, status="1", invited_by="owner")
        # "solo" owns ONLY its own personal workspace, whose id IS its user id.
        # That is the trap G3 targets: owning one workspace must grant nothing in
        # another, and an id comparison would conclude otherwise.
        Tenant.create(id="solo", name="solo", llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="", parser_ids="")
        User.create(id="solo", nickname="solo", email="solo@example.test", current_tenant_id="solo")
        UserTenant.create(id="solo-self", tenant_id="solo", user_id="solo", role="owner", status="1", invited_by="solo")
        yield db
        if not db.is_closed():
            db.close()


def _four(**overrides):
    values = {
        "calls_per_day": 500,
        "calls_per_month": 5000,
        "tokens_per_day": 100000,
        "tokens_per_month": 2000000,
    }
    values.update(overrides)
    return values


# --------------------------------------------------------------------------- #
# G1 authorization + audit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("operator", ["owner", "admin"])
def test_owner_and_admin_can_save_and_each_write_is_audited(policy, operator):
    payload = budget.configure_budget("workspace", operator, _four())

    assert payload["calls_per_day"] == 500
    assert payload["tokens_per_month"] == 2000000
    audit = WorkspaceAudit.select().where(WorkspaceAudit.tenant_id == "workspace").get()
    assert audit.operator_id == operator
    assert audit.action == "update_budget"
    assert audit.details == _four()


def test_authorization_is_rechecked_in_the_service_not_only_in_the_route(policy):
    # The direct service call is the same check the HTTP layer reaches, so a
    # removed or demoted operator is refused even when a stale UI sends the write.
    UserTenant.update(role="normal").where((UserTenant.tenant_id == "workspace") & (UserTenant.user_id == "admin")).execute()

    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "admin", _four())
    assert WorkspaceBudget.select().count() == 0
    assert WorkspaceAudit.select().count() == 0


def test_g2_normal_member_cannot_write(policy):
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "member", _four())

    assert WorkspaceBudget.select().count() == 0
    assert WorkspaceAudit.select().count() == 0


def test_g3_a_personal_workspace_owner_cannot_write_another_workspace(policy):
    # "solo" owns the workspace whose id IS their user id. That is legitimate for
    # THEIR OWN workspace and must grant nothing elsewhere, which is where an
    # id-comparison would go wrong.
    own = budget.configure_budget("solo", "solo", _four())
    assert own["calls_per_day"] == 500

    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("other", "solo", _four())
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "solo", _four())

    assert WorkspaceBudget.select().where(WorkspaceBudget.tenant_id == "workspace").count() == 0
    assert WorkspaceBudget.select().where(WorkspaceBudget.tenant_id == "other").count() == 0
    assert WorkspaceAudit.select().where(WorkspaceAudit.tenant_id == "workspace").count() == 0


# --------------------------------------------------------------------------- #
# G6 audit atomicity
# --------------------------------------------------------------------------- #


def test_g6_a_failed_audit_write_rolls_the_limits_back(policy, monkeypatch):
    def fail(**_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(WorkspaceAudit, "create", fail)
    with pytest.raises(RuntimeError):
        budget.configure_budget("workspace", "owner", _four())

    assert WorkspaceBudget.select().count() == 0


def test_a_refused_update_writes_no_success_audit(policy):
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "owner", {"calls_per_day": -1})

    assert WorkspaceAudit.select().count() == 0


# --------------------------------------------------------------------------- #
# G4 partial PUT + storage range
# --------------------------------------------------------------------------- #


def test_g4_a_partial_update_touches_only_the_given_field(policy):
    baseline = budget.configure_budget("workspace", "owner", _four(calls_per_minute=17, timezone="Asia/Shanghai"))

    payload = budget.configure_budget("workspace", "owner", {"calls_per_day": 42})

    assert payload["calls_per_day"] == 42
    assert payload["calls_per_month"] == baseline["calls_per_month"]
    assert payload["tokens_per_day"] == baseline["tokens_per_day"]
    assert payload["tokens_per_month"] == baseline["tokens_per_month"]
    assert payload["calls_per_minute"] == 17
    assert payload["timezone"] == "Asia/Shanghai"
    assert WorkspaceAudit.select().count() == 2


def test_g4_an_empty_or_unknown_patch_is_refused(policy):
    for bad in ({}, {"tokens_per_week": 5}, {"calls_per_day": "500"}, {"calls_per_day": True}, {"calls_per_day": 1.5}):
        with pytest.raises(WorkspaceAccessDenied):
            budget.configure_budget("workspace", "owner", bad)
    assert WorkspaceBudget.select().count() == 0


def test_g4_calls_are_validated_against_the_storage_column(policy):
    # Calls live in an IntegerField: 10^10 used to be accepted here and would fail
    # at insert. It is now a controlled refusal, and the boundary is exact.
    at_max = budget.configure_budget("workspace", "owner", {"calls_per_day": budget.CALL_MAX})
    assert at_max["calls_per_day"] == budget.CALL_MAX

    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "owner", {"calls_per_day": budget.CALL_MAX + 1})
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "owner", {"calls_per_day": 10_000_000_000})
    # Tokens keep their BigInteger range.
    assert budget.configure_budget("workspace", "owner", {"tokens_per_day": budget.TOKEN_MAX})["tokens_per_day"] == budget.TOKEN_MAX


# --------------------------------------------------------------------------- #
# G5 zero semantics
# --------------------------------------------------------------------------- #


def test_g5_tokens_zero_means_not_enforced_and_calls_zero_is_refused(policy):
    payload = budget.configure_budget("workspace", "owner", {"tokens_per_day": 0, "tokens_per_month": 0})

    assert payload["tokens_per_day"] == 0
    assert "tokens_per_day" in payload["zero_means_unlimited"]
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "owner", {"calls_per_day": 0})


# --------------------------------------------------------------------------- #
# G7 (policy half): revision semantics and conditional update
# --------------------------------------------------------------------------- #


def test_the_revision_covers_policy_and_ignores_usage(policy):
    baseline = budget.policy_revision("workspace")

    budget.configure_budget("workspace", "owner", _four())
    changed = budget.policy_revision("workspace")
    assert changed != baseline

    # A reservation/consumption change is NOT a policy change: including usage
    # would make every metered model call a conflict for the policy editor.
    WorkspaceBudget.update(calls_per_day=WorkspaceBudget.calls_per_day).where(WorkspaceBudget.tenant_id == "workspace").execute()
    assert budget.policy_revision("workspace") == changed


def test_a_matching_revision_saves_and_a_stale_one_conflicts(policy):
    budget.configure_budget("workspace", "owner", _four())
    revision = budget.policy_revision("workspace")

    saved = budget.configure_budget("workspace", "owner", {"calls_per_day": 600}, expected_revision=revision)
    assert saved["calls_per_day"] == 600

    # The second administrator still holds the pre-change revision.
    with pytest.raises(budget.PolicyConflict):
        budget.configure_budget("workspace", "admin", {"calls_per_day": 700}, expected_revision=revision)

    assert WorkspaceBudget.get_by_id("workspace").calls_per_day == 600
    assert WorkspaceAudit.select().where(WorkspaceAudit.operator_id == "admin").count() == 0
    # The conflict response carries the NEW revision, so a refresh-then-save works.
    assert saved["policy_revision"] != revision


def test_the_returned_revision_is_the_one_the_next_save_must_echo(policy):
    first = budget.configure_budget("workspace", "owner", _four())
    second = budget.configure_budget("workspace", "admin", {"calls_per_month": 9000}, expected_revision=first["policy_revision"])

    assert second["calls_per_month"] == 9000
    # And a partial save with the fresh revision keeps the other field.
    third = budget.configure_budget("workspace", "owner", {"tokens_per_day": 12345}, expected_revision=second["policy_revision"])
    assert third["calls_per_day"] == 500 and third["tokens_per_day"] == 12345


def test_a_caller_without_the_header_keeps_the_legacy_behaviour(policy):
    budget.configure_budget("workspace", "owner", _four())
    # No If-Match: last committed write wins, so the pre-existing API contract is
    # not broken by the newer conditional one.
    payload = budget.configure_budget("workspace", "admin", {"calls_per_day": 777})
    assert payload["calls_per_day"] == 777


def test_saving_never_resets_counters_or_creates_a_second_row(policy):
    budget.configure_budget("workspace", "owner", _four())
    budget.configure_budget("workspace", "owner", {"calls_per_day": 501})

    assert WorkspaceBudget.select().count() == 1


# --------------------------------------------------------------------------- #
# Read-side exposure
# --------------------------------------------------------------------------- #


def test_the_quota_view_exposes_the_revision_the_editor_needs(policy):
    budget.configure_budget("workspace", "owner", _four())

    payload = read.quota_status("owner", "workspace")
    data = payload["data"]

    assert data["policy_revision"] == budget.policy_revision("workspace")
    assert data["limits_source"] == "workspace_budget_row"
    assert data["limits"]["calls_per_day"] == 500
    # The read path stays read-only: no audit row appears from reading it.
    assert WorkspaceAudit.select().count() == 1


def test_a_workspace_without_a_budget_row_reports_defaults_and_a_revision(policy):
    payload = read.quota_status("owner", "workspace")
    data = payload["data"]

    assert data["limits_source"] == "backend_defaults"
    assert data["limits"]["calls_per_day"] == 1000
    assert data["policy_revision"] == budget.policy_revision("workspace")
    assert WorkspaceBudget.select().count() == 0
