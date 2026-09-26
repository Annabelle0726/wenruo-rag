"""Token/cost reserve-settle, workspace timezone boundaries, detached attribution."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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
from api.db.services import workspace_budget_service as budget
from common.exceptions import WorkspaceAccessDenied
from common.model_budget import budgeted, dispatch_reservation, estimate_prompt_tokens, pricing_of, record_dispatch_usage
from common.workspace_context import execution_refusal, execution_user


class AdmittingRedis:
    """Stands in for the Lua rolling-window gate."""

    def __init__(self):
        self.calls = []

    def eval(self, script, nkeys, key, *args):
        self.calls.append((key, args))
        return 1


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    models = [Tenant, User, UserTenant, WorkspaceAudit, WorkspaceBudget, WorkspaceUsage, WorkspaceUsageLedger]
    db = SqliteDatabase(tmp_path / "budget.sqlite", timeout=20)
    with db.bind_ctx(models):
        db.create_tables(models)
        monkeypatch.setattr(budget, "DB", db)
        redis = AdmittingRedis()
        monkeypatch.setattr(budget, "REDIS_CONN", SimpleNamespace(REDIS=redis))
        for tenant in ("workspace", "other"):
            Tenant.create(id=tenant, name=tenant, llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="", parser_ids="")
        for user, role in (("owner", "owner"), ("admin", "admin"), ("member", "normal")):
            User.create(id=user, nickname=user, email=user + "@example.test", current_tenant_id="workspace")
            UserTenant.create(id=user, user_id=user, tenant_id="workspace", role=role, invited_by="owner")
        yield db, redis
        if not db.is_closed():
            db.close()


def _limits(**overrides):
    values = {
        "calls_per_minute": 20,
        "calls_per_day": 1000,
        "calls_per_month": 20000,
        "tokens_per_day": 100000,
        "tokens_per_month": 2000000,
        "cost_micros_per_day": 0,
        "cost_micros_per_month": 0,
    }
    values.update(overrides)
    return values


def _rows(user_id="member"):
    """Every counter row of a member: the day row and the month row."""
    return list(WorkspaceUsage.select().where(WorkspaceUsage.user_id == user_id))


def _tokens(user_id="member"):
    return {row.tokens for row in _rows(user_id)}


def test_settlement_charges_actual_and_releases_the_bound(workspace):
    budget.configure_budget("workspace", "owner", _limits())
    reservation = budget.reserve_call("workspace", "member", model_name="chat-x", model_type="chat", reserved_tokens=1000)
    assert reservation
    assert _tokens() == {1000}  # the bound is held while in flight
    assert WorkspaceUsageLedger.get_by_id(reservation).status == "reserved"

    result = budget.settle_dispatch(reservation, prompt_tokens=100, completion_tokens=50, total_tokens=150)

    assert result["status"] == "settled" and result["released_tokens"] == 850
    for row in _rows():
        assert (row.tokens, row.prompt_tokens, row.completion_tokens) == (150, 100, 50)
    ledger = WorkspaceUsageLedger.get_by_id(reservation)
    assert (ledger.status, ledger.tokens, ledger.prompt_tokens, ledger.completion_tokens) == ("settled", 150, 100, 50)
    assert ledger.period_day and ledger.period_month and ledger.settled_at


def test_second_settlement_is_a_no_op(workspace):
    budget.configure_budget("workspace", "owner", _limits())
    reservation = budget.reserve_call("workspace", "member", reserved_tokens=1000)
    budget.settle_dispatch(reservation, total_tokens=150)

    again = budget.settle_dispatch(reservation, total_tokens=5000)

    assert again["duplicate"] is True
    assert _tokens() == {150}


def test_unreported_dispatch_keeps_its_whole_reservation(workspace):
    budget.configure_budget("workspace", "owner", _limits())
    reservation = budget.reserve_call("workspace", "member", reserved_tokens=1000)

    assert budget.release_dispatch(reservation)["status"] == "unsettled"

    assert WorkspaceUsageLedger.get_by_id(reservation).status == "unsettled"
    assert _tokens() == {1000}  # never refunded
    # A late settlement cannot resurrect it either.
    assert budget.settle_dispatch(reservation, total_tokens=10)["duplicate"] is True
    assert _tokens() == {1000}


def test_settlement_tops_up_when_the_provider_reports_more(workspace):
    budget.configure_budget("workspace", "owner", _limits())
    reservation = budget.reserve_call("workspace", "member", reserved_tokens=10)

    budget.settle_dispatch(reservation, total_tokens=100)

    assert _tokens() == {100}


def test_token_limit_refuses_before_dispatch_and_frees_room_on_settlement(workspace):
    budget.configure_budget("workspace", "owner", _limits(tokens_per_day=100, tokens_per_month=100))
    first = budget.reserve_call("workspace", "member", reserved_tokens=60)
    with pytest.raises(WorkspaceAccessDenied, match="Token"):
        budget.reserve_call("workspace", "member", reserved_tokens=60)

    budget.settle_dispatch(first, total_tokens=1)

    assert budget.reserve_call("workspace", "member", reserved_tokens=60)


def test_cost_limit_needs_a_model_that_states_pricing(workspace):
    budget.configure_budget("workspace", "owner", _limits(cost_micros_per_day=1000, cost_micros_per_month=1000))
    first = budget.reserve_call("workspace", "member", reserved_cost_micros=800)
    with pytest.raises(WorkspaceAccessDenied, match="费用"):
        budget.reserve_call("workspace", "member", reserved_cost_micros=800)

    budget.settle_dispatch(first, total_tokens=10, cost_micros=300)

    assert {row.cost_micros for row in _rows()} == {300}
    assert budget.reserve_call("workspace", "member", reserved_cost_micros=700)


def test_a_zero_token_limit_means_unlimited(workspace):
    budget.configure_budget("workspace", "owner", _limits(tokens_per_day=0, tokens_per_month=0))
    reservation = budget.reserve_call("workspace", "member", reserved_tokens=10**9)
    assert WorkspaceUsageLedger.get_by_id(reservation).reserved_tokens == 10**9
    assert _tokens() == {10**9}


@pytest.mark.parametrize(
    "moment,tz,expected",
    [
        (datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc), "Asia/Shanghai", ("2026-01-02", "2026-01")),
        (datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc), "UTC", ("2026-01-01", "2026-01")),
        (datetime(2026, 2, 28, 23, 30, tzinfo=timezone.utc), "Pacific/Kiritimati", ("2026-03-01", "2026-03")),
        (datetime(2026, 3, 1, 2, 0, tzinfo=timezone.utc), "Pacific/Honolulu", ("2026-02-28", "2026-02")),
    ],
)
def test_periods_follow_the_workspace_calendar(moment, tz, expected):
    assert budget.current_periods(tz, now=moment) == expected


def test_timezone_is_validated_on_write_and_forgiven_on_read(workspace):
    budget.configure_budget("workspace", "owner", {"timezone": "Asia/Shanghai"})
    assert WorkspaceBudget.get_by_id("workspace").timezone == "Asia/Shanghai"
    with pytest.raises(WorkspaceAccessDenied, match="未知时区"):
        budget.configure_budget("workspace", "owner", {"timezone": "Mars/Phobos"})
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "owner", {"timezone": ""})
    # A stored zone the host cannot resolve changes only the boundary: the call
    # proceeds on UTC instead of failing closed.
    WorkspaceBudget.update(timezone="Mars/Phobos").where(WorkspaceBudget.tenant_id == "workspace").execute()
    assert budget.current_periods(WorkspaceBudget.get_by_id("workspace").timezone) == budget.current_periods("UTC")


def test_reservation_counter_takes_the_workspace_zone(workspace):
    budget.configure_budget("workspace", "owner", {"timezone": "Pacific/Kiritimati"})
    moment = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)
    reservation = budget.reserve_call("workspace", "member", reserved_tokens=5, now=moment)

    ledger = WorkspaceUsageLedger.get_by_id(reservation)
    assert (ledger.timezone, ledger.period_day, ledger.period_month) == ("Pacific/Kiritimati", "2026-01-02", "2026-01")
    assert {row.period for row in _rows()} == {"2026-01-02", "2026-01"}
    # The UTC day would have been a different row; nothing was written there.
    assert not WorkspaceUsage.select().where(WorkspaceUsage.period == "2026-01-01").exists()


def test_concurrent_reservations_cannot_oversubscribe_tokens(workspace):
    budget.configure_budget("workspace", "owner", _limits(tokens_per_day=100, tokens_per_month=100, calls_per_day=1000))

    def reserve(_):
        try:
            budget.reserve_call("workspace", "member", reserved_tokens=30)
            return True
        except WorkspaceAccessDenied:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = sum(pool.map(reserve, range(8)))

    assert admitted == 3  # 3 x 30 fits in 100; the fourth would be 120
    assert _tokens() == {90}


def test_manager_usage_is_recorded_but_never_denied(workspace):
    budget.configure_budget("workspace", "owner", _limits(tokens_per_day=1, tokens_per_month=1, calls_per_day=1, calls_per_month=1))

    reservation = budget.reserve_call("workspace", "owner", reserved_tokens=5000)
    budget.settle_dispatch(reservation, prompt_tokens=7, completion_tokens=3, total_tokens=10)

    assert WorkspaceUsageLedger.get_by_id(reservation).user_id == "owner"
    assert {(row.calls, row.tokens) for row in _rows("owner")} == {(1, 10)}


def test_every_reservation_revalidates_membership(workspace):
    UserTenant.delete().where((UserTenant.tenant_id == "workspace") & (UserTenant.user_id == "member")).execute()
    with pytest.raises(WorkspaceAccessDenied, match="无权"):
        budget.reserve_call("workspace", "member", reserved_tokens=1)


def test_estimate_and_bound_from_the_call_shape():
    def chat(self, system, history, gen_conf={}):
        pass

    assert estimate_prompt_tokens({"system": "you are a bot", "history": [{"role": "user", "content": "hello" * 50}]}) > 0
    assert estimate_prompt_tokens({"texts": ["a" * 400, "b" * 400]}) > 100
    assert estimate_prompt_tokens({"image": b"\x00" * 100}) == 0

    prompt = estimate_prompt_tokens({"system": "sys", "history": [{"role": "user", "content": "x" * 400}]})
    tokens, cost = dispatch_reservation({"max_tokens": 128000, "pricing": {"input_per_million": 0.3, "output_per_million": 1.2}}, chat, (None, "sys", [{"role": "user", "content": "x" * 400}]), {})
    # The output bound is capped well below the model's context window, and the
    # bound is priced: 8192 output tokens at 1.2 micro-USD each dominates.
    assert tokens == prompt + 8192
    assert cost > 8192
    assert pricing_of({"pricing": {"input_per_million": "0.5", "output_per_million": None}}) == (0.5, 0.0)
    assert pricing_of({}) == (0.0, 0.0)


def test_budgeted_dispatch_settles_from_the_reported_usage(workspace):
    budget.configure_budget("workspace", "owner", _limits())

    class Model:
        tenant_id = "workspace"
        model_config = {"llm_name": "chat-x", "model_type": "chat", "max_tokens": 1024}

        @budgeted
        def call(self, system, history):
            record_dispatch_usage(prompt_tokens=20, completion_tokens=5, total_tokens=25)
            return "ok"

    token = execution_user.set("member")
    try:
        assert Model().call("sys", [{"role": "user", "content": "hi"}]) == "ok"
    finally:
        execution_user.reset(token)

    ledger = WorkspaceUsageLedger.select().first()
    assert (ledger.status, ledger.model_name, ledger.call_kind) == ("settled", "chat-x", "chat")
    assert (ledger.tokens, ledger.prompt_tokens, ledger.completion_tokens) == (25, 20, 5)
    assert ledger.reserved_tokens > 25
    assert _tokens() == {25}


def test_a_dispatch_that_reports_nothing_keeps_its_reservation(workspace):
    budget.configure_budget("workspace", "owner", _limits())

    class Model:
        tenant_id = "workspace"
        model_config = {"llm_name": "chat-x", "model_type": "chat", "max_tokens": 16}

        @budgeted
        async def stream(self, system, history):
            yield "partial"

    async def run():
        token = execution_user.set("member")
        try:
            generator = Model().stream("sys", [{"role": "user", "content": "hi"}])
            assert await anext(generator) == "partial"
            await generator.aclose()  # the client disconnects mid-stream
        finally:
            execution_user.reset(token)

    asyncio.run(run())

    ledger = WorkspaceUsageLedger.select().first()
    assert ledger.status == "unsettled"
    assert ledger.reserved_tokens > 0
    assert _tokens() == {ledger.reserved_tokens}


def test_budgeted_dispatch_without_an_actor_is_not_metered(workspace):
    class Model:
        tenant_id = "workspace"
        model_config = {"llm_name": "chat-x", "model_type": "chat"}

        @budgeted
        def call(self, system, history):
            record_dispatch_usage(total_tokens=99)
            return "ok"

    assert Model().call("sys", []) == "ok"
    assert WorkspaceUsageLedger.select().count() == 0


def test_attribute_detached_job_uses_the_initiator(workspace):
    with budget.attribute_detached_job("workspace", "member") as actor:
        assert actor == "member"
        assert execution_user.get() == "member"
        assert execution_refusal.get() == {}
    assert execution_user.get() is None
    assert execution_refusal.get() is None


def test_attribute_detached_job_fences_a_removed_initiator(workspace):
    UserTenant.delete().where((UserTenant.tenant_id == "workspace") & (UserTenant.user_id == "member")).execute()
    with pytest.raises(WorkspaceAccessDenied, match="已不在工作区"):
        with budget.attribute_detached_job("workspace", "member"):
            pass
    assert execution_user.get() is None


def test_attribute_detached_job_falls_back_to_the_owner(workspace):
    tokens = budget.enter_detached_job("workspace", None)
    try:
        assert execution_user.get() == "owner"
    finally:
        budget.exit_detached_job(tokens)
    assert execution_user.get() is None


def test_attribute_detached_job_without_a_workspace_stays_unmetered(workspace):
    with budget.attribute_detached_job(None, "member") as actor:
        assert actor is None
        assert execution_user.get() is None


def test_attribute_detached_job_resets_identity_after_a_failure(workspace):
    with pytest.raises(RuntimeError):
        with budget.attribute_detached_job("workspace", "member"):
            assert execution_user.get() == "member"
            raise RuntimeError("worker blew up")
    assert execution_user.get() is None


def test_detached_job_calls_are_charged_to_its_initiator(workspace):
    budget.configure_budget("workspace", "owner", _limits())

    class Model:
        tenant_id = "workspace"
        model_config = {"llm_name": "embed-x", "model_type": "embedding", "max_tokens": 64}

        @budgeted
        def embed(self, texts):
            record_dispatch_usage(prompt_tokens=40, total_tokens=40)
            return [[0.0], [0.0]]

    with budget.attribute_detached_job("workspace", "member"):
        Model().embed(["a" * 400, "b" * 400])

    ledger = WorkspaceUsageLedger.select().first()
    assert (ledger.user_id, ledger.status, ledger.tokens) == ("member", "settled", 40)
    assert _tokens() == {40}


def test_budget_read_reports_limits_usage_and_zone(workspace):
    budget.configure_budget("workspace", "owner", {"timezone": "Asia/Shanghai", "tokens_per_day": 500})
    reservation = budget.reserve_call("workspace", "member", reserved_tokens=10)
    budget.settle_dispatch(reservation, prompt_tokens=4, completion_tokens=1, total_tokens=5)

    payload = budget.configure_budget("workspace", "owner")

    assert payload["timezone"] == "Asia/Shanghai"
    assert payload["tokens_per_day"] == 500
    assert payload["unit"] == "model_calls"
    assert payload["cost_unit"] == "micro_usd"
    # Day and month are reported separately: one reservation increments both, so
    # a single summed total would double count it.
    assert payload["used"]["day"] == {"calls": 1, "tokens": 5, "prompt_tokens": 4, "completion_tokens": 1, "cost_micros": 0}
    assert payload["used"]["month"]["tokens"] == 5
    assert payload["used"]["members"]["member"]["day"]["tokens"] == 5
    assert payload["used"]["period_day"] and payload["used"]["period_month"]
    assert payload["zero_means_unlimited"] == ["tokens_per_day", "tokens_per_month", "cost_micros_per_day", "cost_micros_per_month"]


def test_budget_write_rejects_unknown_fields_and_negative_values(workspace):
    with pytest.raises(WorkspaceAccessDenied, match="未知的额度字段"):
        budget.configure_budget("workspace", "owner", {"calls_per_minute": 5, "tokens_per_week": 5})
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "owner", {"tokens_per_day": -1})
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "owner", {"calls_per_minute": 0})
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "owner", {})
    # A partial update is allowed and audited; untouched limits keep their value.
    budget.configure_budget("workspace", "owner", _limits(calls_per_minute=7))
    payload = budget.configure_budget("workspace", "owner", {"tokens_per_day": 12})
    assert payload["calls_per_minute"] == 7 and payload["tokens_per_day"] == 12
    assert WorkspaceAudit.select().count() == 2


def test_settlement_of_a_deleted_counter_is_survivable(workspace):
    budget.configure_budget("workspace", "owner", _limits())
    reservation = budget.reserve_call("workspace", "member", reserved_tokens=100)
    WorkspaceUsage.delete().execute()  # an operator reset the counters mid-call

    assert budget.settle_dispatch(reservation, total_tokens=5)["status"] == "settled"
    assert WorkspaceUsage.select().count() == 0
    assert WorkspaceUsageLedger.get_by_id(reservation).status == "settled"


def test_settlement_of_an_unknown_reservation_is_ignored(workspace):
    assert budget.settle_dispatch(uuid4().hex, total_tokens=1) == {"status": "missing"}
    assert budget.settle_dispatch(None) == {"status": "missing"}
    assert budget.release_dispatch(None) == {"status": "missing"}
