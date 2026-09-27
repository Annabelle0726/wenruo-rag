"""Semantic-diff suite for the P0-B leg-attribution repair.

Proves, per changed file, that the change is confined to what was authorised:

  pipeline.py       -> original approved gate re-run against the deployed baseline (reporter-only)
  multi_route.py    -> original approved gate re-run against the deployed baseline (reporter-only)
  search.py         -> NEW FILE: reporter-only instrumentation at the two evidence-leg boundaries.
                       Proven by AST normalisation: after removing reporter statements and unwrapping
                       the single documented report-then-re-raise handler, every pre-existing function
                       is byte-identical to the deployed baseline, and every signature is unchanged.
  health_bridge.py  -> authorised attribution change. The health CONTRACT (health.py) and the producer
                       API (health_producers.py) must be byte-identical to the approved candidate, so
                       the contract cannot have been weakened to reach `full`.

Host-side, read-only. Writes deploy/p0_gates/semantic_diff_suite_result.json.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
GATES = ROOT / "deploy" / "p0_gates"
BASE = ROOT / "deploy" / "p0_baseline"
BUILD = ROOT / "deploy" / "p0_build"

REPORTER_CALLS = {
    "_report",
    "attach_retrieval_health",
    "begin_retrieval_health",
    "mark_empty_window",
    "mark_no_question",
    "report_route_failure",
    "report_route_success",
}
NEW_SEARCH_HELPERS = {"_health_bridge", "health_producer_error", "_report"}
#: Benign builtins used by the reporter helper itself (attribute lookup / message formatting only).
BENIGN_HELPER_BUILTINS = {"getattr", "type"}
FORBIDDEN_POLICY_SYMBOLS = ("decide_answer_action", "required_notice", "AnswerAction", "refuse_insufficient", "refuse_failed")


def policy_symbols_outside_declaration(text: str) -> list:
    """Forbidden answer-policy symbols actually *used*, ignoring the blocklist that names them.

    `health_bridge.FORBIDDEN_POLICY_SYMBOLS` is the tuple the build gate checks against, so the names
    legitimately appear there. Everything else must be free of them.
    """
    tree = ast.parse(text)
    tree.body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "FORBIDDEN_POLICY_SYMBOLS" for t in node.targets)
        )
    ]
    dumped = ast.dump(tree)
    return [symbol for symbol in FORBIDDEN_POLICY_SYMBOLS if symbol in dumped]


def collapse_temporary(stmts: list) -> list:
    """`x = <expr>` immediately followed by `return x` -> `return <expr>`.

    This is the reviewed bind-then-return form the approved pipeline/multi_route candidate also uses:
    the temporary exists only so a reporter can run between the call and the return.
    """
    out = []
    index = 0
    while index < len(stmts):
        stmt = stmts[index]
        nxt = stmts[index + 1] if index + 1 < len(stmts) else None
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(nxt, ast.Return)
            and isinstance(nxt.value, ast.Name)
            and nxt.value.id == stmt.targets[0].id
        ):
            out.append(ast.Return(value=stmt.value))
            index += 2
            continue
        out.append(stmt)
        index += 1
    return out


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_original_gate():
    spec = importlib.util.spec_from_file_location("p0_option_a_gate", ROOT / "tools" / "scripts" / "p0_option_a_candidate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def functions_of(tree: ast.AST) -> dict:
    return {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def strip_reporters(stmts: list, reporter_names) -> list:
    """Remove reporter-only statements (recursively), keeping every other node exactly as parsed."""
    kept = []
    for stmt in stmts:
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name)
            and stmt.value.func.id in reporter_names
        ):
            continue
        for field, value in ast.iter_fields(stmt):
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                setattr(stmt, field, strip_reporters(value, reporter_names))
        kept.append(stmt)
    return kept


def body_dumps(node) -> list:
    return [ast.dump(stmt) for stmt in node.body]


def is_report_then_rereraise(node) -> bool:
    """A Try whose single handler reports and then bare-re-raises: instrumentation, not control flow."""
    if not isinstance(node, ast.Try) or len(node.handlers) != 1:
        return False
    body = node.handlers[0].body
    return (
        len(body) == 2
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Call)
        and getattr(body[0].value.func, "id", None) == "_report"
        and isinstance(body[1], ast.Raise)
        and body[1].exc is None
    )


def normalize_instrumented_body(stmts: list) -> list:
    """Undo the instrumentation: unwrap the report-then-re-raise try, drop reporters, collapse temporaries."""
    unwrapped = []
    for stmt in stmts:
        if is_report_then_rereraise(stmt):
            unwrapped.extend(stmt.body)
        else:
            unwrapped.append(stmt)
    return collapse_temporary(strip_reporters(unwrapped, REPORTER_CALLS))


def check_search(baseline_text: str, candidate_text: str) -> dict:
    base_tree, cand_tree = ast.parse(baseline_text), ast.parse(candidate_text)
    base_fns, cand_fns = functions_of(base_tree), functions_of(cand_tree)

    preexisting = sorted(set(base_fns) & set(cand_fns))
    removed = sorted(set(base_fns) - set(cand_fns))
    added = sorted(set(cand_fns) - set(base_fns))

    unchanged_bodies = {}
    for name in preexisting:
        if name == "get_vector":
            continue
        base_body = body_dumps(base_fns[name])
        cand_body = body_dumps(cand_fns[name])
        # candidate statements minus reporter statements must equal the baseline statements exactly
        stripped = [ast.dump(s) for s in strip_reporters(cand_fns[name].body, REPORTER_CALLS)]
        unchanged_bodies[name] = stripped == base_body

    # get_vector: the documented wrapper - body unchanged, one handler that reports then re-raises
    gv_base, gv_cand = base_fns["get_vector"], cand_fns["get_vector"]
    handler = next((node for node in ast.walk(gv_cand) if isinstance(node, ast.Try)), None)
    handler_shape_ok = handler is not None and is_report_then_rereraise(handler)
    normalized_body = [ast.dump(s) for s in normalize_instrumented_body(gv_cand.body)]
    base_gv = body_dumps(gv_base)
    inner_shape_ok = normalized_body == base_gv

    introduced_calls = set()
    for node in ast.walk(cand_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            introduced_calls.add(node.func.id)
    baseline_calls = set()
    for node in ast.walk(base_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            baseline_calls.add(node.func.id)
    new_calls = sorted(introduced_calls - baseline_calls)

    checks = {
        "no_preexisting_function_removed": removed == [],
        "only_allowlisted_helpers_added": set(added) <= NEW_SEARCH_HELPERS,
        "all_preexisting_signatures_unchanged": all(ast.dump(base_fns[n].args) == ast.dump(cand_fns[n].args) for n in preexisting),
        "all_other_preexisting_bodies_unchanged_after_stripping_reporters": all(unchanged_bodies.values()),
        "get_vector_body_unchanged_inside_the_try": inner_shape_ok,
        "single_new_handler_reports_then_reraises_identically": handler_shape_ok,
        "introduced_calls_are_reporting_only": set(new_calls) <= (REPORTER_CALLS | NEW_SEARCH_HELPERS | BENIGN_HELPER_BUILTINS),
        "no_answer_policy_symbols_introduced": policy_symbols_outside_declaration(candidate_text) == [],
    }
    return {
        "scope": "search.py (vs deployed baseline)",
        "checks": checks,
        "passed": all(checks.values()),
        "functions_removed": removed,
        "functions_added": added,
        "introduced_calls": new_calls,
        "bodies_unchanged": {k: v for k, v in unchanged_bodies.items() if not v},
    }


def check_health_bridge(candidate_text: str) -> dict:
    contract = BUILD / "health.py"
    producers = BUILD / "health_producers.py"
    checks = {
        # The contract and the producer API are the approved ones: `full` cannot have been reached by
        # weakening validate(), KNOWN_LEGS, NEUTRAL or the evidence rules.
        "contract_module_unchanged_this_round": sha256(contract) == "ff04f8f6f07a8f01e761473209394ceeb8b797701f9103392f34401ec1d4cee4",
        "producer_api_unchanged_this_round": sha256(producers) == "391d0ced5b8e4b9824436547b3a7fc36a2ba7d7235b396fdf1aa6a6dbb31c68b",
        "route_reporters_signatures_unchanged": all(
            ast.dump(functions_of(ast.parse(candidate_text))[name].args) == ast.dump(functions_of(ast.parse((BASE / "health_bridge.approved.py").read_text(encoding="utf-8")))[name].args)
            for name in ("report_route_success", "report_route_failure")
        ),
        "leg_fact_reporters_added": all(
            name in functions_of(ast.parse(candidate_text))
            for name in ("report_dense_executed", "report_dense_failed", "report_dense_not_triggered", "report_lexical_executed", "report_lexical_failed", "report_lexical_not_triggered")
        ),
        "route_reporting_no_longer_erases_legs": "session.legs.pop(" not in candidate_text,
        "no_answer_policy_enforcement_symbols": policy_symbols_outside_declaration(candidate_text) == [],
    }
    return {"scope": "health_bridge.py (authorised attribution change)", "checks": checks, "passed": all(checks.values())}


def main() -> int:
    gate = load_original_gate()

    baseline_pipeline = (BASE / "pipeline.py").read_text(encoding="utf-8")
    baseline_multi_route = (ROOT / "rag" / "retrieval" / "multi_route.py").read_text(encoding="utf-8")
    baseline_search = (ROOT / "rag" / "nlp" / "search.py").read_text(encoding="utf-8")

    cand_pipeline = (BUILD / "pipeline.py").read_text(encoding="utf-8")
    cand_multi_route = (BUILD / "multi_route.py").read_text(encoding="utf-8")
    cand_search = (BUILD / "search.py").read_text(encoding="utf-8")

    rerun = [
        gate.semantic_gate(baseline_pipeline, cand_pipeline, "pipeline.py (vs deployed baseline)"),
        gate.semantic_gate(baseline_multi_route, cand_multi_route, "multi_route.py (vs deployed baseline)"),
    ]
    search_report = check_search(baseline_search, cand_search)
    bridge_report = check_health_bridge((BUILD / "health_bridge.py").read_text(encoding="utf-8"))

    payload = {
        "gate": "P0-B leg-attribution repair — semantic-diff suite",
        "approved_reporter_only_gate_rerun": rerun,
        "search_layer_report": search_report,
        "health_bridge_report": bridge_report,
        "baselines": {
            "pipeline.py": sha256(BASE / "pipeline.py"),
            "multi_route.py": sha256(ROOT / "rag" / "retrieval" / "multi_route.py"),
            "search.py": sha256(ROOT / "rag" / "nlp" / "search.py"),
        },
        "candidates": {name: sha256(BUILD / name) for name in ("pipeline.py", "multi_route.py", "search.py", "health.py", "health_producers.py", "health_bridge.py")},
        "verdict": "PASS" if all(g["passed"] for g in rerun) and search_report["passed"] and bridge_report["passed"] else "FAIL",
    }
    (GATES / "semantic_diff_suite_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for report in [*rerun, search_report, bridge_report]:
        print(f"[{report['scope']}] passed={report['passed']}")
        for name, value in report["checks"].items():
            print(f"    {'PASS' if value else 'FAIL'}  {name}")
    print("VERDICT:", payload["verdict"])
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
