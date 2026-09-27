"""Failure-mode characterization generator (Tasks A-F).

Reads: decomposition_cold_raw.txt (Task A probe), decomposition_cold_err.txt, retrieval_reproducibility.json
(v1 window record), retrieval_stage_raw.txt (v2, used ONLY to document its own contamination).

Writes: failure_mode_characterization.json + failure_mode_characterization.md, and appends a correction
notice to retrieval_reproducibility.md. Read-only with respect to the deployment.
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
COLD_RAW = ROOT / "decomposition_cold_raw.txt"
COLD_ERR = ROOT / "decomposition_cold_err.txt"
V1_JSON = ROOT / "retrieval_reproducibility.json"
V2_RAW = ROOT / "retrieval_stage_raw.txt"
OUT_JSON = ROOT / "failure_mode_characterization.json"
OUT_MD = ROOT / "failure_mode_characterization.md"
OLD_MD = ROOT / "retrieval_reproducibility.md"


def norm(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "")).lower()


def jaccard(left, right) -> float:
    a, b = {norm(x) for x in left if norm(x)}, {norm(x) for x in right if norm(x)}
    return round(len(a & b) / len(a | b), 4) if (a | b) else 1.0


def load_cold() -> dict:
    text = COLD_RAW.read_text(encoding="utf-8", errors="replace")
    return json.loads(text.split("COLD_JSON_BEGIN", 1)[1].split("COLD_JSON_END", 1)[0].strip())


def stderr_counts(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {
        "quota_error_lines": sum(1 for line in lines if "RESOURCE_EXHAUSTED" in line or "quota exhausted" in line),
        "route_failure_lines": sum(1 for line in lines if "failed: GeminiEmbed" in line),
        "type_error_lines": sum(1 for line in lines if "classmethod" in line),
    }


def task_a(cold: dict) -> list:
    out = []
    for query in cold.get("queries", []):
        runs = query.get("runs") or []
        decompositions = [run.get("sub_queries") or [] for run in runs]
        side = runs[0].get("side_routes") or [] if runs else []
        route_sets = [[query["text"], *subs, *side] for subs in decompositions]
        distinct = []
        for subs in decompositions:
            key = tuple(sorted(norm(item) for item in subs))
            if key not in [item["key"] for item in distinct]:
                distinct.append({"key": key, "sub_queries": subs})
        pairwise_subs = [jaccard(decompositions[i], decompositions[j]) for i in range(len(decompositions)) for j in range(i + 1, len(decompositions))]
        pairwise_routes = [jaccard(route_sets[i], route_sets[j]) for i in range(len(route_sets)) for j in range(i + 1, len(route_sets))]
        windows = [run.get("window_ids") or [] for run in runs]
        coverage_gaps = sorted({len(set(norm(x) for x in decompositions[i]) ^ set(norm(x) for x in decompositions[j])) for i in range(len(decompositions)) for j in range(i + 1, len(decompositions))}, reverse=True)
        out.append(
            {
                "id": query["id"],
                "kind": query["kind"],
                "raw_query": query["text"],
                "looks_composite": query["looks_composite"],
                "runs": len(runs),
                "decomposition_calls_per_run": [run.get("decomposition_calls") for run in runs],
                "distinct_decomposition_count": len(distinct),
                "distinct_decompositions": [item["sub_queries"] for item in distinct][:4],
                "pairwise_sub_query_jaccard_min": min(pairwise_subs) if pairwise_subs else None,
                "pairwise_route_set_jaccard_min": min(pairwise_routes) if pairwise_routes else None,
                "sub_query_count_per_run": [len(item) for item in decompositions],
                "max_symmetric_difference_between_decompositions": coverage_gaps[0] if coverage_gaps else 0,
                "replay_windows_empty": all(len(window) == 0 for window in windows),
                "replay_window_sizes": [len(window) for window in windows],
                "replay_status": "BLOCKED_BY_EMBEDDING_QUOTA" if all(len(window) == 0 for window in windows) else "OBSERVED",
            }
        )
    return out


def main() -> int:
    cold = load_cold()
    queries = task_a(cold)
    cold_err = stderr_counts(COLD_ERR)
    v2_err = stderr_counts(ROOT / "retrieval_stage_err.txt")

    v1 = json.loads(V1_JSON.read_text(encoding="utf-8")) if V1_JSON.exists() else {}
    structured = [
        {
            "id": query["id"],
            "class": query["class"],
            "first_divergence_stage": payload["first_divergence_stage"],
            "exact_match_rate": payload["window_stats"]["exact_match_rate_vs_run1"],
            "jaccard_at_k_mean": payload["window_stats"]["jaccard_at_k_mean"],
            "classification": payload["classification"]["primary"],
            "family_runs_with_target_family": (payload.get("family_presence") or {}).get("runs_with_family_in_window"),
        }
        for query in v1.get("queries", [])
        for tag, payload in query["series"].items()
        if tag == "A_chat_model_present"
    ]
    kbinfos_keys = sorted({json.dumps(payload["kbinfos_keys"]) for query in v1.get("queries", []) for payload in query["series"].values()})

    if V2_RAW.exists():
        text = V2_RAW.read_text(encoding="utf-8", errors="replace")
        v2 = json.loads(text.split("STAGE_JSON_BEGIN", 1)[1].split("STAGE_JSON_END", 1)[0].strip())
        v2_runs = [
            {"id": query["id"], "runs": len(query["runs"]), "runs_raising": sum(1 for run in query["runs"] if run.get("error")), "window_lengths": [len(run.get("final_ids") or []) for run in query["runs"]]}
            for query in v2["queries"]
        ]
    else:
        v2_runs = []

    composite = [query for query in queries if query["kind"] == "COMPOSITE"]
    controls = [query for query in queries if query["kind"] == "NON_COMPOSITE_CONTROL"]
    varying = [query for query in queries if query["distinct_decomposition_count"] > 1]
    verdict = (
        "MATERIAL_DECOMPOSITION_VARIANCE_OBSERVED_AT_ROUTE_LEVEL_REPLAY_BLOCKED"
        if varying and all(query["replay_status"] == "BLOCKED_BY_EMBEDDING_QUOTA" for query in varying)
        else ("DECOMPOSITION_VARIANCE_NON_MATERIAL_IN_TEST_SET" if not varying else "MATERIAL_DECOMPOSITION_VARIANCE_OBSERVED")
    )

    report = {
        "purpose": "Failure-mode characterization: cold-cache decomposition sensitivity and dense-route degradation",
        "headline": "Under pinned inputs and configuration, deployed retrieval is reproducible. The remaining reproducibility and availability risks are upstream LLM decomposition on cache miss and runtime dense-route degradation.",
        "no_fix_declaration": "No retrieval parameter, prompt, reranker, embedding model, index, Redis key, or deployed file was modified in this round.",
        "task_a": {
            "isolation_method": "in-process cache bypass (get_llm_cache forced to miss, set_llm_cache no-op); production Redis never read, written, deleted or flushed",
            "cache_functions_before_patch": cold.get("cache_functions_before"),
            "patched_modules": cold.get("patched_modules"),
            "chat_model_calls_total": cold.get("chat_model_calls_total"),
            "frozen_parameters": cold.get("frozen_parameters"),
            "queries": queries,
            "composite_queries": [query["id"] for query in composite],
            "control_queries": [query["id"] for query in controls],
            "queries_with_variance": [query["id"] for query in varying],
            "verdict": verdict,
            "stderr": cold_err,
            "redis_role_verdict": (
                "REDIS_CACHE_IS_FACTUALLY_PERFORMING_REPRODUCIBILITY_STABILISATION: with the cache bypassed the same "
                "question yields different route sets on repeat, while the earlier warm-cache round produced "
                "byte-identical decompositions and 10/10 identical evidence windows over 240 runs."
            ),
        },
        "task_b": {
            "chain": [
                "embedding request failure (429 RESOURCE_EXHAUSTED from the remote embedding API)",
                "route-level exception handling: the failing route is isolated and logged as a warning, the remaining routes continue",
                "warning/error: warning only, in the retrieval module logger",
                "remaining candidate pool: the window is built from the routes that survived",
                "synthesis caller: receives the normal result object",
            ],
            "machine_readable_degradation_state": "NOT PRESENT",
            "machine_readable_evidence": f"the retrieval result exposes exactly {kbinfos_keys} and no degraded/health field; a 240-run probe in which nothing failed returned zero errors, and the quota-affected probes returned the same key set",
            "caller_awareness": "NOT AWARE in the silent case; in the observed 429 trace the caller sometimes received a raised exception instead, so awareness is path-dependent rather than guaranteed",
            "http_200_claim": "NOT VERIFIED THIS ROUND (no API call was issued; doing so would consume embedding quota, which is forbidden by the round rules)",
            "trace_evidence": {
                "stage_probe_429_route_failures": v2_err.get("route_failure_lines"),
                "stage_probe_429_quota_lines": v2_err.get("quota_error_lines"),
                "cold_probe_429_route_failures": cold_err.get("route_failure_lines"),
                "cold_probe_429_quota_lines": cold_err.get("quota_error_lines"),
                "quota_cap_evidence": "free-tier limit 1000 embed requests/day for gemini-embedding-1.0 as reported by the API error body",
            },
            "classification": "SILENT_RETRIEVAL_DEGRADATION",
            "classification_scope": "supported for the retrieval layer (no degradation flag, warning-only logging, window built from surviving routes); the HTTP layer is NOT VERIFIED",
        },
        "task_c": {
            "document_family_availability": "stable within a pinned configuration (v1: target family present in the window in 10/10 runs for every query that has a defined target family)",
            "authoritative_evidence_availability": "NOT REVIEWED (no human annotation exists; the earlier human evidence template is still all PENDING, so no authoritative-evidence claim is made)",
            "structural_record": structured,
        },
        "task_d": {
            "tie_breaker_status": "LATENT TIE-BREAK RISK - NOT OBSERVED AS A FAILURE",
            "basis": "three candidate-ordering sites have no secondary sort key, but 240 pinned runs produced 10/10 identical windows and Jaccard@K 1.0, so no tie-induced window change was observed",
        },
        "task_e_failure_mode_matrix": [
            {"failure_mode": "LLM decomposition variance (cold cache)", "status": "OBSERVED", "evidence": "cold-cache probe: distinct route sets per query on repeat", "impact": "route-set change; window impact BLOCKED_BY_EMBEDDING_QUOTA"},
            {"failure_mode": "Embedding quota exhaustion (remote API 429)", "status": "OBSERVED", "evidence": "460 quota lines and 230 route-failure lines in the cold probe; 290/139 in the stage probe", "impact": "dense route drops out, warning-only, no degradation flag"},
            {"failure_mode": "ANN nondeterminism (same vector, same query)", "status": "NO / controlled replay / NOT OBSERVED", "evidence": "240 pinned runs with 10/10 identical windows; three identical GET kNN probes bit-identical", "impact": "none observed"},
            {"failure_mode": "Score tie instability (equal or near-equal score)", "status": "LATENT RISK", "evidence": "no secondary sort key at any of the three ordering sites; no tie-induced change observed in 240 runs", "impact": "none observed"},
            {"failure_mode": "Hash ordering (process hash seed)", "status": "CLOSED / NO PATH", "evidence": "no set-ordered or dict-ordered construct reaches candidate order; the only hashing is content-addressed", "impact": "none"},
        ],
        "task_f_generalization_risks": [
            {"risk": "external embedding dependency", "mechanism": "query and document vectors come from a remote provider with a request quota; exhaustion removes an entire retrieval leg", "corpus_independent": True, "observed": "YES"},
            {"risk": "decomposition sampling", "mechanism": "the decomposition model call sets no temperature, top_p or seed, so a cache miss can return a different route set", "corpus_independent": True, "observed": "YES"},
            {"risk": "cache-dependent reproducibility", "mechanism": "reproducibility currently rests on a time-limited external cache rather than on deterministic generation", "corpus_independent": True, "observed": "YES"},
            {"risk": "silent route degradation", "mechanism": "a failed leg is logged as a warning and the result object carries no health field", "corpus_independent": True, "observed": "YES"},
            {"risk": "score tie handling", "mechanism": "ordering is score-only with no secondary key, so ties inherit insertion order", "corpus_independent": True, "observed": "NO (latent)"},
            {"risk": "pool-dependent fallback amplification", "mechanism": "recall-floor and follow-up branches are decided by pool composition, so a small upstream change can change the route set and then every downstream tie", "corpus_independent": True, "observed": "DERIVED"},
        ],
        "correction_v2_instrumentation": {
            "statement": "The instrumentation-v2 stage capture is retracted. Every one of its 120 runs returned an empty window, and 8 to 10 of 10 runs per query raised TypeError: 'classmethod' object is not callable from this round's own wrapper, which the pipeline route-failure isolation absorbed.",
            "runs": v2_runs,
            "effect": "Sections 10, 12 and 13 of retrieval_reproducibility.md drew pool sizes, cutoff deltas and per-route identities from that run. Those specific numbers are withdrawn as evidence; the stability result rests on probe v1 (240 runs, zero errors, zero quota failures), which is unaffected.",
            "quota_attribution": "The 429 lines in the stage-probe stderr are real, but the empty windows cannot be attributed to the quota because the instrumentation itself broke retrieval in the same runs.",
        },
        "limitations": [
            "Task A materiality is answered at the route-set level only; the evidence-window half is BLOCKED_BY_EMBEDDING_QUOTA because the embedding quota is exhausted for the day.",
            "No API call was made, so HTTP-level behaviour of a degraded retrieval is NOT VERIFIED.",
            "Authoritative-evidence availability is NOT REVIEWED: no human annotation exists.",
            "The remote quota resets daily, so the blocked replay can be repeated without any parameter change once quota is available.",
        ],
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Failure-Mode Characterization",
        "",
        f"**Headline:** {report['headline']}",
        "",
        report["no_fix_declaration"],
        "",
        "> **Correction up front.** The instrumentation-v2 stage capture is retracted: every one of its 120 runs",
        "> returned an empty window and 8-10 of 10 runs per query raised `TypeError: 'classmethod' object is not",
        "> callable` from this round's own wrapper, absorbed by the pipeline route-failure isolation. Sections 10,",
        "> 12 and 13 of `retrieval_reproducibility.md` drew pool sizes, cutoff deltas and per-route identities from",
        "> that run; those numbers are withdrawn. The stability result rests on probe v1 (240 runs, zero errors,",
        "> zero quota failures) and is unaffected.",
        "",
        "## Task A — Decomposition cold-cache sensitivity",
        "",
        f"- Isolation: {report['task_a']['isolation_method']}",
        f"- Cache functions before patching: `{json.dumps(report['task_a']['cache_functions_before_patch'], ensure_ascii=False)}`",
        f"- Chat-model calls actually made (proves the cache was bypassed rather than hit): **{report['task_a']['chat_model_calls_total']}**",
        f"- Frozen parameters: `{json.dumps(report['task_a']['frozen_parameters'], ensure_ascii=False)}`",
        f"- Probe stderr: {json.dumps(cold_err)}",
        "",
        "| query | kind | looks_composite | runs | distinct decompositions | sub-query count per run | min pairwise sub-query Jaccard | min pairwise route-set Jaccard | max symmetric difference | replay |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for query in queries:
        lines.append(
            f"| {query['id']} | {query['kind']} | {query['looks_composite']} | {query['runs']} | {query['distinct_decomposition_count']} | "
            f"{query['sub_query_count_per_run']} | {query['pairwise_sub_query_jaccard_min']} | {query['pairwise_route_set_jaccard_min']} | "
            f"{query['max_symmetric_difference_between_decompositions']} | {query['replay_status']} |"
        )
    lines += ["", "### Distinct decompositions observed (per query, up to four)", ""]
    for query in queries:
        lines.append(f"- **{query['id']}** ({query['raw_query']})")
        for index, decomposition in enumerate(query["distinct_decompositions"], 1):
            lines.append(f"  {index}. {' | '.join(decomposition)[:320] if decomposition else 'NONE (no sub-queries)'}")
    lines += [
        "",
        f"**Verdict:** `{report['task_a']['verdict']}`",
        "",
        "**Is the Redis cache a performance optimisation or a reproducibility stabiliser?**",
        report["task_a"]["redis_role_verdict"],
        "",
        "### Retrieval replay",
        "",
        f"- Status: **{queries[0]['replay_status'] if queries else 'UNKNOWN'}** for every query that showed variance.",
        "- Cause: the remote embedding quota was already exhausted, so the dense leg failed on every replay run (see the 429 counts above) and every window came back empty.",
        "- Consequence: whether two cold decompositions yield different Top-8 evidence windows is **not answerable today**. The route sets differ, and section 13.4 documents the pool-dependent branches that would amplify such a difference, but no window-level claim is made.",
        "",
        "### Downstream amplification (status per mechanism)",
        "",
        "| mechanism | status in this round |",
        "| --- | --- |",
        "| recall-floor rescue branch | INERT at the pinned threshold (the configured threshold equals the recall floor, so the second call is identical) |",
        "| core-document follow-up branch | NOT OBSERVABLE (its wrapper could not be exercised without a populated pool) |",
        "| document-family change | NOT OBSERVED (blocked with the replay) |",
        "| key evidence chunk loss | NOT OBSERVED (blocked with the replay) |",
        "",
        "## Task B — Dense-route degradation characterization",
        "",
        "| link in the chain | finding |",
        "| --- | --- |",
    ]
    for index, link in enumerate(report["task_b"]["chain"], 1):
        lines.append(f"| {index} | {link} |")
    task_b = report["task_b"]
    lines += [
        "",
        f"- **Machine-readable degradation state:** {task_b['machine_readable_degradation_state']} — {task_b['machine_readable_evidence']}",
        f"- **Caller awareness:** {task_b['caller_awareness']}",
        f"- **HTTP status claim:** {task_b['http_200_claim']}",
        f"- **Trace evidence:** {json.dumps(task_b['trace_evidence'], ensure_ascii=False)}",
        "",
        f"**Classification: `{task_b['classification']}`** — {task_b['classification_scope']}",
        "",
        "## Task C — Evidence impact: document family versus authoritative evidence",
        "",
        f"- **Document-family availability:** {report['task_c']['document_family_availability']}",
        f"- **Authoritative-evidence availability:** {report['task_c']['authoritative_evidence_availability']}",
        "",
        "| query | first divergence | EMR | Jaccard@K | classification | runs with target family in window |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in structured:
        lines.append(f"| {row['id']} | {row['first_divergence_stage']} | {row['exact_match_rate']} | {row['jaccard_at_k_mean']} | {row['classification']} | {row['family_runs_with_target_family']} |")
    lines += [
        "",
        "No window-Jaccard-only claim is made here: family availability and authoritative-evidence availability are",
        "reported separately, and the latter is **NOT REVIEWED**.",
        "",
        "## Task D — Tie-breaker status correction",
        "",
        f"**{report['task_d']['tie_breaker_status']}**",
        "",
        report["task_d"]["basis"] + ".",
        "",
        "## Task E — Failure Mode Matrix",
        "",
        "| failure mode | status | evidence | impact |",
        "| --- | --- | --- | --- |",
    ]
    for row in report["task_e_failure_mode_matrix"]:
        lines.append(f"| {row['failure_mode']} | **{row['status']}** | {row['evidence']} | {row['impact']} |")
    lines += [
        "",
        "## Task F — Generalization Risk Table (corpus-independent)",
        "",
        "| mechanism risk | mechanism | corpus-independent | observed |",
        "| --- | --- | --- | --- |",
    ]
    for row in report["task_f_generalization_risks"]:
        lines.append(f"| {row['risk']} | {row['mechanism']} | {row['corpus_independent']} | {row['observed']} |")
    lines += [
        "",
        "Deliberately free of corpus-specific wording: no standard number, no core count, no document-part name.",
        "",
        "## Limitations",
        "",
    ] + [f"- {item}" for item in report["limitations"]]
    lines += ["", "Characterization complete. No fix code, no parameter change, no index write, no Redis mutation.", ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    if OLD_MD.exists():
        document = OLD_MD.read_text(encoding="utf-8")
        notice = (
            "\n## 14. CORRECTION: instrumentation v2 is retracted\n\n"
            "Every one of the 120 runs of the instrumentation-v2 stage capture returned an **empty** final window, and\n"
            "8 to 10 of 10 runs per query raised `TypeError: 'classmethod' object is not callable` from this round's own\n"
            "wrapper, which the pipeline route-failure isolation absorbed. Sections 10, 12 and 13 drew pool sizes, cutoff\n"
            "deltas and per-route identities from that run; **those specific numbers are withdrawn as evidence**. The\n"
            "stability result in sections 3-7 rests on probe v1 (240 runs, zero errors, zero quota failures) and is\n"
            "unaffected. The 429 lines in the stage-probe stderr are real, but the empty windows cannot be attributed to\n"
            "the quota because the instrumentation broke retrieval in the same runs. See `failure_mode_characterization.md`.\n"
        )
        if "## 14. CORRECTION" not in document:
            OLD_MD.write_text(document.rstrip() + "\n" + notice, encoding="utf-8")

    print(
        json.dumps(
            {
                "task_a_verdict": verdict,
                "chat_calls": cold.get("chat_model_calls_total"),
                "queries": [
                    {"id": query["id"], "kind": query["kind"], "composite": query["looks_composite"], "distinct": query["distinct_decomposition_count"], "subs_per_run": query["sub_query_count_per_run"], "jaccard_min": query["pairwise_sub_query_jaccard_min"], "route_jaccard_min": query["pairwise_route_set_jaccard_min"], "replay": query["replay_status"]}
                    for query in queries
                ],
                "cold_stderr": cold_err,
                "kbinfos_keys": kbinfos_keys,
                "v2_retracted": {"runs": len(v2_runs), "raising": sum(row["runs_raising"] for row in v2_runs)},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
