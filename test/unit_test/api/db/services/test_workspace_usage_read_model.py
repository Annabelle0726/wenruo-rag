"""The U1 usage read model: scope isolation, frozen accounting, cost honesty.

The fixture deliberately uses a workspace id that equals NO user id, and a user
who belongs to two workspaces, because the live deployment's only metered
`(tenant_id, user_id)` pair happens to have `tenant_id == user_id`. A read model
that confused the two domains would look correct on that data and is exactly
what these tests have to rule out.
"""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
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
    WorkspaceUsage,
    WorkspaceUsageLedger,
)
from api.db.services import workspace_budget_service as enforcement
from api.db.services import workspace_usage_read_service as read
from common.exceptions import WorkspaceAccessDenied

WORKSPACE = "ws-alpha"
OTHER_WORKSPACE = "ws-beta"
OWNER = "owner-user"
ADMIN = "admin-user"
MEMBER_A = "member-a"
MEMBER_B = "member-b"
OUTSIDER = "outsider-user"

DAY = "2026-03-10"
DAY2 = "2026-03-11"
MONTH = "2026-03"
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)

# --------------------------------------------------------------------------- #
# fixture: 2 workspaces, 5 members (one of them in BOTH workspaces)
# --------------------------------------------------------------------------- #


def _ledger(tenant_id, user_id, status, *, day=DAY, tokens=0, reserved_tokens=0, cost_micros=0, reserved_cost_micros=0, model_name="chat-x", call_kind="chat"):
    WorkspaceUsageLedger.create(
        id=uuid4().hex,
        tenant_id=tenant_id,
        user_id=user_id,
        call_kind=call_kind,
        model_name=model_name,
        period_day=day,
        period_month=MONTH,
        timezone="UTC",
        reserved_tokens=reserved_tokens,
        reserved_cost_micros=reserved_cost_micros,
        prompt_tokens=tokens,
        completion_tokens=0,
        tokens=tokens,
        cost_micros=cost_micros,
        status=status,
        settled_at=None,
    )


def _counter(user_id, period, calls, tokens, tenant_id=WORKSPACE):
    WorkspaceUsage.create(
        id=uuid4().hex,
        tenant_id=tenant_id,
        user_id=user_id,
        period=period,
        calls=calls,
        prompt_tokens=tokens,
        completion_tokens=0,
        tokens=tokens,
        cost_micros=0,
    )


@pytest.fixture
def usage(tmp_path, monkeypatch):
    models = [Tenant, User, UserTenant, WorkspaceAudit, WorkspaceBudget, WorkspaceUsage, WorkspaceUsageLedger]
    db = SqliteDatabase(tmp_path / "usage_read.sqlite", timeout=20)
    with db.bind_ctx(models):
        db.create_tables(models)
        # The read model resolves `DB` at call time from its own module, so the
        # fixture binds it exactly like the enforcement tests bind theirs.
        monkeypatch.setattr(read, "DB", db)

        for tenant in (WORKSPACE, OTHER_WORKSPACE):
            Tenant.create(id=tenant, name=tenant, llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="", parser_ids="")
        for user_id in (OWNER, ADMIN, MEMBER_A, MEMBER_B, OUTSIDER):
            User.create(id=user_id, nickname=user_id.upper(), email=user_id + "@example.test", current_tenant_id=WORKSPACE)
        for user_id, tenant_id, role in (
            (OWNER, WORKSPACE, "owner"),
            (ADMIN, WORKSPACE, "admin"),
            (MEMBER_A, WORKSPACE, "normal"),
            (MEMBER_B, WORKSPACE, "normal"),
            (OUTSIDER, OTHER_WORKSPACE, "owner"),
            (MEMBER_A, OTHER_WORKSPACE, "normal"),
        ):
            UserTenant.create(id=f"{user_id}:{tenant_id}"[:32], user_id=user_id, tenant_id=tenant_id, role=role, status="1", invited_by=OWNER)

        # -- WORKSPACE, DAY ------------------------------------------------- #
        # A priced, settled chat call.
        _ledger(WORKSPACE, MEMBER_A, "settled", tokens=150, reserved_tokens=1000, cost_micros=700, reserved_cost_micros=900, model_name="chat-x")
        # A STALE reservation: written long before "now", never settled or released.
        _ledger(WORKSPACE, MEMBER_A, "reserved", reserved_tokens=500, model_name="embed-x", call_kind="embedding")
        # A dispatch that finished without reporting usage.
        _ledger(WORKSPACE, MEMBER_A, "unsettled", reserved_tokens=300, model_name="embed-x", call_kind="embedding")
        # An UNPRICED settled call.
        _ledger(WORKSPACE, MEMBER_B, "settled", tokens=40, reserved_tokens=200, model_name="chat-y")
        # A settled call whose model name was never recorded.
        _ledger(WORKSPACE, MEMBER_B, "settled", tokens=9, reserved_tokens=50, model_name="", call_kind="")
        _ledger(WORKSPACE, OWNER, "settled", tokens=20, reserved_tokens=100, cost_micros=90, reserved_cost_micros=100, model_name="chat-x")
        # An extra provider round: priced, outstanding, and still only a bound.
        _ledger(WORKSPACE, ADMIN, "reserved", reserved_tokens=70, reserved_cost_micros=80, model_name="chat-x")
        # A second day inside the same month.
        _ledger(WORKSPACE, MEMBER_A, "settled", day=DAY2, tokens=5, reserved_tokens=10, model_name="chat-x")
        # Another workspace's row: must never surface in WORKSPACE views.
        _ledger(OTHER_WORKSPACE, MEMBER_A, "settled", tokens=999, reserved_tokens=1000, cost_micros=999, model_name="chat-x")

        # -- durable counters (occupancy) ----------------------------------- #
        for user_id, calls, tokens in ((MEMBER_A, 3, 950), (MEMBER_B, 2, 49), (OWNER, 1, 20), (ADMIN, 1, 70)):
            _counter(user_id, DAY, calls, tokens)
        _counter(MEMBER_A, DAY2, 1, 5)
        for user_id, calls, tokens in ((MEMBER_A, 4, 955), (MEMBER_B, 2, 49), (OWNER, 1, 20), (ADMIN, 1, 70)):
            _counter(user_id, MONTH, calls, tokens)
        yield db
        if not db.is_closed():
            db.close()


def _snapshot():
    """Every row of every table, for the no-write assertion."""
    return {
        "ledger": sorted((row.id, row.status, row.tokens, row.reserved_tokens, row.cost_micros) for row in WorkspaceUsageLedger.select()),
        "usage": sorted((row.id, row.period, row.calls, row.tokens) for row in WorkspaceUsage.select()),
        "audit": sorted(row.id for row in WorkspaceAudit.select()),
        "members": sorted((row.id, row.role, row.status) for row in UserTenant.select()),
        "budget": sorted(row.tenant_id for row in WorkspaceBudget.select()),
    }


def _denied(call):
    with pytest.raises(WorkspaceAccessDenied):
        call()


# --------------------------------------------------------------------------- #
# scope: NORMAL own usage only
# --------------------------------------------------------------------------- #


def test_normal_member_reads_their_own_usage(usage):
    payload = read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["view"] == "my_usage"
    assert payload["scope"]["role"] == "normal"
    assert payload["scope"]["subject_user_id"] == MEMBER_A
    assert payload["scope"]["workspace_wide"] is False
    accounting = payload["accounting"]
    assert accounting["attempted_calls"] == 3
    assert accounting["settled_attempts"] == 1
    assert accounting["settled_tokens"] == 150
    assert accounting["outstanding_reserved_tokens"] == 800
    assert accounting["effective_tokens"] == 950
    # Another workspace's 999 tokens never leak into this workspace's view.
    assert accounting["settled_tokens"] != 999


def test_normal_member_cannot_read_another_member(usage):
    # The scope resolver refuses a NORMAL caller naming someone else, and every
    # workspace-wide view is refused outright.
    _denied(lambda: read.resolve_read_scope(MEMBER_A, WORKSPACE, member_user_id=MEMBER_B))
    _denied(lambda: read.quota_status(MEMBER_A, WORKSPACE, member_user_id=MEMBER_B, now=NOW))
    _denied(lambda: read.workspace_summary(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW))
    _denied(lambda: read.member_breakdown(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW))
    _denied(lambda: read.daily_series(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW))
    _denied(lambda: read.monthly_series(MEMBER_A, WORKSPACE, start_month=MONTH, end_month=MONTH, now=NOW))
    _denied(lambda: read.recorded_model_breakdown(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW))
    # A NORMAL caller naming themselves is still only their own rows.
    own = read.resolve_read_scope(MEMBER_A, WORKSPACE, member_user_id=MEMBER_A)
    assert own.subject_user_id == MEMBER_A and own.workspace_wide is False


def test_a_removed_member_cannot_read_usage(usage):
    UserTenant.delete().where((UserTenant.tenant_id == WORKSPACE) & (UserTenant.user_id == MEMBER_A)).execute()

    _denied(lambda: read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW))
    _denied(lambda: read.resolve_read_scope(MEMBER_A, WORKSPACE))
    # Their retained history still belongs to the workspace aggregate.
    summary = read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert summary["accounting"]["attempted_calls"] == 7


def test_owner_and_admin_read_the_workspace_aggregate(usage):
    expected = {
        "attempted_calls": 7,
        "settled_attempts": 4,
        "reserved_attempts": 2,
        "unsettled_attempts": 1,
        "outstanding_attempts": 3,
        "settled_tokens": 219,
        "outstanding_reserved_tokens": 870,
        "effective_tokens": 1089,
    }
    for actor in (OWNER, ADMIN):
        payload = read.workspace_summary(actor, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
        assert payload["scope"]["workspace_wide"] is True
        for key, value in expected.items():
            assert payload["accounting"][key] == value, key


def test_cross_workspace_reads_are_refused(usage):
    # The workspace owner of WORKSPACE belongs to no other workspace.
    _denied(lambda: read.workspace_summary(OWNER, OTHER_WORKSPACE, start_day=DAY, end_day=DAY, now=NOW))
    _denied(lambda: read.my_usage(OWNER, OTHER_WORKSPACE, now=NOW))
    # A total outsider cannot read this workspace at all.
    _denied(lambda: read.my_usage(OUTSIDER, WORKSPACE, now=NOW))
    _denied(lambda: read.resolve_read_scope(OUTSIDER, WORKSPACE))
    # MEMBER_A belongs to BOTH workspaces: each read returns that workspace's rows.
    other = read.my_usage(MEMBER_A, OTHER_WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert other["accounting"]["settled_tokens"] == 999
    assert other["scope"]["workspace_id"] == OTHER_WORKSPACE
    here = read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert here["accounting"]["settled_tokens"] == 150


def test_a_user_id_is_never_treated_as_a_workspace_id(usage):
    # The fixture keeps the two domains distinct on purpose.
    assert WORKSPACE not in (OWNER, ADMIN, MEMBER_A, MEMBER_B, OUTSIDER)
    # Passing a USER id where a workspace is expected finds no membership.
    for user_id in (OWNER, MEMBER_A):
        _denied(lambda user_id=user_id: read.resolve_read_scope(user_id, user_id))
        _denied(lambda user_id=user_id: read.my_usage(user_id, user_id, now=NOW))
    # The same caller reaching the real workspace succeeds, so resolution is by
    # MEMBERSHIP and not by any id comparison.
    assert read.resolve_read_scope(MEMBER_A, WORKSPACE).workspace_id == WORKSPACE


def test_multi_member_breakdown_reports_every_member(usage):
    payload = read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["view"] == "member_breakdown"
    members = {row["user_id"]: row for row in payload["data"]["members"]}
    assert set(members) == {OWNER, ADMIN, MEMBER_A, MEMBER_B}
    assert payload["data"]["total_members"] == 4
    assert payload["data"]["truncated"] is False
    assert members[MEMBER_A]["accounting"]["attempted_calls"] == 3
    assert members[MEMBER_B]["accounting"]["attempted_calls"] == 2
    assert members[OWNER]["accounting"]["attempted_calls"] == 1
    assert members[ADMIN]["accounting"]["attempted_calls"] == 1
    assert members[MEMBER_A]["role"] == "normal" and members[MEMBER_A]["live_member"] is True
    assert members[MEMBER_A]["nickname"] == MEMBER_A.upper()


def test_member_breakdown_keeps_a_removed_members_history(usage):
    UserTenant.delete().where((UserTenant.tenant_id == WORKSPACE) & (UserTenant.user_id == MEMBER_B)).execute()

    payload = read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    members = {row["user_id"]: row for row in payload["data"]["members"]}
    assert MEMBER_B in members, "a removed member's usage must not be dropped from the history"
    assert members[MEMBER_B]["live_member"] is False
    assert members[MEMBER_B]["role"] is None
    assert members[MEMBER_B]["accounting"]["attempted_calls"] == 2
    # The name is still resolvable by a LEFT-JOIN-style lookup, never an INNER JOIN.
    assert members[MEMBER_B]["name_available"] is True


def test_member_breakdown_is_paginated(usage):
    first = read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, limit=2, offset=0, now=NOW)
    second = read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, limit=2, offset=2, now=NOW)

    assert len(first["data"]["members"]) == 2
    assert first["data"]["truncated"] is True
    assert len(second["data"]["members"]) == 2
    assert second["data"]["truncated"] is False
    assert {row["user_id"] for row in first["data"]["members"]}.isdisjoint({row["user_id"] for row in second["data"]["members"]})
    # Ordering is by attempts desc, so the heaviest member leads.
    assert first["data"]["members"][0]["user_id"] == MEMBER_A


# --------------------------------------------------------------------------- #
# accounting: settled vs reserved vs unsettled
# --------------------------------------------------------------------------- #


def test_settled_reserved_and_unsettled_are_calculated_separately(usage):
    payload = read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    accounting = payload["accounting"]

    assert accounting["settled_attempts"] == 1
    assert accounting["reserved_attempts"] == 1
    assert accounting["unsettled_attempts"] == 1
    assert accounting["attempted_calls"] == 3
    assert accounting["settled_tokens"] == 150
    assert accounting["outstanding_reserved_tokens"] == 500 + 300
    assert accounting["effective_tokens"] == 150 + 500 + 300
    assert accounting["unrecognised_status_attempts"] == 0
    # The partition the cost coverage depends on.
    assert accounting["cost_established_rows"] + accounting["cost_unestablished_rows"] + accounting["zero_usage_rows"] == accounting["attempted_calls"]


def test_effective_tokens_is_the_occupancy_formula_not_a_naive_token_sum(usage):
    payload = read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    accounting = payload["accounting"]

    # Reading `tokens` alone would report only the settled part and under-report.
    assert accounting["effective_tokens"] == accounting["settled_tokens"] + accounting["outstanding_reserved_tokens"]
    assert accounting["effective_tokens"] == 1089
    assert accounting["settled_tokens"] == 219


def test_a_stale_reservation_stays_outstanding_and_is_not_running(usage):
    """A `reserved` row written long before "now" is occupancy, never activity."""
    payload = read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    accounting = payload["accounting"]

    assert accounting["reserved_attempts"] == 1
    assert accounting["outstanding_reserved_tokens"] >= 500
    # It is NOT settled and NOT zero.
    assert accounting["settled_tokens"] == 150
    assert accounting["outstanding_reserved_tokens"] != 0
    # No metric may be NAMED as if the call were still running or had really run.
    for key in accounting:
        normalised = key.replace("_", "")
        for forbidden in ("running", "inflight", "active", "providerusage", "actualusage", "reported"):
            assert forbidden not in normalised, (key, forbidden)
    # The disclaimer is carried in the payload instead.
    assert any("does not mean the call is still running" in note for note in payload["notes"])
    assert any("NOT provider-reported usage" in note for note in payload["notes"])


def test_outstanding_occupancy_is_never_labelled_as_provider_usage(usage):
    payload = read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    assert "outstanding_reserved_tokens" in payload["accounting"]
    assert payload["accounting"]["outstanding_reserved_tokens"] == 870
    assert "provider" not in payload["accounting"]
    assert any("reserved budget occupancy" in note for note in payload["notes"])


def test_day_and_month_counters_are_never_summed(usage):
    """One reservation increments a day row AND a month row: adding them doubles."""
    day = read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert day["reconciliation"]["counter_rows"] == 4
    assert day["reconciliation"]["counter_calls"] == 7

    monthly = read.monthly_series(OWNER, WORKSPACE, start_month=MONTH, end_month=MONTH, now=NOW)
    assert monthly["reconciliation"]["counter_rows"] == 4
    assert monthly["reconciliation"]["counter_calls"] == 8  # day 7 + DAY2 1, NOT 7 + 8
    assert monthly["accounting"]["effective_tokens"] == 1094


def test_daily_and_monthly_series_are_separate_buckets(usage):
    daily = read.daily_series(OWNER, WORKSPACE, start_day=DAY, end_day=DAY2, now=NOW)
    assert [bucket["period"] for bucket in daily["data"]["buckets"]] == [DAY, DAY2]
    assert [bucket["attempted_calls"] for bucket in daily["data"]["buckets"]] == [7, 1]
    assert daily["period"]["days"] == 2
    assert daily["period"]["days_with_activity"] == 2

    monthly = read.monthly_series(OWNER, WORKSPACE, start_month=MONTH, end_month=MONTH, now=NOW)
    assert [bucket["period"] for bucket in monthly["data"]["buckets"]] == [MONTH]
    assert monthly["data"]["buckets"][0]["attempted_calls"] == 8
    assert monthly["period"]["kind"] == "month"


def test_series_are_zero_filled_and_say_so(usage):
    series = read.daily_series(OWNER, WORKSPACE, start_day="2026-03-09", end_day=DAY2, now=NOW)

    buckets = {bucket["period"]: bucket for bucket in series["data"]["buckets"]}
    assert set(buckets) == {"2026-03-09", DAY, DAY2}
    empty = buckets["2026-03-09"]
    assert empty["attempted_calls"] == 0
    assert empty["accounting"]["effective_tokens"] == 0
    # A day with no metered attempt has NO pricing evidence at all: unavailable,
    # and both cost figures stay null rather than becoming a known zero.
    assert empty["accounting"]["cost_coverage"] == "unavailable"
    assert empty["accounting"]["settled_estimated_cost_micros"] is None
    assert empty["accounting"]["outstanding_reserved_cost_micros"] is None
    assert "zero_filled" in series["data"]


# --------------------------------------------------------------------------- #
# cost honesty
# --------------------------------------------------------------------------- #


def test_missing_pricing_is_unavailable_never_zero(usage):
    payload = read.my_usage(MEMBER_B, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    accounting = payload["accounting"]

    assert accounting["settled_tokens"] == 49
    assert accounting["cost_coverage"] == "unavailable"
    # Explicitly None, NOT 0: rendering this as $0.00 would be a lie.
    assert accounting["settled_estimated_cost_micros"] is None
    assert accounting["outstanding_reserved_cost_micros"] is None
    assert accounting["settled_estimated_cost_micros"] != 0
    assert payload["cost"]["term"] == "Estimated model cost"
    assert payload["cost"]["coverage"] == "unavailable"
    assert payload["cost"]["unit"] == "micro_usd"


def test_outstanding_cost_is_null_when_no_reservation_carried_pricing(usage):
    """A priced settled row must not make an UNPRICED reservation read as 0."""
    payload = read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["accounting"]["settled_estimated_cost_micros"] == 700
    assert payload["accounting"]["settled_cost_coverage"] == "complete"
    assert payload["accounting"]["outstanding_reserved_tokens"] == 800
    assert payload["accounting"]["outstanding_reserved_cost_micros"] is None
    assert payload["accounting"]["outstanding_cost_coverage"] == "unavailable"
    assert payload["accounting"]["cost_coverage"] == "partial"


def test_priced_rows_make_the_cost_available(usage):
    owner = read.my_usage(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert owner["accounting"]["settled_estimated_cost_micros"] == 90
    assert owner["accounting"]["cost_coverage"] == "complete"

    admin = read.my_usage(ADMIN, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert admin["accounting"]["outstanding_reserved_cost_micros"] == 80
    assert admin["accounting"]["cost_coverage"] == "complete"
    assert admin["accounting"]["outstanding_cost_coverage"] == "complete"


def test_workspace_cost_coverage_is_partial_when_pricing_is_mixed(usage):
    payload = read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["accounting"]["cost_coverage"] == "partial"
    assert payload["accounting"]["cost_established_rows"] == 3
    assert payload["accounting"]["cost_unestablished_rows"] == 4
    assert payload["accounting"]["settled_estimated_cost_micros"] == 790
    assert payload["accounting"]["outstanding_reserved_cost_micros"] == 80
    assert any("not a provider bill" in note for note in payload["cost"]["notes"])


def test_the_live_zero_priced_shape_reports_unavailable(usage):
    """The live deployment is 0 PRICED / 75 UNPRICED; that must read unavailable."""
    WorkspaceUsageLedger.update(cost_micros=0, reserved_cost_micros=0).execute()

    payload = read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["accounting"]["cost_coverage"] == "unavailable"
    assert payload["accounting"]["settled_estimated_cost_micros"] is None
    assert payload["accounting"]["outstanding_reserved_cost_micros"] is None
    assert payload["accounting"]["attempted_calls"] == 7
    assert payload["accounting"]["effective_tokens"] == 1089


# --------------------------------------------------------------------------- #
# historical attribution stays recorded-only
# --------------------------------------------------------------------------- #


def test_model_breakdown_is_recorded_name_only(usage):
    payload = read.recorded_model_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    buckets = {row["bucket"]: row for row in payload["data"]["models"]}
    assert set(buckets) == {"chat-x", "embed-x", "chat-y", "unrecorded"}
    assert payload["data"]["total_buckets"] == 4
    assert buckets["chat-x"]["accounting"]["attempted_calls"] == 3
    assert buckets["embed-x"]["accounting"]["attempted_calls"] == 2
    for row in payload["data"]["models"]:
        assert row["attribution"] == "recorded_model_name_only"
        # No provider, key-instance or workload reconstruction - ever.
        assert row["provider"] is None
        assert row["key_instance"] is None
        assert row["workload"] is None


def test_an_unrecorded_model_name_is_an_explicit_bucket(usage):
    payload = read.recorded_model_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    unrecorded = next(row for row in payload["data"]["models"] if row["bucket"] == "unrecorded")
    assert unrecorded["recorded_model_name"] is None
    assert unrecorded["accounting"]["attempted_calls"] == 1
    assert unrecorded["accounting"]["settled_tokens"] == 9
    assert "unrecorded" in payload["data"]["not_answered"]


def test_model_breakdown_is_paginated(usage):
    first = read.recorded_model_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, limit=2, offset=0, now=NOW)
    assert len(first["data"]["models"]) == 2
    assert first["data"]["truncated"] is True
    assert first["data"]["models"][0]["bucket"] == "chat-x"


# --------------------------------------------------------------------------- #
# reconciliation
# --------------------------------------------------------------------------- #


def test_workspace_total_reconciles_with_the_member_breakdown(usage):
    summary = read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    breakdown = read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    member_attempts = sum(row["accounting"]["attempted_calls"] for row in breakdown["data"]["members"])
    assert member_attempts == summary["accounting"]["attempted_calls"] == 7
    assert summary["reconciliation"]["member_breakdown_consistent"] is True
    assert summary["reconciliation"]["member_breakdown_attempted_calls"] == 7
    # Counters agree with the ledger on this fixture, both calls and occupancy.
    assert summary["reconciliation"]["calls_consistent"] is True
    assert summary["reconciliation"]["tokens_consistent"] is True
    assert summary["reconciliation"]["counter_calls"] == 7
    assert summary["reconciliation"]["counter_tokens"] == 1089


def test_a_counter_ledger_divergence_is_reported_not_hidden(usage):
    WorkspaceUsage.update(calls=WorkspaceUsage.calls - 1).where((WorkspaceUsage.period == DAY) & (WorkspaceUsage.user_id == MEMBER_A)).execute()

    payload = read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["reconciliation"]["calls_consistent"] is False
    assert payload["reconciliation"]["ledger_attempted_calls"] == 7
    assert payload["reconciliation"]["counter_calls"] == 6
    assert "never merged" in payload["reconciliation"]["semantics"]


# --------------------------------------------------------------------------- #
# budget: a missing row is the backend defaults
# --------------------------------------------------------------------------- #


def test_a_missing_budget_row_means_backend_defaults(usage):
    payload = read.quota_status(OWNER, WORKSPACE, now=NOW)
    data = payload["data"]

    assert data["limits_source"] == "backend_defaults"
    assert data["limits"] == {
        "calls_per_minute": 20,
        "calls_per_day": 1000,
        "calls_per_month": 20000,
        "tokens_per_day": 200000,
        "tokens_per_month": 4000000,
        "cost_micros_per_day": 0,
        "cost_micros_per_month": 0,
    }
    # The defaults are NOT zero limits and NOT unlimited calls.
    assert data["limits"]["calls_per_day"] == 1000
    assert data["zero_means_unlimited"] == ["tokens_per_day", "tokens_per_month", "cost_micros_per_day", "cost_micros_per_month"]
    assert data["limits_scope"] == "per_member"
    assert data["applies_to"] == "normal"


def test_a_zero_limit_is_not_enforced_and_has_no_remaining(usage):
    payload = read.quota_status(MEMBER_A, WORKSPACE, now=NOW)
    standing = payload["data"]["standing"]

    cost = standing["cost_micros_per_day"]
    assert cost["limit"] == 0
    assert cost["enforced"] is False
    # 0 means "not enforced", never "zero remaining".
    assert cost["remaining"] is None
    assert standing["tokens_per_day"]["limit"] == 200000
    assert standing["tokens_per_day"]["enforced"] is True
    assert standing["tokens_per_day"]["used"] == 950  # occupancy from the counters
    assert standing["tokens_per_month"]["used"] == 955
    assert standing["calls_per_day"]["used"] == 3
    assert standing["tokens_per_day"]["remaining"] == 200000 - 950


def test_quota_occupancy_matches_the_enforcement_read_source(usage):
    """The limits are compared against exactly what enforcement itself reads."""
    payload = read.quota_status(MEMBER_A, WORKSPACE, now=NOW)
    snapshot = enforcement.usage_snapshot(WORKSPACE, MEMBER_A, now=NOW)

    standing = payload["data"]["standing"]
    assert standing["tokens_per_day"]["used"] == snapshot["day"]["tokens"] == 950
    assert standing["calls_per_month"]["used"] == snapshot["month"]["calls"] == 4
    assert payload["period"]["day"] == snapshot["period_day"]
    assert payload["period"]["month"] == snapshot["period_month"]


def test_the_rolling_minute_is_reported_as_unavailable(usage):
    payload = read.quota_status(OWNER, WORKSPACE, now=NOW)
    minute = payload["data"]["standing"]["calls_per_minute"]

    assert minute["limit"] == 20
    assert minute["used"] is None
    assert minute["used_available"] is False
    assert "Redis" in minute["note"]


def test_a_configured_budget_row_is_reported_as_configured(usage):
    WorkspaceBudget.create(tenant_id=WORKSPACE, calls_per_day=7, tokens_per_day=1234, timezone="Asia/Shanghai")

    payload = read.quota_status(OWNER, WORKSPACE, now=NOW)

    assert payload["data"]["limits_source"] == "workspace_budget_row"
    assert payload["data"]["limits"]["calls_per_day"] == 7
    assert payload["data"]["limits"]["tokens_per_day"] == 1234
    assert payload["scope"]["timezone"] == "Asia/Shanghai"


def test_quota_status_reports_exemptions_and_workspace_occupancy(usage):
    for actor, exempt in ((OWNER, True), (ADMIN, True), (MEMBER_A, False)):
        payload = read.quota_status(actor, WORKSPACE, now=NOW)
        assert payload["data"]["subject"]["exempt"] is exempt
        assert payload["data"]["subject"]["live_member"] is True
        assert "PER MEMBER" in payload["data"]["not_answered"]
        occupancy = payload["data"]["workspace_occupancy"]
        if exempt:
            assert occupancy is not None
            assert occupancy["comparable_to_limits"] is False
        else:
            assert occupancy is None


def test_quota_status_for_a_removed_member(usage):
    UserTenant.delete().where((UserTenant.tenant_id == WORKSPACE) & (UserTenant.user_id == MEMBER_B)).execute()

    payload = read.quota_status(OWNER, WORKSPACE, member_user_id=MEMBER_B, now=NOW)

    subject = payload["data"]["subject"]
    assert subject["user_id"] == MEMBER_B
    assert subject["live_member"] is False
    assert subject["role"] is None
    # An inactive member is neither exempt nor subject to the limits.
    assert subject["exempt"] is None
    assert "no longer active" in payload["data"]["not_answered"]


def test_a_normal_member_cannot_request_another_members_quota(usage):
    _denied(lambda: read.quota_status(MEMBER_A, WORKSPACE, member_user_id=MEMBER_B, now=NOW))
    own = read.quota_status(MEMBER_A, WORKSPACE, now=NOW)
    assert own["data"]["subject"]["user_id"] == MEMBER_A
    assert own["data"]["workspace_occupancy"] is None


# --------------------------------------------------------------------------- #
# performance guards
# --------------------------------------------------------------------------- #


def test_a_day_range_is_bounded(usage):
    _denied(lambda: read.my_usage(MEMBER_A, WORKSPACE, start_day="2026-01-01", end_day="2026-12-31", now=NOW))
    _denied(lambda: read.workspace_summary(OWNER, WORKSPACE, start_day="2026-01-01", end_day="2026-12-31", now=NOW))
    # Exactly the cap is allowed.
    keys = read.resolve_day_range("2026-01-01", "2026-04-02", now=NOW)
    assert len(keys) == read.MAX_RANGE_DAYS


def test_a_month_range_is_bounded(usage):
    _denied(lambda: read.monthly_series(OWNER, WORKSPACE, start_month="2024-01", end_month="2026-12", now=NOW))
    keys = read.resolve_month_range("2025-01", "2026-12", now=NOW)
    assert len(keys) == read.MAX_RANGE_MONTHS


def test_a_malformed_or_inverted_range_is_refused(usage):
    for bad in ("2026-3-1", "20260310", "not-a-day", "2026-13-01", "2026-03-10T00:00:00"):
        _denied(lambda bad=bad: read.my_usage(MEMBER_A, WORKSPACE, start_day=bad, end_day=DAY, now=NOW))
    _denied(lambda: read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY2, end_day=DAY, now=NOW))
    _denied(lambda: read.monthly_series(OWNER, WORKSPACE, start_month="2026-03", end_month="2026-01", now=NOW))
    _denied(lambda: read.monthly_series(OWNER, WORKSPACE, start_month="2026-3", end_month=MONTH, now=NOW))


def test_pagination_bounds_are_enforced(usage):
    _denied(lambda: read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, limit=read.MAX_PAGE_SIZE + 1, now=NOW))
    _denied(lambda: read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, limit=0, now=NOW))
    _denied(lambda: read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, limit=-1, now=NOW))
    _denied(lambda: read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, offset=-1, now=NOW))
    _denied(lambda: read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, limit="many", now=NOW))
    _denied(lambda: read.recorded_model_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, limit=read.MAX_PAGE_SIZE + 1, now=NOW))


def test_an_unknown_view_is_refused(usage):
    _denied(lambda: read.build_view("everything", OWNER, WORKSPACE))
    _denied(lambda: read.build_view("", OWNER, WORKSPACE))
    for view in read.VIEWS:
        assert read.build_view(view, OWNER, WORKSPACE, now=NOW)["view"] == view


# --------------------------------------------------------------------------- #
# the read model is read-only
# --------------------------------------------------------------------------- #


def test_the_read_model_writes_nothing(usage):
    before = _snapshot()

    read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY2, now=NOW)
    read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY2, now=NOW)
    read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY2, now=NOW)
    read.daily_series(OWNER, WORKSPACE, start_day=DAY, end_day=DAY2, now=NOW)
    read.monthly_series(OWNER, WORKSPACE, start_month=MONTH, end_month=MONTH, now=NOW)
    read.recorded_model_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY2, now=NOW)
    read.quota_status(OWNER, WORKSPACE, now=NOW)

    assert _snapshot() == before
    # A configuration change would have written an audit row; the read model must not.
    assert WorkspaceAudit.select().count() == 0
    assert WorkspaceBudget.select().count() == 0


def test_the_read_path_never_takes_the_budget_write_lock(usage, monkeypatch):
    """`configure_budget` locks the tenant row; the read model must not use it."""
    source = Path(read.__file__).read_text(encoding="utf-8")
    assert "configure_budget" not in source

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the read model must not take the tenant self-update lock")

    monkeypatch.setattr(Tenant, "update", forbidden)
    read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    read.workspace_summary(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    read.daily_series(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    read.monthly_series(OWNER, WORKSPACE, start_month=MONTH, end_month=MONTH, now=NOW)
    read.recorded_model_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert read.quota_status(OWNER, WORKSPACE, now=NOW)["data"]["limits_source"] == "backend_defaults"


# --------------------------------------------------------------------------- #
# the API layer
# --------------------------------------------------------------------------- #


def _load_api_module():
    """Load the blueprint the way `api.apps.register_page` does.

    `api.apps` is deliberately NOT booted here. Importing it registers every API
    blueprint in the process, which starts import-time clients and leaves
    unclosed sockets; pytest escalates those ResourceWarnings at teardown and a
    fully green run would then exit non-zero. The route module needs only two
    names from it, so they are stubbed for the duration of the load.
    """
    import types

    from quart import Blueprint

    stub = types.ModuleType("api.apps")
    stub.current_user = SimpleNamespace(id="stub-user")
    stub.login_required = lambda func: func

    path = Path(read.__file__).resolve().parents[2] / "apps" / "restful_apis" / "workspace_usage_api.py"
    spec = importlib.util.spec_from_file_location("workspace_usage_api_under_test", path)
    module = importlib.util.module_from_spec(spec)
    module.manager = Blueprint("workspace_usage_api_under_test", __name__)
    sys.modules[spec.name] = module

    # EXACTLY ONE KEY is substituted, and exactly one key is put back. This must
    # not be `unittest.mock.patch.dict`: on exit that helper clears the whole
    # `sys.modules` mapping and repopulates it from a snapshot taken on entry, so
    # every module this load imported for the FIRST time is evicted. The chain
    # `api.utils.api_utils -> common.mcp_tool_call_conn -> mcp -> mcp.types` is one
    # of them, and `mcp.types` lazily registers `pydantic.root_model` while it
    # builds `class JSONRPCMessage(RootModel[...])`. A second load in the same
    # process then re-executes that class body, and pydantic's generic-submodel
    # machinery does `sys.modules[created_model.__module__]` -> KeyError:
    # 'pydantic.root_model'. Restoring one key leaves everything the load imported
    # resident, which is what a real `import` does.
    absent = object()
    previous = sys.modules.get("api.apps", absent)
    sys.modules["api.apps"] = stub
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is absent:
            sys.modules.pop("api.apps", None)
        else:
            sys.modules["api.apps"] = previous
    return module


def test_the_api_layer_exposes_exactly_the_frozen_views():
    from quart import Quart

    module = _load_api_module()
    app = Quart(__name__)
    app.register_blueprint(module.manager, url_prefix="/api/v1")
    rules = {rule.rule: rule.methods for rule in app.url_map.iter_rules() if rule.rule.startswith("/api/v1/tenants")}

    assert set(rules) == {
        "/api/v1/tenants/<tenant_id>/usage/my",
        "/api/v1/tenants/<tenant_id>/usage/summary",
        "/api/v1/tenants/<tenant_id>/usage/members",
        "/api/v1/tenants/<tenant_id>/usage/member-report",
        "/api/v1/tenants/<tenant_id>/usage/daily",
        "/api/v1/tenants/<tenant_id>/usage/monthly",
        "/api/v1/tenants/<tenant_id>/usage/models",
        "/api/v1/tenants/<tenant_id>/usage/quota",
    }
    for methods in rules.values():
        # Read-only surface: no route accepts anything but GET (plus HEAD/OPTIONS).
        assert methods <= {"GET", "HEAD", "OPTIONS"}, methods
    assert set(module.VIEW_PARAMS) == set(read.VIEWS)


def test_the_api_layer_maps_every_parameter_to_a_view_keyword():
    module = _load_api_module()
    import inspect

    for view, params in module.VIEW_PARAMS.items():
        signature = inspect.signature(read.VIEWS[view])
        for keyword in params.values():
            assert keyword in signature.parameters, (view, keyword)
    assert "start_day" not in module.VIEW_PARAMS["quota_status"]
    assert module.VIEW_PARAMS["quota_status"]["user_id"] == "member_user_id"
    # Naming one member is one question with two accepted spellings, and the view it
    # reaches takes exactly one keyword for it.
    member_params = module.VIEW_PARAMS["member_report"]
    assert member_params["user_id"] == member_params["member_user_id"] == "member_user_id"
    assert set(member_params) == {"user_id", "member_user_id", "start_day", "end_day", "limit", "offset"}


# --------------------------------------------------------------------------- #
# member report: one member's window, composed from the same primitives
# --------------------------------------------------------------------------- #


def test_an_owner_reads_one_members_report(usage):
    payload = read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["view"] == "member_report"
    assert payload["scope"]["subject_user_id"] == MEMBER_A
    assert payload["scope"]["workspace_wide"] is False
    assert payload["data"]["member"] == {
        "user_id": MEMBER_A,
        "nickname": MEMBER_A.upper(),
        "name_available": True,
        "live_member": True,
        "role": "normal",
    }
    # The report is the member's own read, named: same predicate, same figures.
    own = read.my_usage(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert payload["accounting"] == own["accounting"]
    assert payload["period"]["days"] == 1
    assert payload["period"]["days_with_activity"] == 1


def test_an_admin_reads_one_members_report(usage):
    payload = read.member_report(ADMIN, WORKSPACE, member_user_id=MEMBER_B, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["data"]["member"]["user_id"] == MEMBER_B
    assert payload["accounting"]["attempted_calls"] == 2
    buckets = {row["bucket"] for row in payload["data"]["models"]["models"]}
    # One of MEMBER_B's calls recorded no model name, so it is an explicit bucket.
    assert buckets == {"chat-y", read.UNRECORDED_MODEL}


def test_a_normal_member_reads_their_own_report(usage):
    payload = read.member_report(MEMBER_A, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["data"]["member"]["user_id"] == MEMBER_A


def test_a_normal_member_cannot_read_another_members_report(usage):
    _denied(
        lambda: read.member_report(MEMBER_A, WORKSPACE, member_user_id=MEMBER_B, start_day=DAY, end_day=DAY, now=NOW)
    )


def test_a_report_without_a_named_member_is_the_callers_own(usage):
    # The same rule `quota_status` follows: an unnamed subject resolves to the actor,
    # so no second convention about whose rows are read exists in this module.
    payload = read.member_report(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert payload["data"]["member"]["user_id"] == OWNER
    assert payload["accounting"] == read.my_usage(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)["accounting"]

    # A NORMAL member cannot use the omission to reach anyone but themselves.
    own = read.member_report(MEMBER_A, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert own["data"]["member"]["user_id"] == MEMBER_A


def test_only_a_live_member_of_the_path_workspace_may_read_a_report(usage):
    # An owner of ANOTHER workspace is not a member here, whatever they ask for.
    _denied(
        lambda: read.member_report(OUTSIDER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY, now=NOW)
    )


def test_a_removed_members_report_stays_readable(usage):
    UserTenant.delete().where((UserTenant.tenant_id == WORKSPACE) & (UserTenant.user_id == MEMBER_B)).execute()

    payload = read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_B, start_day=DAY, end_day=DAY, now=NOW)

    member = payload["data"]["member"]
    assert member["live_member"] is False
    assert member["role"] is None
    # The name is looked up separately, never joined destructively.
    assert member["name_available"] is True
    assert member["nickname"] == MEMBER_B.upper()
    assert payload["accounting"]["attempted_calls"] == 2


def test_a_removed_actor_cannot_read_any_report(usage):
    UserTenant.delete().where((UserTenant.tenant_id == WORKSPACE) & (UserTenant.user_id == MEMBER_A)).execute()

    _denied(
        lambda: read.member_report(MEMBER_A, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY, now=NOW)
    )


def test_the_report_matches_the_members_row_in_the_breakdown(usage):
    breakdown = read.member_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    rows = {row["user_id"]: row for row in breakdown["data"]["members"]}

    for user_id in (MEMBER_A, MEMBER_B, OWNER, ADMIN):
        report = read.member_report(OWNER, WORKSPACE, member_user_id=user_id, start_day=DAY, end_day=DAY, now=NOW)
        assert report["accounting"] == rows[user_id]["accounting"], user_id


def test_the_daily_buckets_sum_to_the_reported_attempts(usage):
    payload = read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY2, now=NOW)

    buckets = payload["data"]["daily"]["buckets"]
    assert [bucket["period"] for bucket in buckets] == [DAY, DAY2]
    assert sum(bucket["attempted_calls"] for bucket in buckets) == 4
    assert payload["accounting"]["attempted_calls"] == 4
    assert payload["data"]["daily"]["granularity"] == "day"


def test_the_month_buckets_cover_the_months_the_day_window_spans(usage):
    payload = read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY2, now=NOW)

    months = payload["data"]["monthly"]["buckets"]
    assert [bucket["period"] for bucket in months] == [MONTH]
    assert months[0]["attempted_calls"] == payload["accounting"]["attempted_calls"] == 4


def test_a_member_report_never_carries_another_members_or_workspaces_rows(usage):
    payload = read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY, now=NOW)

    # MEMBER_A also has rows in OTHER_WORKSPACE (999 tokens): only this workspace's count.
    assert payload["accounting"]["settled_tokens"] == 150
    assert payload["accounting"]["attempted_calls"] == 3
    assert {row["bucket"] for row in payload["data"]["models"]["models"]} == {"chat-x", "embed-x"}
    workspace_models = read.recorded_model_breakdown(OWNER, WORKSPACE, start_day=DAY, end_day=DAY, now=NOW)
    assert workspace_models["accounting"]["attempted_calls"] > payload["accounting"]["attempted_calls"]


def test_a_subject_with_no_rows_in_this_workspace_reports_a_zero_window(usage):
    # The predicate stays scoped to the path workspace, so an unrelated subject gets an
    # empty window - never another workspace's figures.
    payload = read.member_report(OWNER, WORKSPACE, member_user_id=OUTSIDER, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["accounting"]["attempted_calls"] == 0
    assert payload["accounting"]["effective_tokens"] == 0
    assert payload["data"]["daily"]["buckets"][0]["attempted_calls"] == 0
    assert payload["data"]["models"]["models"] == []
    assert payload["data"]["member"]["live_member"] is False
    assert payload["data"]["member"]["role"] is None


def test_unpriced_rows_leave_the_member_cost_unavailable_never_zero(usage):
    payload = read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_B, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["accounting"]["settled_estimated_cost_micros"] is None
    assert payload["accounting"]["settled_cost_coverage"] == "unavailable"
    assert payload["cost"]["settled_coverage"] == "unavailable"


def test_priced_rows_make_the_member_cost_available(usage):
    payload = read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY, now=NOW)

    assert payload["accounting"]["settled_estimated_cost_micros"] == 700
    assert payload["accounting"]["settled_cost_coverage"] == "complete"
    # The reservation carries no pricing, so the OUTSTANDING figure stays null while the
    # settled one is known: the two are gated independently.
    assert payload["accounting"]["outstanding_reserved_cost_micros"] is None
    assert payload["accounting"]["outstanding_cost_coverage"] != "complete"


def test_the_member_report_reconciles_against_that_members_counters(usage):
    payload = read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY, now=NOW)

    reconciliation = payload["reconciliation"]
    assert reconciliation["ledger_attempted_calls"] == 3
    assert reconciliation["counter_calls"] == 3
    assert reconciliation["calls_consistent"] is True


def test_the_member_report_range_rules_match_every_other_view(usage):
    _denied(lambda: read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY2, end_day=DAY, now=NOW))
    _denied(
        lambda: read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day="2026-3-1", end_day=DAY, now=NOW)
    )
    _denied(
        lambda: read.member_report(
            OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day="2025-01-01", end_day=DAY, now=NOW
        )
    )


def test_the_member_report_pages_the_model_buckets(usage):
    payload = read.member_report(
        OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY, limit=1, offset=0, now=NOW
    )

    assert len(payload["data"]["models"]["models"]) == 1
    assert payload["data"]["models"]["limit"] == 1
    assert payload["data"]["models"]["truncated"] is True


def test_the_member_report_writes_nothing(usage):
    before = _snapshot()

    read.member_report(OWNER, WORKSPACE, member_user_id=MEMBER_A, start_day=DAY, end_day=DAY, now=NOW)

    assert _snapshot() == before
