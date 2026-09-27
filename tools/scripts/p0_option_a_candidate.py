"""Option-A candidate builder and Semantic-Diff Gate.

Reads the extracted deployment baseline (`deploy/p0_baseline/pipeline.py`, 329 lines, sha256 recorded)
plus the in-tree `rag/retrieval/multi_route.py` (which matches the deployed file line for line), applies
the reporter-only instrumentation, writes the candidate files, emits a unified diff, and then runs an
automated semantic-diff gate over the ASTs to prove the change is observability-only.

Nothing here writes to the live modules under rag/ and nothing touches the container or any image.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "deploy" / "p0_baseline"
BASELINE_PIPELINE = BASE / "pipeline.py"
TREE_MULTI_ROUTE = ROOT / "rag" / "retrieval" / "multi_route.py"
CAND_PIPELINE = BASE / "pipeline.p0-candidate.py"
CAND_MULTI_ROUTE = BASE / "multi_route.p0-candidate.py"
PATCH = BASE / "p0_option_a.patch"
RESULT = BASE / "p0_option_a_semantic_diff_result.json"

IMPORT_BLOCK = """from rag.retrieval.health_bridge import (
    attach_retrieval_health,
    begin_retrieval_health,
    mark_empty_window,
    mark_no_question,
    report_route_failure,
    report_route_success,
)

"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"ANCHOR FAILURE [{label}]: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def build_pipeline_candidate(baseline: str) -> str:
    text = replace_once(baseline, "async def retrieve_multi_route(\n", IMPORT_BLOCK + "async def retrieve_multi_route(\n", "pipeline import")
    text = replace_once(
        text,
        '    question = " ".join(str(question or "").split())\n    if not question:\n        return empty_kbinfos()\n',
        '    question = " ".join(str(question or "").split())\n    begin_retrieval_health()\n    if not question:\n        mark_no_question()\n        return attach_retrieval_health(empty_kbinfos())\n',
        "pipeline empty question",
    )
    text = replace_once(
        text,
        '    merged = await _retrieve(routes, doc_ids)\n    if not merged.get("chunks"):\n        return empty_kbinfos()\n',
        '    merged = await _retrieve(routes, doc_ids)\n    if not merged.get("chunks"):\n        mark_empty_window()\n        return attach_retrieval_health(empty_kbinfos())\n',
        "pipeline empty window",
    )
    text = replace_once(
        text,
        '    return {"total": merged.get("total", len(chunks)), "chunks": chunks, "doc_aggs": merged.get("doc_aggs", [])}\n',
        '    return attach_retrieval_health({"total": merged.get("total", len(chunks)), "chunks": chunks, "doc_aggs": merged.get("doc_aggs", [])})\n',
        "pipeline final return",
    )
    return text


def build_multi_route_candidate(source: str) -> str:
    return replace_once(
        source,
        """    async def _guard(query: str) -> RouteResult:
        try:
            return await _retrieve_route(
""",
        """    async def _guard(query: str) -> RouteResult:
        try:
            result = await _retrieve_route(
""",
        "multi_route guard success binding",
    ).replace(
        """                allow_dense_fallback=allow_dense_fallback,
            )
        except Exception as exc:  # noqa: BLE001 - one dead route must not sink the others
            _LOG.warning("[Multi-route] route %r failed: %s", query[:80], exc)
            return RouteResult(query=query, failed=True)
""",
        """                allow_dense_fallback=allow_dense_fallback,
            )
            report_route_success()
            return result
        except Exception as exc:  # noqa: BLE001 - one dead route must not sink the others
            _LOG.warning("[Multi-route] route %r failed: %s", query[:80], exc)
            report_route_failure(exc)
            return RouteResult(query=query, failed=True)
""",
        1,
    ).replace(
        "from rag.retrieval.rerank import",
        "from rag.retrieval.health_bridge import report_route_failure, report_route_success\nfrom rag.retrieval.rerank import",
        1,
    )


REPORTER_CALLS = {"attach_retrieval_health", "begin_retrieval_health", "mark_empty_window", "mark_no_question", "report_route_failure", "report_route_success"}

#: Answer policy stays out of this deployment (see health_bridge.ANSWER_POLICY_ENFORCEMENT).
FORBIDDEN_POLICY_SYMBOLS = ("decide_answer_action", "required_notice", "AnswerAction", "refuse_insufficient", "refuse_failed")
PRESERVED_CALLS = ("_retrieve_route", "multi_route_retrieve", "rerank_chunks", "merge_route_hits", "core_document_followup", "RouteResult", "empty_kbinfos")


def functions(tree: ast.AST) -> dict:
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found[node.name] = node
    return found


def signature_dump(node) -> str:
    return ast.dump(node.args)


def module_headers(tree: ast.AST) -> list:
    """Module-level identity: functions compare by name and signature, everything else by full dump."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"{type(node).__name__}:{node.name}:{signature_dump(node)}")
        else:
            out.append(ast.dump(node))
    return out


def except_types(tree: ast.AST) -> list:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                out.append(ast.dump(handler.type) if handler.type else "BARE_EXCEPT")
    return sorted(out)


def calls_named(tree: ast.AST, names) -> list:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
            if name in names:
                out.append(f"{name}(" + ast.dump(ast.Tuple(elts=node.args)) + ")")
    return sorted(out)


def returns_in(tree: ast.AST, name: str) -> list:
    node = functions(tree).get(name)
    if node is None:
        return []
    return [ast.dump(sub.value) for sub in ast.walk(node) if isinstance(sub, ast.Return)]


def strip_wrapper(dumped: str) -> str:
    """Remove exactly one attach_retrieval_health(...) wrapper so payloads can be compared."""
    if dumped.startswith("Call(func=Name(id='attach_retrieval_health'") and dumped.endswith(")"):
        inner = dumped.split("args=[", 1)[-1]
        return inner.rsplit("], keywords=[]", 1)[0]
    return dumped


def semantic_gate(baseline: str, candidate: str, label: str) -> dict:
    base_tree, cand_tree = ast.parse(baseline), ast.parse(candidate)
    base_fns, cand_fns = functions(base_tree), functions(cand_tree)
    checks = {}

    checks["function_set_unchanged"] = sorted(base_fns) == sorted(cand_fns)
    checks["all_signatures_unchanged"] = all(signature_dump(base_fns[name]) == signature_dump(cand_fns[name]) for name in base_fns if name in cand_fns)
    checks["except_types_unchanged"] = except_types(base_tree) == except_types(cand_tree)
    checks["try_block_count_unchanged"] = sum(1 for n in ast.walk(base_tree) if isinstance(n, ast.Try)) == sum(1 for n in ast.walk(cand_tree) if isinstance(n, ast.Try))
    checks["preserved_call_sites_unchanged"] = calls_named(base_tree, PRESERVED_CALLS) == calls_named(cand_tree, PRESERVED_CALLS)
    checks["return_count_unchanged"] = all(len(returns_in(base_tree, name)) == len(returns_in(cand_tree, name)) for name in base_fns)
    changed_returns_ok = True
    bind_proofs = {}
    for name in base_fns:
        before, after = returns_in(base_tree, name), returns_in(cand_tree, name)
        for old, new in zip(before, after):
            if old == new or strip_wrapper(new) == old:
                continue
            # Declared rewrite: `return <expr>` -> `<tmp> = <expr>; report(); return <tmp>`.
            # Allowed only with proof: exactly one assignment of the temporary from the identical
            # expression, and the temporary is used nowhere else (so nothing can mutate it).
            assignment = None
            for node in ast.walk(cand_fns[name]):
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    if ast.dump(node.value) == old:
                        assignment = node.targets[0].id
            if assignment is None or f"Name(id='{assignment}'" not in new:
                changed_returns_ok = False
                continue
            uses = sum(1 for node in ast.walk(cand_fns[name]) if isinstance(node, ast.Name) and node.id == assignment)
            if uses != 2:
                changed_returns_ok = False
                continue
            bind_proofs[f"{name}:{assignment}"] = "assignment value identical to the baseline return; temporary used exactly twice (assignment + return)"
    checks["returns_only_wrapped_not_altered"] = changed_returns_ok

    new_calls = set()
    for node in ast.walk(cand_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            new_calls.add(node.func.id)
    baseline_calls = set()
    for node in ast.walk(base_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            baseline_calls.add(node.func.id)
    introduced = new_calls - baseline_calls
    checks["only_reporter_calls_introduced"] = introduced <= REPORTER_CALLS
    # Hard interception item: answer-policy enforcement must not exist in this deployment. A `partial`
    # evidence state may be observed and exposed, never turned into a refusal.
    checks["no_answer_policy_enforcement_symbols"] = not any(symbol in candidate for symbol in FORBIDDEN_POLICY_SYMBOLS)

    # Module-level comparison uses *headers* for functions (name + signature), because function
    # bodies legitimately contain the reporter calls; comparing whole dumps would report every
    # instrumented function as "removed and re-added".
    base_module = module_headers(base_tree)
    cand_module = module_headers(cand_tree)
    removed = [n for n in base_module if n not in cand_module]
    checks["no_module_level_statement_removed"] = removed == []
    added_module = [n for n in cand_module if n not in base_module]
    checks["module_level_additions_are_import_only"] = all(n.startswith("ImportFrom") or n.startswith("Import(") for n in added_module)
    position = [cand_module.index(n) for n in base_module if n in cand_module]
    checks["module_level_sequence_preserved"] = position == sorted(position)

    return {
        "scope": label,
        "checks": checks,
        "passed": all(checks.values()),
        "introduced_calls": sorted(introduced),
        "added_module_level_nodes": len(added_module),
        "bind_then_return_proofs": bind_proofs,
    }


def main() -> int:
    baseline_pipeline = BASELINE_PIPELINE.read_text(encoding="utf-8")
    baseline_multi_route = TREE_MULTI_ROUTE.read_text(encoding="utf-8")
    cand_pipeline = build_pipeline_candidate(baseline_pipeline)
    cand_multi_route = build_multi_route_candidate(baseline_multi_route)

    CAND_PIPELINE.write_text(cand_pipeline, encoding="utf-8", newline="\n")
    CAND_MULTI_ROUTE.write_text(cand_multi_route, encoding="utf-8", newline="\n")

    diff = list(difflib.unified_diff(baseline_pipeline.splitlines(True), cand_pipeline.splitlines(True), "rag/retrieval/pipeline.py (deployed baseline)", "rag/retrieval/pipeline.py (p0 candidate)", n=3))
    diff += list(difflib.unified_diff(baseline_multi_route.splitlines(True), cand_multi_route.splitlines(True), "rag/retrieval/multi_route.py (deployed baseline)", "rag/retrieval/multi_route.py (p0 candidate)", n=3))
    PATCH.write_text("".join(diff), encoding="utf-8", newline="\n")

    gates = [semantic_gate(baseline_pipeline, cand_pipeline, "pipeline.py"), semantic_gate(baseline_multi_route, cand_multi_route, "multi_route.py")]
    payload = {
        "gate": "P0 Option-A Semantic-Diff Gate",
        "baseline": {
            "pipeline.py": {"lines": len(baseline_pipeline.splitlines()), "sha256": hashlib.sha256(baseline_pipeline.encode("utf-8")).hexdigest()},
            "multi_route.py": {"lines": len(baseline_multi_route.splitlines()), "sha256": hashlib.sha256(baseline_multi_route.encode("utf-8")).hexdigest()},
        },
        "candidate": {
            "pipeline.py": {"lines": len(cand_pipeline.splitlines())},
            "multi_route.py": {"lines": len(cand_multi_route.splitlines())},
        },
        "diff_hunks": "".join(diff).count("\n@@"),
        "gates": gates,
        "verdict": "PASS" if all(gate["passed"] for gate in gates) else "FAIL",
    }
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
