"""GENERATOR_ANCHOR_GATE — a stale transformation anchor must fail the build, never no-op.

The P0-B incident started here. `build_multi_route_candidate` injected the reporter import with a bare
`str.replace()` anchored on `from rag.retrieval.rerank import`, which does not exist in the file. The
call returned the source unchanged, the build reported success, and the deployed candidate called two
symbols it never bound. This gate turns that accident into a permanent regression case.

Checks:
  1. every transformation anchor declares an expected match count;
  2. 0 matches            -> hard FAIL;
  3. more than expected   -> hard FAIL;
  4. exactly expected     -> succeeds;
  5. post-transformation  -> the expected symbol/import/call really exists;
  6. the stale `rerank` anchor now HARD-FAILS instead of silently succeeding;
  7. the builder functions contain no bare `str.replace(` call at all;
  8. the generator's output is byte-identical to the approved build inputs.

Host-side, read-only. Exit 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "tools" / "scripts" / "p0_option_a_candidate.py"
STALE_ANCHOR = "from rag.retrieval.rerank import"
BUILD = ROOT / "deploy" / "p0_build"


def load_generator():
    spec = importlib.util.spec_from_file_location("p0_option_a_candidate_under_test", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def expect_hard_failure(callable_, label: str = "probe") -> dict:
    """A stale/ambiguous anchor must raise SystemExit, not return the source unchanged."""
    try:
        result = callable_()
    except SystemExit as exc:
        return {"label": label, "raised": "SystemExit", "message": str(exc)[:200], "hard_failed": True}
    return {"label": label, "raised": None, "returned_unchanged": result is not None, "hard_failed": False}


def bare_replace_calls(source: str) -> list:
    """Any `.replace(` call inside the builder functions is a silent-no-op risk."""
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("build_"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "replace":
                    offenders.append(f"{node.name}:{sub.lineno}")
    return offenders


def main() -> int:
    gen = load_generator()
    gen_source = GENERATOR.read_text(encoding="utf-8")
    baseline_multi_route = (ROOT / "rag" / "retrieval" / "multi_route.py").read_text(encoding="utf-8")

    out: dict = {"gate": "GENERATOR_ANCHOR_GATE", "generator": str(GENERATOR.relative_to(ROOT))}

    # 1-4. declared match counts behave correctly
    anchor = "from typing import Any, Sequence\n"
    out["exact_one_match"] = {
        "succeeded": gen.replace_exact(baseline_multi_route, anchor, anchor, 1, "gate-probe-exact") == baseline_multi_route,
    }
    out["zero_matches"] = expect_hard_failure(lambda: gen.replace_exact(baseline_multi_route, "THIS ANCHOR DOES NOT EXIST\n", "", 1, "gate-probe-zero"))
    out["more_than_expected"] = expect_hard_failure(lambda: gen.replace_exact(baseline_multi_route, "import logging\n", "", 0, "gate-probe-over"))

    # 6. the historical stale anchor: this is the exact call that silently no-opped
    out["stale_rerank_anchor"] = expect_hard_failure(lambda: gen.replace_once(baseline_multi_route, STALE_ANCHOR, "import nothing\n", "stale-rerank-anchor"))
    out["stale_anchor_present_in_baseline_count"] = baseline_multi_route.count(STALE_ANCHOR)
    out["incident_mechanism_demonstrated"] = baseline_multi_route.replace(STALE_ANCHOR, "X", 1) == baseline_multi_route

    # 7. no bare .replace( anywhere in the builders
    out["bare_replace_calls_in_builders"] = bare_replace_calls(gen_source)

    # 5 + 8. the generator still produces the approved, fully bound candidate
    cand_multi_route = gen.build_multi_route_candidate(baseline_multi_route)
    cand_pipeline = gen.build_pipeline_candidate((ROOT / "deploy" / "p0_baseline" / "pipeline.py").read_text(encoding="utf-8"))
    out["symbol_binding_proofs"] = [
        gen.verify_candidate_symbols(cand_pipeline, "pipeline.py"),
        gen.verify_candidate_symbols(cand_multi_route, "multi_route.py"),
    ]
    for name, text in (("multi_route.py", cand_multi_route), ("pipeline.py", cand_pipeline)):
        built = BUILD / name
        out[f"output_matches_build_input_{name}"] = (
            built.exists() and hashlib.sha256(text.encode("utf-8")).hexdigest() == hashlib.sha256(built.read_bytes()).hexdigest()
        )

    checks = {
        "exactly_one_match_succeeds": out["exact_one_match"]["succeeded"],
        "zero_matches_hard_fails": out["zero_matches"]["hard_failed"],
        "more_than_expected_hard_fails": out["more_than_expected"]["hard_failed"],
        "stale_anchor_hard_fails_now": out["stale_rerank_anchor"]["hard_failed"],
        "incident_mechanism_demonstrated": out["incident_mechanism_demonstrated"],
        "no_bare_replace_in_builders": out["bare_replace_calls_in_builders"] == [],
        "all_reporter_symbols_bound": all(p["passed"] for p in out["symbol_binding_proofs"]),
        "generator_output_matches_approved_build_inputs": out["output_matches_build_input_multi_route.py"] and out["output_matches_build_input_pipeline.py"],
    }
    out["checks"] = checks
    out["passed"] = all(checks.values())
    out["verdict"] = "PASS" if out["passed"] else "FAIL"

    (ROOT / "deploy" / "p0_gates" / "generator_anchor_gate_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
