"""Build the MINIMAL BACKPORT of Phase 1 onto the DEPLOYED (pre-planner) pipeline.py.

Reads the deployed pipeline.py, applies exactly the Phase-1 integration hunks, and writes the
result to a candidate path. Nothing in the deployed tree is touched: the patched file is a
standalone module used only to prove the backport is semantically clean and to exercise the real
production route assembly end to end.

    python tools/scripts/phase1_build_backport.py <deployed_pipeline.py> <out.py>
"""

from __future__ import annotations

import pathlib
import sys

# Hunk 1 - the import. Placed next to the other rag.retrieval imports.
IMPORT_ANCHOR = "from rag.retrieval.rerank import DEFAULT_FINAL_TOP_N, rerank_chunks, resolve_final_top_n\n"
IMPORT_ADDED = "from rag.retrieval.route_expansion import MAX_SUPPLEMENTAL_ROUTES, supplemental_routes\n"

# Hunk 2 - the route budget. Expressed with MAX_SUB_QUERIES, which the deployed pipeline ALREADY
# imports, so the backport pulls in no planner symbol (planner.py does not exist in the image).
BUDGET_ANCHOR = "MAX_CORE_DOCUMENT_ROUTES = 3\n"
BUDGET_ADDED = """
#: Total route allowance for one question on THIS pipeline: the decomposition cap plus room for the
#: deterministic supplemental cross product. Derived from a constant the deployed module already
#: imports, so the backport introduces no dependency on the planner.
ROUTE_BUDGET = MAX_SUB_QUERIES + MAX_SUPPLEMENTAL_ROUTES
"""

# Hunk 3 - the expansion itself, immediately after the deployed route assembly completes.
CALL_ANCHOR = """    targeted = clause_route(question)
    if targeted:
        routes.append(targeted)
"""
CALL_ADDED = """    targeted = clause_route(question)
    if targeted:
        routes.append(targeted)
    # Deterministic supplemental routes: a question that enumerates both an entity axis and a
    # fact-type axis gets their bounded cross product, so its per-fact-type coverage does not depend
    # on how granular the decomposition model happened to be in this session. Additive: every route
    # above is kept. See `rag.retrieval.route_expansion`.
    supplemental, expansion = supplemental_routes(
        question,
        existing_routes=routes,
        budget=max(0, ROUTE_BUDGET - len(routes)),
    )
    if supplemental:
        routes.extend(supplemental)
        sub_queries.extend(supplemental)
        _LOG.info(
            "[Multi-route] deterministic expansion=%s added %d route(s): %s",
            expansion.get("reason"),
            len(supplemental),
            supplemental,
        )
"""


def apply(source: str) -> tuple[str, list[str]]:
    applied: list[str] = []
    text = source

    if IMPORT_ANCHOR not in text:
        raise SystemExit("import anchor not found - deployed pipeline has changed")
    if IMPORT_ADDED not in text:
        text = text.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_ADDED, 1)
        applied.append("import")

    if BUDGET_ANCHOR not in text:
        raise SystemExit("budget anchor not found")
    if "ROUTE_BUDGET" not in text:
        text = text.replace(BUDGET_ANCHOR, BUDGET_ANCHOR + BUDGET_ADDED, 1)
        applied.append("ROUTE_BUDGET")

    if CALL_ANCHOR not in text:
        raise SystemExit("route-assembly anchor not found")
    if "supplemental_routes(" not in text:
        text = text.replace(CALL_ANCHOR, CALL_ADDED, 1)
        applied.append("expansion call")

    return text, applied


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = (pathlib.Path(p) for p in sys.argv[1:3])
    patched, applied = apply(src.read_text(encoding="utf-8"))
    dst.write_text(patched, encoding="utf-8", newline="\n")
    print(f"applied hunks: {applied}")
    print(f"wrote {dst}")
    # report the delta so the diff can be reviewed without a build
    before = src.read_text(encoding="utf-8").splitlines()
    after = patched.splitlines()
    print(f"lines: {len(before)} -> {len(after)} (+{len(after) - len(before)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
