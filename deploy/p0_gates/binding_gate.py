"""RUNTIME_SYMBOL_BINDING_GATE — executes inside the candidate runtime environment.

Prevents the P0-B incident class: a module that *calls* reporter symbols it never *binds*.
The previous candidate passed the AST semantic diff and the frozen fault-injection suite while being
unable to run at all, because nothing ever imported the deployed module and executed the wiring.

This gate does not compare call sites. It imports the candidate module in the candidate runtime
environment and then actually executes both reporter paths.

Hard rules:
  * embedding/store are TEST DOUBLES -> zero external Gemini quota;
  * the executed `multi_route.py` and reporter wiring come from the module under test
    (the actual image file, or the actual candidate file), never from a simulation.

Exit code 0 = PASS, 1 = FAIL. Emits JSON between BINDING_GATE_JSON_BEGIN / _END.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import sys
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, "/ragflow")

REPORTERS = ("report_route_success", "report_route_failure")


class QuotaExhausted(Exception):
    """Stands in for the remote embedding API's 429 RESOURCE_EXHAUSTED."""


class HealthyRetriever:
    """Test double: a route that returns a usable pool."""

    def __init__(self) -> None:
        self.calls = 0

    async def retrieval(self, *args, **kwargs):
        self.calls += 1
        return {
            "chunks": [{"chunk_id": "c1", "content": "probe", "docnm_kwd": "d1"}],
            "doc_aggs": [{"doc_name": "d1"}],
            "total": 1,
        }


class FailingRetriever:
    """Test double: a route whose embedding boundary raises."""

    def __init__(self) -> None:
        self.calls = 0

    async def retrieval(self, *args, **kwargs):
        self.calls += 1
        raise QuotaExhausted("429 RESOURCE_EXHAUSTED: quota exceeded")


def load_module(args):
    if args.import_name:
        return importlib.import_module(args.import_name), args.import_name
    spec = importlib.util.spec_from_file_location(args.module_name, args.file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, args.file


def leg_snapshot(session) -> dict:
    if session is None:
        return {}
    return {name: getattr(leg.status, "value", str(leg.status)) for name, leg in session.legs.items()}


def route_counters(session) -> dict:
    """Route-level bookkeeping produced by `report_route_success` / `report_route_failure`."""
    if session is None:
        return {}
    return dict(session.__dict__.get("_route_counters") or {})


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file")
    parser.add_argument("--import-name")
    parser.add_argument("--module-name", default="candidate_multi_route_under_test")
    parser.add_argument("--label", default="unlabelled")
    args = parser.parse_args()

    out: dict = {"gate": "RUNTIME_SYMBOL_BINDING_GATE", "label": args.label, "loaded_from": args.file or args.import_name}

    # ---- 1. import in the candidate runtime environment -------------------------------
    module = None
    import_error = None
    try:
        module, loaded = load_module(args)
        out["loaded_from"] = loaded
        out["module_file"] = getattr(module, "__file__", None)
    except BaseException as exc:  # noqa: BLE001 - any import failure is a gate failure
        import_error = {"type": type(exc).__name__, "message": str(exc)[:300]}
    out["import_error"] = import_error
    out["import_succeeded"] = import_error is None

    if module is None:
        out["checks"] = {"import_succeeded": False}
        out["passed"] = False
        out["verdict"] = "FAIL"
        print("BINDING_GATE_JSON_BEGIN")
        print(json.dumps(out, ensure_ascii=False))
        print("BINDING_GATE_JSON_END")
        return 1

    from rag.retrieval import health_bridge

    # ---- 2. symbol binding -----------------------------------------------------------
    binding = {}
    for name in REPORTERS:
        obj = getattr(module, name, None)
        approved = getattr(health_bridge, name, None)
        binding[name] = {
            "bound": obj is not None,
            "callable": callable(obj),
            "bound_to_approved_reporter": obj is not None and obj is approved,
            "object": getattr(obj, "__name__", None),
        }
    out["binding"] = binding

    # ---- 3. execute the reporter paths for real --------------------------------------
    async def exercise(retriever, queries, session_holder):
        health_bridge.begin_retrieval_health()
        session_holder["session"] = health_bridge.current_session()
        escaped = None
        result = {}
        try:
            result = await module.multi_route_retrieve(
                retriever=retriever,
                queries=queries,
                embd_mdl=None,
                tenant_ids=["tenant-probe"],
                kb_ids=["kb-probe"],
            )
        except BaseException as exc:  # noqa: BLE001
            escaped = {
                "type": type(exc).__name__,
                "message": str(exc)[:200],
                "raised_from": next((ln.strip() for ln in traceback.format_exc().splitlines() if "multi_route.py" in ln), None),
            }
        return escaped, result

    fail_holder: dict = {}
    failure_escaped, failure_result = await exercise(FailingRetriever(), ["q-fail"], fail_holder)
    out["failure_path"] = {
        "exception_escaped": failure_escaped,
        "session_legs": leg_snapshot(fail_holder.get("session")),
        "route_counters": route_counters(fail_holder.get("session")),
        "result_keys": sorted(str(k) for k in failure_result.keys()) if isinstance(failure_result, dict) else [],
    }

    ok_holder: dict = {}
    success_retriever = HealthyRetriever()
    success_escaped, success_result = await exercise(success_retriever, ["q-ok-a", "q-ok-b"], ok_holder)
    out["success_path"] = {
        "exception_escaped": success_escaped,
        "session_legs": leg_snapshot(ok_holder.get("session")),
        "route_counters": route_counters(ok_holder.get("session")),
        "route_calls": success_retriever.calls,
        "result_keys": sorted(str(k) for k in success_result.keys()) if isinstance(success_result, dict) else [],
        "merged_total": success_result.get("total") if isinstance(success_result, dict) else None,
    }

    # The route reporters no longer own leg attribution (one hybrid route covers BOTH evidence legs, so
    # the route layer must not invent either one). Their execution is therefore observed on the route
    # counters, and the failure path additionally leaves a leg fact by attributing the caught exception.
    success_counters = out["success_path"]["route_counters"]
    failure_counters = out["failure_path"]["route_counters"]
    failure_legs = out["failure_path"]["session_legs"]
    reporter_success_executed = success_counters.get("succeeded", 0) >= 1
    reporter_failure_executed = failure_counters.get("failed", 0) >= 1 or any(
        status in ("failed", "degraded") for status in failure_legs.values()
    )

    error_types = [err["type"] for err in (failure_escaped, success_escaped) if err]
    out["error_types_observed"] = error_types

    checks = {
        "import_succeeded": True,
        "report_route_success_bound": binding["report_route_success"]["bound"],
        "report_route_success_callable": binding["report_route_success"]["callable"],
        "report_route_failure_bound": binding["report_route_failure"]["bound"],
        "report_route_failure_callable": binding["report_route_failure"]["callable"],
        "reporters_bound_to_approved_implementation": all(binding[n]["bound_to_approved_reporter"] for n in REPORTERS),
        "reporter_success_path_executed": reporter_success_executed,
        "reporter_failure_path_executed": reporter_failure_executed,
        "failure_reporter_did_not_escape_guard_handler": failure_escaped is None,
        "success_reporter_did_not_escape_guard_handler": success_escaped is None,
        "no_nameerror": "NameError" not in error_types,
        "no_importerror": "ImportError" not in error_types and "ModuleNotFoundError" not in error_types,
        "no_unresolved_reporter_symbol": not any(err["type"] == "NameError" and "report_route" in err.get("message", "") for err in (failure_escaped, success_escaped) if err),
    }
    out["checks"] = checks
    out["passed"] = all(checks.values())
    out["verdict"] = "PASS" if out["passed"] else "FAIL"

    print("BINDING_GATE_JSON_BEGIN")
    print(json.dumps(out, ensure_ascii=False))
    print("BINDING_GATE_JSON_END")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
