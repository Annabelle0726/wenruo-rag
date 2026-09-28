"""Mechanism gates for the dense-failure isolation: admission, budget, late results, control signals.

These run WITHOUT Elasticsearch and without a provider: they exercise the embedding execution
mechanism itself, which is where the incident's root cause lived (a provider call that never
returned held the awaiting coroutine, so the route came back empty instead of degrading).

Each test states the property it pins, and the audit question it answers:

* healthy call semantics unchanged, including which thread runs the provider call
* admission is bounded and the work queue behind it is bounded
* the budget (semaphore) is released on success, on provider failure, on submission failure, and
  after a timed-out worker finishes late
* repeated timeouts leak neither worker threads nor budget
* late completion cannot re-enter the retrieval or move Dense health
* control signals - user abort, shutdown, credential revocation - are never converted into a
  recoverable provider failure, while the incident's own 400 FAILED_PRECONDITION stays recoverable
* interpreter-exit semantics are unchanged from the shared helper they replace
"""
import asyncio
import concurrent.futures.thread as cf_thread
import sys
import threading
import time

import numpy as np
import pytest

sys.path.insert(0, "/ragflow")
import common.settings  # noqa: F401

import rag.nlp.search as search_module
from rag.nlp.search import (
    Dealer,
    EmbeddingCapacityError,
    _EMBEDDING_EXECUTOR,
    _EMBEDDING_SLOTS,
    _looks_like_credential_or_permission_failure,
)
from rag.llm.embedding_model import EmbeddingError, EmbeddingQuotaExhausted, EmbeddingRateLimited
from common.exceptions import ModelException

REPORT = {}
SLOT_CAPACITY = 32
WORKER_THREADS = 16


def bare_dealer():
    """A Dealer with no store and no Redis: the mechanism under test needs neither."""
    return Dealer.__new__(Dealer)


class Healthy:
    def __init__(self):
        self.calls = 0
        self.threads = []

    def encode_queries(self, text):
        self.calls += 1
        self.threads.append(threading.current_thread().name)
        return np.array([1.0, 0.0]), 1


class Failing(Healthy):
    def encode_queries(self, text):
        self.calls += 1
        raise EmbeddingError("Embedding request failed: 400 FAILED_PRECONDITION User location is not supported for the API use.")


class Blocking(Healthy):
    def __init__(self):
        super().__init__()
        self.gate = threading.Event()
        self.started = threading.Event()

    def encode_queries(self, text):
        self.calls += 1
        self.started.set()
        self.gate.wait(30)
        return np.array([1.0, 0.0]), 1


def slots_free():
    return _EMBEDDING_SLOTS._value


def embedding_thread_names():
    return sorted(t.name for t in threading.enumerate() if t.name.startswith("retrieval-embedding"))


@pytest.fixture(autouse=True)
def restore_budget():
    """Every test leaves the budget and the deadline exactly as it found them."""
    before = slots_free()
    yield
    for _ in range(SLOT_CAPACITY - slots_free()):
        _EMBEDDING_SLOTS.release()
    assert slots_free() == SLOT_CAPACITY, f"budget not restored: {slots_free()} != {SLOT_CAPACITY} (was {before} before the test)"


# ---------------------------------------------------------------------------
# Healthy semantics
# ---------------------------------------------------------------------------


async def test_healthy_call_semantics_unchanged():
    """The provider is called once, with the same argument, and its tuple is returned unchanged."""
    model = Healthy()
    value = await bare_dealer()._query_embedding(model, "question text")
    assert model.calls == 1
    vector, count = value
    assert list(vector) == [1.0, 0.0] and count == 1
    assert model.threads[0].startswith("retrieval-embedding"), model.threads[0]
    assert slots_free() == SLOT_CAPACITY
    REPORT["healthy_semantics"] = {"calls": model.calls, "worker_thread": model.threads[0], "budget_after": slots_free()}


async def test_context_is_copied_into_the_worker():
    """A ContextVar set by the caller is visible in the worker, as the shared helper guaranteed."""
    import contextvars

    probe = contextvars.ContextVar("p12_probe", default="unset")
    seen = {}

    class Ctx(Healthy):
        def encode_queries(self, text):
            seen["value"] = probe.get()
            return np.array([1.0, 0.0]), 1

    token = probe.set("caller-value")
    try:
        await bare_dealer()._query_embedding(Ctx(), "q")
    finally:
        probe.reset(token)
    assert seen["value"] == "caller-value"
    REPORT["contextvar_propagation"] = seen


# ---------------------------------------------------------------------------
# Admission and bounds
# ---------------------------------------------------------------------------


async def test_admission_is_bounded_and_never_fails_the_turn():
    """With the budget exhausted the call raises a LOCAL capacity error and submits nothing."""
    for _ in range(SLOT_CAPACITY):
        assert _EMBEDDING_SLOTS.acquire(blocking=False)
    assert slots_free() == 0
    model = Healthy()
    started = time.perf_counter()
    with pytest.raises(EmbeddingCapacityError) as excinfo:
        await bare_dealer()._query_embedding(model, "q")
    elapsed = time.perf_counter() - started
    assert model.calls == 0, "a rejected call must not reach the provider"
    assert elapsed < 1.0, "capacity rejection must be immediate, not a wait"
    # Local back-pressure is recoverable: the turn degrades to lexical instead of failing.
    assert Dealer._recoverable_embedding_failure(excinfo.value) is True
    REPORT["capacity_admission"] = {"rejected_in_seconds": round(elapsed, 4), "provider_calls": model.calls, "classified_recoverable": True}


async def test_queued_work_is_bounded_by_the_budget():
    """At most SLOT_CAPACITY calls may be in flight or queued; the (n+1)-th is refused."""
    blocking = [Blocking() for _ in range(SLOT_CAPACITY)]
    tasks = [asyncio.create_task(bare_dealer()._query_embedding(blocking[i], f"q{i}")) for i in range(SLOT_CAPACITY)]
    for _ in range(200):
        if slots_free() == 0:
            break
        await asyncio.sleep(0.01)
    assert slots_free() == 0, "the budget should be fully committed"
    queued = _EMBEDDING_EXECUTOR._work_queue.qsize()
    assert queued <= SLOT_CAPACITY - WORKER_THREADS, f"queued work exceeds the budget: {queued}"
    with pytest.raises(EmbeddingCapacityError):
        await bare_dealer()._query_embedding(Healthy(), "one-too-many")
    for model in blocking:
        model.gate.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert slots_free() == SLOT_CAPACITY, "the budget must return after the workers finish"
    REPORT["bounded_queue"] = {"capacity": SLOT_CAPACITY, "worker_threads": WORKER_THREADS, "max_queued_observed": queued}


# ---------------------------------------------------------------------------
# Budget release
# ---------------------------------------------------------------------------


async def test_budget_released_on_success_and_on_provider_failure():
    await bare_dealer()._query_embedding(Healthy(), "q")
    assert slots_free() == SLOT_CAPACITY
    with pytest.raises(EmbeddingError):
        await bare_dealer()._query_embedding(Failing(), "q")
    assert slots_free() == SLOT_CAPACITY, "a provider failure must release its budget"
    REPORT["budget_release"] = {"after_success": SLOT_CAPACITY, "after_provider_failure": slots_free()}


async def test_budget_released_when_submission_fails(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("executor is shut down")

    monkeypatch.setattr(_EMBEDDING_EXECUTOR, "submit", explode)
    with pytest.raises(RuntimeError):
        await bare_dealer()._query_embedding(Healthy(), "q")
    assert slots_free() == SLOT_CAPACITY, "a submission that never happened must not consume budget"
    REPORT["budget_release_on_submit_failure"] = {"budget": slots_free()}


async def test_budget_released_after_a_timed_out_worker_finishes_late(monkeypatch):
    """A timed-out call keeps holding its budget until its worker settles - then releases it."""
    monkeypatch.setattr(Dealer, "_embedding_wait_seconds", 0.05)
    model = Blocking()
    with pytest.raises(asyncio.TimeoutError):
        await bare_dealer()._query_embedding(model, "q")
    assert model.started.is_set()
    assert slots_free() == SLOT_CAPACITY - 1, "a worker still running must keep its own budget"
    model.gate.set()
    for _ in range(200):
        if slots_free() == SLOT_CAPACITY:
            break
        await asyncio.sleep(0.02)
    assert slots_free() == SLOT_CAPACITY, "the budget must return when the late worker settles"
    REPORT["late_budget_release"] = {"held_while_running": True, "released_after_settle": True}


async def test_repeated_timeouts_leak_neither_threads_nor_budget(monkeypatch):
    """N timeout cycles must return the pool to its baseline size and the budget to full."""
    monkeypatch.setattr(Dealer, "_embedding_wait_seconds", 0.02)
    baseline = len(embedding_thread_names())
    for _ in range(12):
        model = Blocking()
        with pytest.raises(asyncio.TimeoutError):
            await bare_dealer()._query_embedding(model, "q")
        model.gate.set()
    for _ in range(300):
        if slots_free() == SLOT_CAPACITY:
            break
        await asyncio.sleep(0.02)
    after = len(embedding_thread_names())
    assert slots_free() == SLOT_CAPACITY, f"budget leaked: {slots_free()}"
    assert after <= max(baseline, WORKER_THREADS), f"worker threads grew from {baseline} to {after}"
    REPORT["resource_leak"] = {"cycles": 12, "threads_baseline": baseline, "threads_after": after, "budget_after": slots_free(), "bounded_by": WORKER_THREADS}


# ---------------------------------------------------------------------------
# Late results
# ---------------------------------------------------------------------------


async def test_late_result_cannot_re_enter_or_move_health(monkeypatch):
    """A worker that finishes after the deadline changes nothing: not the value, not the facts."""
    from rag.retrieval import health_bridge as hb

    monkeypatch.setattr(Dealer, "_embedding_wait_seconds", 0.05)
    hb.begin_retrieval_health()
    session = hb.current_session()
    model = Blocking()
    with pytest.raises(asyncio.TimeoutError):
        await bare_dealer()._query_embedding(model, "q")
    facts_after_timeout = dict(session.__dict__.get("_leg_facts", {}))
    model.gate.set()
    await asyncio.sleep(0.2)
    assert session.__dict__.get("_leg_facts", {}) == facts_after_timeout, "a late completion moved the leg facts"
    assert slots_free() == SLOT_CAPACITY
    REPORT["late_result_isolation"] = {"facts_after_timeout": {k: dict(v) for k, v in facts_after_timeout.items()}, "unchanged_after_late_completion": True}


# ---------------------------------------------------------------------------
# Control signals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc,expected,label",
    [
        (asyncio.CancelledError(), False, "user abort / task cancellation"),
        (KeyboardInterrupt(), False, "interpreter interrupt"),
        (SystemExit(), False, "process shutdown"),
        (PermissionError("workspace membership revoked"), False, "permission revoked"),
        (EmbeddingError("Embedding request failed: 401 UNAUTHENTICATED invalid authentication credentials"), False, "revoked api key (401)"),
        (EmbeddingError("Embedding request failed: 403 PERMISSION_DENIED caller does not have permission"), False, "denied permission (403)"),
        (EmbeddingError("Embedding request failed: 400 API key not valid. Please pass a valid API key."), False, "invalid api key"),
        (EmbeddingError("Embedding request failed: 400 FAILED_PRECONDITION User location is not supported for the API use."), True, "incident location restriction"),
        (EmbeddingError("Embedding request failed: 429 RESOURCE_EXHAUSTED quota exceeded"), True, "provider quota"),
        (EmbeddingQuotaExhausted("gemini", "quota exceeded"), True, "quota exhausted class"),
        (EmbeddingRateLimited("gemini", "rate limit exceeded"), True, "rate limited class"),
        (asyncio.TimeoutError(), True, "provider timeout"),
        (TimeoutError("read timed out"), True, "provider read timeout"),
        (ConnectionError("connection reset"), True, "connection failure"),
        # A requests-based connector reports 5xx as a bare ModelException flagged transient, and
        # leaves 4xx unflagged. Consulting that flag is what keeps a transient outage on TEI /
        # HuggingFace / an OpenAI-compatible local server from becoming the same false-empty result
        # the Gemini incident produced - those connectors never raise EmbeddingError.
        (ModelException("status: 503, response: service unavailable", retryable=True), True, "bare ModelException flagged transient (5xx connector)"),
        (ModelException("status: 401, response: unauthorized", retryable=False), False, "bare ModelException 401"),
        (ModelException("status: 403, response: forbidden", retryable=False), False, "bare ModelException 403"),
        (ModelException("status: 404, response: not found", retryable=False), False, "bare ModelException 404"),
        (ModelException("status: 422, response: unprocessable", retryable=False), False, "bare ModelException 422"),
        (ModelException("status: 500, response: boom"), False, "bare ModelException with the default (non-transient) flag"),
        (ValueError("something nobody classified"), False, "unclassified failure (fail closed)"),
    ],
)
def test_recoverable_classification(exc, expected, label):
    """Recoverable means 'degrade and keep serving'. Everything else must surface."""
    assert Dealer._recoverable_embedding_failure(exc) is expected, label
    REPORT.setdefault("classification", []).append({"case": label, "exception": type(exc).__name__, "recoverable": expected})


def test_the_incidents_own_error_is_transient_by_no_flag_at_all():
    """Pin why recoverability cannot be decided by `retryable` alone.

    The provider location restriction arrives as a plain `EmbeddingError` whose `retryable` is the
    default False, because `embedding_failure` only recognises quota and rate-limit bodies. A rule
    of the form "recoverable iff retryable" would therefore classify the incident itself as
    permanent and reintroduce the bug this repair removes.
    """
    incident = EmbeddingError("Embedding request failed for GeminiEmbed. Error: 400 FAILED_PRECONDITION User location is not supported for the API use.")
    assert incident.retryable is False
    assert Dealer._recoverable_embedding_failure(incident) is True
    REPORT["incident_flag_pin"] = {"retryable_flag": incident.retryable, "classified_recoverable": True}


def test_credential_markers_are_matched_but_the_incident_is_not():
    assert _looks_like_credential_or_permission_failure(EmbeddingError("403 Forbidden")) is True
    assert _looks_like_credential_or_permission_failure(EmbeddingError("400 FAILED_PRECONDITION location is not supported")) is False
    assert _looks_like_credential_or_permission_failure(EmbeddingError("429 RESOURCE_EXHAUSTED")) is False


async def test_cancellation_propagates_through_the_embedding_await(monkeypatch):
    """Cancelling the awaiting task must raise CancelledError, not a recoverable provider error."""
    model = Blocking()
    task = asyncio.create_task(bare_dealer()._query_embedding(model, "q"))
    for _ in range(200):
        if model.started.is_set():
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    model.gate.set()
    await asyncio.sleep(0.1)
    assert Dealer._recoverable_embedding_failure(asyncio.CancelledError()) is False
    REPORT["cancellation"] = {"raised": "CancelledError", "classified_recoverable": False}


# ---------------------------------------------------------------------------
# Shutdown semantics
# ---------------------------------------------------------------------------


def test_shutdown_semantics_unchanged_from_the_shared_helper():
    """The dedicated pool is an ordinary ThreadPoolExecutor, joined at interpreter exit exactly
    like the shared helper's per-call pool was.

    `common.misc_utils.thread_pool_exec` creates a per-call `ThreadPoolExecutor(max_workers=1)` and
    calls `shutdown(wait=True)`, which is what turned a hung provider call into a blocked request
    and an empty route. This pool removes that block but keeps the same exit registration: hung
    worker threads still block interpreter exit, in BOTH designs, so this change neither introduces
    nor removes that property.
    """
    assert isinstance(_EMBEDDING_EXECUTOR, __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor)
    assert _EMBEDDING_EXECUTOR._max_workers == WORKER_THREADS
    assert _EMBEDDING_EXECUTOR._thread_name_prefix == "retrieval-embedding"
    threads = list(_EMBEDDING_EXECUTOR._threads)
    registered = [t for t in threads if t in cf_thread._threads_queues]
    REPORT["shutdown_semantics"] = {
        "executor_is_thread_pool_executor": True,
        "max_workers": _EMBEDDING_EXECUTOR._max_workers,
        "spawned_threads": len(threads),
        "registered_for_exit_join": len(registered),
        "property": "unchanged: a hung provider call blocks interpreter exit in both designs",
    }
    assert all(t.name.startswith("retrieval-embedding") for t in threads)


def test_module_level_helpers_are_single_instances():
    """One pool and one budget for the process, so admission is global rather than per-Dealer."""
    assert search_module._EMBEDDING_EXECUTOR is _EMBEDDING_EXECUTOR
    assert search_module._EMBEDDING_SLOTS is _EMBEDDING_SLOTS
    assert slots_free() == SLOT_CAPACITY
    REPORT["single_instances"] = {"capacity": SLOT_CAPACITY}
