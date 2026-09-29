"""Harness diagnostic for the failing healthy-path ES-trace differential.

`test_degradation.py::test_healthy_semantic_differential` asserts that the frozen production Dealer
and the candidate Dealer issue an identical ES query body on the healthy path. Pytest truncates the
assertion diff, so this script re-runs the two arms of that test and prints a *structural* diff of the
captured `_es_search_once` calls: only the differing paths, with the baseline and candidate values.

It changes no product code, does not weaken the gate's assertions and does not substitute for them.
"""

import asyncio
import copy
import importlib.util
import inspect
import sys

sys.path.insert(0, "/ragflow")

_spec = importlib.util.spec_from_file_location("gate", "/tmp/test_degradation.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def short(value, limit=200):
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def walk(a, b, path="trace", out=None):
    if out is None:
        out = []
    if type(a) is not type(b):
        out.append(f"{path}: TYPE {type(a).__name__} != {type(b).__name__}")
    elif isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: ONLY_IN_CANDIDATE={short(b[key])}")
            elif key not in b:
                out.append(f"{path}.{key}: ONLY_IN_BASELINE={short(a[key])}")
            else:
                walk(a[key], b[key], f"{path}.{key}", out)
    elif isinstance(a, (list, tuple)):
        if len(a) != len(b):
            out.append(f"{path}: LENGTH {len(a)} != {len(b)}")
        for index, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{index}]", out)
    elif a != b:
        out.append(f"{path}: BASELINE={short(a)} CANDIDATE={short(b)}")
    return out


def make_dealer(store, dealer_class=None):
    """Signature-adaptive: the gate helper's exact parameter list is not this script's business."""
    parameters = list(inspect.signature(gate.make_dealer).parameters)
    if dealer_class is not None and len(parameters) >= 2:
        return gate.make_dealer(store, dealer_class)
    return gate.make_dealer(store)


async def main():
    # The session fixture yields, so the unwrapped function returns a generator.
    store = next(gate.store.__wrapped__())
    baseline_spec = importlib.util.spec_from_file_location("frozen_production_search", "/tmp/baseline_search.py")
    baseline = importlib.util.module_from_spec(baseline_spec)
    sys.modules[baseline_spec.name] = baseline
    baseline_spec.loader.exec_module(baseline)

    original = store._es_search_once
    traces = []

    def capture(*a, **kw):
        traces.append(copy.deepcopy([a, kw]))
        return original(*a, **kw)

    store._es_search_once = capture
    gate.hb.begin_retrieval_health()
    before = await gate.retrieve(make_dealer(store, baseline.Dealer), gate.Healthy(), weight=0.5)
    old_trace = copy.deepcopy(traces)
    traces.clear()
    gate.hb.begin_retrieval_health()
    after = await gate.retrieve(make_dealer(store), gate.Healthy(), weight=0.5)

    print("TRACE_CALLS baseline/candidate:", len(old_trace), len(traces), flush=True)
    print("RETRIEVED_RESULTS_EQUAL:", before == after, flush=True)
    total = 0
    for index, (x, y) in enumerate(zip(old_trace, traces)):
        differences = walk(x, y, f"trace[{index}]")
        total += len(differences)
        print(f"DIFF_COUNT trace[{index}] = {len(differences)}", flush=True)
        for line in differences[:40]:
            print("   ", line, flush=True)
    print("DIFF_TOTAL:", total, flush=True)
    print("PROVENANCE_FIELD_IN_BASELINE_QUERY:", "content_prefix_kind_kwd" in repr(old_trace), flush=True)
    print("PROVENANCE_FIELD_IN_CANDIDATE_QUERY:", "content_prefix_kind_kwd" in repr(traces), flush=True)
    print("BASELINE_PROVENANCE_IN_SOURCE:", "content_prefix_kind_kwd" in getattr(baseline, "SEARCH_FIELD_NAMES", []) or "n/a", flush=True)


asyncio.run(main())
