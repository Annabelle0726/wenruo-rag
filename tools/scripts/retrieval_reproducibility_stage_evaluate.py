"""Stage-capture evaluator — merges the instrumentation-v2 stage data into the report artifacts.

Reads retrieval_stage_raw.txt (and retrieval_stage_err.txt for the embedding-quota timeline),
computes per-query pool/route/sub-query divergence, cutoff near-tie deltas and embedding
determinism, then merges a `stage_capture` block into retrieval_reproducibility.json, writes
retrieval_stage_detail.md, and inserts that section into retrieval_reproducibility.md as section 10.

Read-only with respect to the deployment: it only reads files already on disk.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
STAGE_RAW = ROOT / "retrieval_stage_raw.txt"
STAGE_ERR = ROOT / "retrieval_stage_err.txt"
MAIN_JSON = ROOT / "retrieval_reproducibility.json"
MAIN_MD = ROOT / "retrieval_reproducibility.md"
SECTION = ROOT / "retrieval_stage_detail.md"
BEGIN, END = "STAGE_JSON_BEGIN", "STAGE_JSON_END"

ORDER = ["S_A1", "S_A3", "S_B1", "S_C3", "U_A2", "U_A4", "U_A5", "U_B6", "U_C1", "K_STD", "K_3CORE", "K_LAYER"]


def signature(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def load_stage() -> dict:
    text = STAGE_RAW.read_text(encoding="utf-8", errors="replace")
    return json.loads(text.split(BEGIN, 1)[1].split(END, 1)[0].strip())


def quota_timeline() -> dict:
    if not STAGE_ERR.exists():
        return {"status": "NOT_OBSERVABLE", "reason": "stderr file missing"}
    lines = STAGE_ERR.read_text(encoding="utf-8", errors="replace").splitlines()
    quota_indexes = [index for index, line in enumerate(lines) if "RESOURCE_EXHAUSTED" in line or "quota exhausted" in line]
    route_failures = [index for index, line in enumerate(lines) if "failed: GeminiEmbed" in line]
    progress = [(index, line) for index, line in enumerate(lines) if "[stage]" in line]
    if not quota_indexes:
        return {"status": "NO_QUOTA_FAILURE_OBSERVED", "route_failure_lines": len(route_failures)}
    first = quota_indexes[0]
    before = [(index, line) for index, line in progress if index < first]
    last_progress = before[-1][1] if before else "NONE"
    parts = last_progress.replace("[stage]", "").strip().split()
    query_id, run_number = (parts[0], int(parts[2].split("/")[0])) if len(parts) >= 3 else ("UNKNOWN", 0)
    degraded = list(ORDER[ORDER.index(query_id) + 1 :]) if query_id in ORDER else []
    return {
        "status": "QUOTA_EXHAUSTED_MID_RUN",
        "first_quota_line_number": first + 1,
        "last_clean_progress": last_progress,
        "last_clean_query": query_id,
        "last_clean_run": run_number,
        "quota_error_lines": len(quota_indexes),
        "route_failure_lines": len(route_failures),
        "clean_queries": ORDER[: ORDER.index(query_id) + 1] if query_id in ORDER else [],
        "partially_degraded_query": query_id,
        "degraded_queries": degraded,
        "provenance": "OBSERVED (probe stderr: GeminiEmbed 429 RESOURCE_EXHAUSTED, free-tier limit 1000 embed requests/day)",
    }


def pool_of(run: dict) -> list:
    best: list = []
    for pool in (run.get("stages") or {}).get("pools") or []:
        candidates = pool.get("candidates") or []
        if len(candidates) > len(best):
            best = candidates
    return best


def routes_of(run: dict) -> dict:
    out: dict = {}
    for call in (run.get("stages") or {}).get("routes") or []:
        label = call.get("route") or "unlabeled"
        key = label if label != "unlabeled" else str(call.get("fn"))
        out.setdefault(key, []).extend(row["id"] for row in call.get("candidates") or [])
    return out


def main() -> int:
    report = load_stage()
    timeline = quota_timeline()
    queries = []
    for query in report.get("queries", []):
        runs = query.get("runs") or []
        pools = [[row["id"] for row in pool_of(run)] for run in runs]
        route_maps = [routes_of(run) for run in runs]
        sub_queries = [(run.get("stages") or {}).get("sub_queries") or [] for run in runs]
        finals = [run.get("final_ids") or [] for run in runs]
        stages = {
            "sub_queries": [signature(item) for item in sub_queries],
            "per_route_candidates": [signature(item) for item in route_maps],
            "pool_before_cut": [signature(item) for item in pools],
            "final_selection": [signature(item) for item in finals],
        }
        first = None
        for name in ("sub_queries", "per_route_candidates", "pool_before_cut", "final_selection"):
            values = {value for value in stages[name] if value not in ("{}", "[]")}
            if len(values) > 1:
                first = name
                break
        cutoff = []
        for index, run in enumerate(runs):
            final_ids = finals[index]
            pool = pool_of(run)
            pool_ids = [row["id"] for row in pool]
            by_id = {row["id"]: row for row in pool}
            last_included = pool_ids[len(final_ids) - 1] if final_ids and len(pool_ids) >= len(final_ids) else (final_ids[-1] if final_ids else None)
            excluded = [row for row in pool if row["id"] not in set(final_ids)]
            first_excluded = None
            if excluded:
                first_excluded = max(excluded, key=lambda row: row.get("similarity") if row.get("similarity") is not None else -1)
            included_row = by_id.get(last_included) or next((row for row in (run.get("final") or []) if row["id"] == last_included), None)
            delta = None
            if included_row and first_excluded and included_row.get("similarity") is not None and first_excluded.get("similarity") is not None:
                delta = round(abs(included_row["similarity"] - first_excluded["similarity"]), 6)
            ordered = [by_id.get(cid) or next((row for row in (run.get("final") or []) if row["id"] == cid), None) for cid in final_ids]
            inside = []
            for left, right in zip(ordered, ordered[1:]):
                if left and right and left.get("similarity") is not None and right.get("similarity") is not None:
                    inside.append(round(abs(left["similarity"] - right["similarity"]), 6))
            cutoff.append(
                {
                    "run": index + 1,
                    "pool_size": len(pool_ids),
                    "last_included": {"id": last_included, "similarity": (included_row or {}).get("similarity")},
                    "first_excluded": {"id": (first_excluded or {}).get("id"), "similarity": (first_excluded or {}).get("similarity")},
                    "cutoff_delta": delta,
                    "min_adjacent_delta_inside_window": min(inside) if inside else None,
                    "excluded_ids": [row["id"] for row in excluded],
                }
            )
        deltas = [item["cutoff_delta"] for item in cutoff if item["cutoff_delta"] is not None]
        inside_all = [item["min_adjacent_delta_inside_window"] for item in cutoff if item["min_adjacent_delta_inside_window"] is not None]
        degraded = query["id"] in timeline.get("degraded_queries", []) or query["id"] == timeline.get("partially_degraded_query")
        queries.append(
            {
                "id": query["id"],
                "class": query["class"],
                "text": query["text"],
                "embedding_probe": query.get("embedding_probe"),
                "pool_sizes": [len(item) for item in pools],
                "distinct_pools": len({signature(item) for item in pools}),
                "distinct_sub_query_sets": len({signature(item) for item in sub_queries}),
                "distinct_route_maps": len({signature(item) for item in route_maps}),
                "distinct_final_windows": len({signature(item) for item in finals}),
                "stages": stages,
                "first_divergence_stage": first or "NONE_UP_TO_FINAL_SELECTION",
                "route_labels": sorted({label for item in route_maps for label in item.keys()}),
                "sub_queries_first_run": sub_queries[0] if sub_queries else [],
                "cutoff": cutoff,
                "cutoff_delta_min": min(deltas) if deltas else None,
                "cutoff_delta_max": max(deltas) if deltas else None,
                "min_adjacent_delta_inside_window": min(inside_all) if inside_all else None,
                "cutoff_flag": "NEAR_TIE_AT_CUTOFF" if (deltas and min(deltas) < 0.005) else ("NO_NEAR_TIE_AT_CUTOFF" if deltas else "NOT_OBSERVABLE"),
                "quota_degraded": degraded,
                "call_names": sorted({name for run in runs for name in (run.get("call_names") or [])}),
                "errors": [run.get("error") for run in runs if run.get("error")],
            }
        )

    if MAIN_JSON.exists():
        main_json = json.loads(MAIN_JSON.read_text(encoding="utf-8"))
        main_json["stage_capture"] = {
            "provenance": "OBSERVED (instrumentation v2, series A only, identical frozen parameters)",
            "purpose": report.get("purpose"),
            "chat_model_path": report.get("chat_model_path"),
            "wrappers_fired": report.get("wrappers_fired"),
            "chat_model_calls_total": report.get("chat_model_calls_total"),
            "dealer_has_retrieval": report.get("dealer_has_retrieval"),
            "embedding_provider_finding": (
                "The deployed embedding provider is a remote Gemini API (gemini-embedding-1.0) on a free tier capped at "
                "1000 embed requests/day. Once the cap was reached the dense route failed with 429 RESOURCE_EXHAUSTED, "
                "was logged as a route warning, and the window was built from the remaining routes."
            ),
            "quota_timeline": timeline,
            "queries": queries,
        }
        MAIN_JSON.write_text(json.dumps(main_json, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "## 10. Stage capture (instrumentation v2, series A)",
        "",
        "Probe v1 recorded decomposition and final windows for both series but could not see the per-route",
        "candidates or the pre-cut pool: the deployed pipeline does **not** route through `Dealer.retrieval`",
        "(`dealer_has_retrieval = " + str(report.get("dealer_has_retrieval")) + "`), and the pool is passed as an",
        "**argument** to the selection step. Version 2 records arguments as well as return values, on the same",
        "frozen configuration. Answer generation still happens nowhere in the probe.",
        "",
        "### 10.1 Embedding-quota degradation inside this probe (read before the tables)",
        "",
        f"- Status: **{timeline.get('status')}**",
        f"- Last clean progress line: `{timeline.get('last_clean_progress')}` (query {timeline.get('last_clean_query')}, run {timeline.get('last_clean_run')})",
        f"- Quota error lines: {timeline.get('quota_error_lines')}, route-failure lines: {timeline.get('route_failure_lines')}",
        f"- Queries measured **before** the failure: {', '.join(timeline.get('clean_queries', []))}",
        f"- Queries measured **after** it (degraded: the dense route dropped out): {', '.join(timeline.get('degraded_queries', []))}",
        f"- Provenance: {timeline.get('provenance')}",
        "",
        "Probe v1 (both series, all 12 queries, 240 runs) recorded **zero** quota failures, so the stability",
        "result in sections 3-7 stands. Only the stage detail below is affected, and each row says so.",
        "",
        "| query | pool sizes | distinct pools | distinct sub-query sets | distinct route sets | distinct windows | first divergence | cutoff flag | min cutoff delta | quota |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for query in queries:
        lines.append(
            f"| {query['id']} | {query['pool_sizes'][:3]}... | {query['distinct_pools']} | {query['distinct_sub_query_sets']} | {query['distinct_route_maps']} | "
            f"{query['distinct_final_windows']} | {query['first_divergence_stage']} | {query['cutoff_flag']} | {query['cutoff_delta_min']} | "
            f"{'DEGRADED' if query['quota_degraded'] else 'clean'} |"
        )
    lines += ["", "### 10.2 Query embedding determinism (10 encodes per query)", "",
              "| query | convention used | dim | unique sha256 | bit-identical | pairwise cosine min | verdict |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for query in queries:
        probe = query.get("embedding_probe") or {}
        lines.append(
            f"| {query['id']} | {probe.get('convention')} | {probe.get('dim')} | {probe.get('sha256_unique_count')}/{probe.get('runs')} | "
            f"{probe.get('vectors_bit_identical')} | {probe.get('pairwise_cosine_min')} | {probe.get('verdict')} |"
        )
    lines += ["", "### 10.3 Sub-queries actually used (first run of each query)", ""]
    for query in queries:
        rendered = " | ".join(query.get("sub_queries_first_run") or []) or "NONE"
        lines.append(f"- **{query['id']}**{' (degraded)' if query['quota_degraded'] else ''}: {rendered[:400]}")
    lines += ["", "### 10.4 Cutoff detail (first run of each query)", ""]
    for query in queries:
        first_cut = (query.get("cutoff") or [{}])[0]
        lines.append(
            f"- **{query['id']}**: pool {first_cut.get('pool_size')}, last included {first_cut.get('last_included', {}).get('id')}"
            f"@{(first_cut.get('last_included') or {}).get('similarity')}, first excluded {first_cut.get('first_excluded', {}).get('id')}"
            f"@{(first_cut.get('first_excluded') or {}).get('similarity')}, delta {first_cut.get('cutoff_delta')}, "
            f"min in-window adjacent delta {first_cut.get('min_adjacent_delta_inside_window')}, excluded {first_cut.get('excluded_ids')}"
        )
    lines += [
        "",
        "### 10.5 Instrumented call names",
        "",
        f"`{signature(sorted({name for query in queries for name in query['call_names']}))[:900]}`",
        "",
        "Note: `Dealer.retrieval` never appears in that list, which is why probe v1 produced no per-route data —",
        "the deployed multi-route path reaches the store through its own route helpers.",
    ]
    SECTION.write_text("\n".join(lines), encoding="utf-8")

    if MAIN_MD.exists():
        document = MAIN_MD.read_text(encoding="utf-8")
        marker = "## 9. Limitations"
        index = document.rfind(marker)
        if index != -1:
            document = document[:index] + "\n".join(lines) + "\n\n## 11. Limitations" + document[index + len(marker):]
            MAIN_MD.write_text(document, encoding="utf-8")
    print(
        json.dumps(
            {
                "quota_timeline": timeline,
                "queries": [
                    {
                        "id": query["id"],
                        "pool_sizes": query["pool_sizes"][:2],
                        "distinct_pools": query["distinct_pools"],
                        "distinct_sub_query_sets": query["distinct_sub_query_sets"],
                        "distinct_route_maps": query["distinct_route_maps"],
                        "distinct_windows": query["distinct_final_windows"],
                        "first_divergence": query["first_divergence_stage"],
                        "cutoff_flag": query["cutoff_flag"],
                        "cutoff_min": query["cutoff_delta_min"],
                        "in_window_min_delta": query["min_adjacent_delta_inside_window"],
                        "embedding": (query.get("embedding_probe") or {}).get("verdict"),
                        "sub_queries": len(query.get("sub_queries_first_run") or []),
                        "degraded": query["quota_degraded"],
                    }
                    for query in queries
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
