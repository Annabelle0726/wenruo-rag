"""Semantic-diff re-run + delta proof for the P0-B wiring repair.

Two independent questions, both answered from the ASTs:

1. RE-RUN of the original approved gate (`tools/scripts/p0_option_a_candidate.py::semantic_gate`)
   with the DEPLOYED BASELINE as the base and the FIXED candidate as the candidate. The repair must
   still satisfy every reporter-only property the original gate enforced.

2. DELTA vs the PREVIOUSLY APPROVED candidate (the one that failed live acceptance). This is the
   proof the operator asked for explicitly: apart from the reporter symbol binding/import, the
   previously approved candidate semantics are unchanged -- i.e. no function body, no `_guard`
   control flow, no exception boundary, no RouteResult, no retrieval parameter and no return value
   differs by so much as a node.

Host-side, read-only. Writes deploy/p0_gates/semantic_diff_rerun_result.json.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
GATES = ROOT / "deploy" / "p0_gates"
BASE = ROOT / "deploy" / "p0_baseline"
BUILD = ROOT / "deploy" / "p0_build"

BASELINE_PIPELINE = BASE / "pipeline.py"
BASELINE_MULTI_ROUTE = ROOT / "rag" / "retrieval" / "multi_route.py"
OLD_CANDIDATE_MULTI_ROUTE = BASE / "multi_route.p0-candidate.py"
NEW_CANDIDATE_PIPELINE = BUILD / "pipeline.py"
NEW_CANDIDATE_MULTI_ROUTE = BUILD / "multi_route.py"

REPORTERS = {"report_route_success", "report_route_failure"}
BRIDGE_MODULE = "rag.retrieval.health_bridge"
FORBIDDEN_POLICY_SYMBOLS = ("decide_answer_action", "required_notice", "AnswerAction", "refuse_insufficient", "refuse_failed")


def load_original_gate():
    path = ROOT / "tools" / "scripts" / "p0_option_a_candidate.py"
    spec = importlib.util.spec_from_file_location("p0_option_a_candidate_gate", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def function_dumps(tree: ast.AST) -> dict:
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.dump(node)
    return out


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def delta_gate(old_text: str, new_text: str) -> dict:
    """Prove the only difference between the approved candidate and the repaired one is the import."""
    old_tree, new_tree = ast.parse(old_text), ast.parse(new_text)
    old_fns, new_fns = function_dumps(old_tree), function_dumps(new_tree)

    old_module = [ast.dump(n) for n in old_tree.body]
    new_module = [ast.dump(n) for n in new_tree.body]
    removed = [n for n in old_module if n not in new_module]
    added = [n for n in new_module if n not in old_module]

    added_imports = []
    for node in new_tree.body:
        if isinstance(node, ast.ImportFrom) and ast.dump(node) in added:
            added_imports.append(
                {
                    "module": node.module,
                    "names": sorted(alias.name for alias in node.names),
                    "level": node.level,
                }
            )

    def reporter_calls(tree):
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in REPORTERS:
                found.append(node.func.id)
        return sorted(found)

    checks = {
        "function_set_unchanged": sorted(old_fns) == sorted(new_fns),
        "every_function_body_byte_identical_in_ast": all(old_fns[name] == new_fns[name] for name in old_fns if name in new_fns),
        "no_module_level_node_removed": removed == [],
        "exactly_one_module_level_node_added": len(added) == 1,
        "added_node_is_the_reporter_import": len(added_imports) == 1 and added_imports[0]["module"] == BRIDGE_MODULE,
        "added_import_binds_exactly_the_two_reporters": len(added_imports) == 1 and set(added_imports[0]["names"]) == REPORTERS,
        "reporter_call_sites_identical": reporter_calls(old_tree) == reporter_calls(new_tree),
        "no_answer_policy_symbols_introduced": not any(s in new_text for s in FORBIDDEN_POLICY_SYMBOLS),
    }

    diff = list(
        difflib.unified_diff(
            old_text.splitlines(True),
            new_text.splitlines(True),
            "multi_route.py (previously approved candidate)",
            "multi_route.py (wiring-repaired candidate)",
            n=1,
        )
    )
    added_lines = [ln for ln in diff if ln.startswith("+") and not ln.startswith("+++")]
    removed_lines = [ln for ln in diff if ln.startswith("-") and not ln.startswith("---")]
    checks["textually_added_lines_are_only_the_import"] = len(added_lines) <= 2 and all(
        (ln[1:].strip().startswith("from rag.retrieval.health_bridge import") or ln[1:].strip() == "") for ln in added_lines
    )
    checks["no_lines_removed_textually"] = removed_lines == []

    return {
        "scope": "delta_vs_previously_approved_candidate",
        "checks": checks,
        "passed": all(checks.values()),
        "added_imports": added_imports,
        "module_level_nodes_added": len(added),
        "module_level_nodes_removed": len(removed),
        "diff": "".join(diff),
    }


def main() -> int:
    gate = load_original_gate()

    baseline_pipeline = BASELINE_PIPELINE.read_text(encoding="utf-8")
    baseline_multi_route = BASELINE_MULTI_ROUTE.read_text(encoding="utf-8")
    old_candidate_multi_route = OLD_CANDIDATE_MULTI_ROUTE.read_text(encoding="utf-8")
    new_pipeline = NEW_CANDIDATE_PIPELINE.read_text(encoding="utf-8")
    new_multi_route = NEW_CANDIDATE_MULTI_ROUTE.read_text(encoding="utf-8")

    rerun = [
        gate.semantic_gate(baseline_pipeline, new_pipeline, "pipeline.py (vs deployed baseline)"),
        gate.semantic_gate(baseline_multi_route, new_multi_route, "multi_route.py (vs deployed baseline)"),
    ]
    delta = delta_gate(old_candidate_multi_route, new_multi_route)

    payload = {
        "gate": "P0-B wiring repair — semantic-diff re-run + delta proof",
        "baseline": {
            "pipeline.py": {"lines": len(baseline_pipeline.splitlines()), "sha256": sha256_text(baseline_pipeline)},
            "multi_route.py": {"lines": len(baseline_multi_route.splitlines()), "sha256": sha256_text(baseline_multi_route)},
        },
        "previously_approved_candidate": {
            "multi_route.py": {"lines": len(old_candidate_multi_route.splitlines()), "sha256": sha256_text(old_candidate_multi_route)},
        },
        "repaired_candidate": {
            "pipeline.py": {"lines": len(new_pipeline.splitlines()), "sha256": sha256_text(new_pipeline)},
            "multi_route.py": {"lines": len(new_multi_route.splitlines()), "sha256": sha256_text(new_multi_route)},
        },
        "semantic_diff_gate_rerun": rerun,
        "delta_proof": delta,
        "verdict": "PASS" if all(g["passed"] for g in rerun) and delta["passed"] else "FAIL",
    }

    out = GATES / "semantic_diff_rerun_result.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in payload.items() if k != "delta_proof"}, ensure_ascii=False, indent=2))
    print("--- DELTA CHECK TABLE ---")
    for name, value in delta["checks"].items():
        print(f"  {'PASS' if value else 'FAIL'}  {name}")
    print("--- DELTA DIFF ---")
    print(delta["diff"] or "(no textual difference)")
    print("VERDICT:", payload["verdict"])
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
