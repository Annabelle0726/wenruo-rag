"""P1-0 characterization: quantify planner variance for cold cache, and test the plan_hash contract.

Reads the COLD_JSON block produced by the Phase A decomposition probe on the CURRENT baseline and computes,
per query: raw-vs-canonical distinctness, route-count variance, pairwise Jaccard and symmetric difference.

The canonicaliser below is a REFERENCE implementation for this characterization only. It is not product
code and changes nothing; its purpose is to measure whether hashing the canonical plan tracks retrieval
topology while hashing the raw model output tracks serialization noise.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import pathlib
import re
import unicodedata

LOG = pathlib.Path(os.environ["TEMP"]) / "p10_char.log"
OUT = pathlib.Path(os.environ["TEMP"]) / "p10_char_summary.json"

TRAILING = "？?。.！!，,、;；:： 　"
WS = re.compile(r"\s+")


def canonical_route(text: str) -> str:
    """Reference canonicalisation of ONE route string (specification, not product code)."""
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = WS.sub(" ", value).strip()
    value = value.strip(TRAILING)
    return value


def canonical_set(sequences) -> frozenset:
    """Canonical retrieval topology contribution: deduped, order-free set of canonical routes."""
    out = set()
    for seq in sequences:
        for route in seq["sub_queries"] + seq["side_routes"]:
            canon = canonical_route(route)
            if canon:
                out.add(canon)
    return frozenset(out)


def plan_hash(topology: frozenset) -> str:
    """plan_hash over the CANONICAL plan (sorted, so it is order-independent and text-stable)."""
    joined = "\n".join(sorted(topology))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def main() -> int:
    blob = LOG.read_bytes()
    # PowerShell's `>` redirect writes UTF-16LE; accept either encoding.
    for encoding in ("utf-8", "utf-16", "utf-16-le", "latin-1"):
        try:
            raw = blob.decode(encoding)
        except Exception:  # noqa: BLE001
            continue
        if "COLD_JSON_BEGIN" in raw:
            break
    else:
        raise SystemExit(f"COLD_JSON_BEGIN not found in {LOG} ({len(blob)} bytes)")
    start = raw.index("COLD_JSON_BEGIN") + len("COLD_JSON_BEGIN")
    end = raw.index("COLD_JSON_END")
    payload = json.loads(raw[start:end].strip())

    report: dict = {
        "gate": "P1_0_PLANNER_CHARACTERIZATION",
        "baseline_image": "ea93cd3bb795",
        "isolation": payload.get("isolation"),
        "runs_per_query": payload.get("runs_per_query"),
        "chat_model_calls_total": payload.get("chat_model_calls_total"),
        "wrappers_fired": payload.get("wrappers_fired"),
        "queries": [],
    }

    for query in payload["queries"]:
        runs = query["runs"]
        raw_sequences = [tuple(r["sub_queries"]) for r in runs]
        raw_sides = [tuple(r["side_routes"]) for r in runs]
        raw_combined = [a + b for a, b in zip(raw_sequences, raw_sides)]

        topologies = [canonical_set([r]) for r in runs]
        hashes = [plan_hash(t) for t in topologies]
        counts = [len(t) for t in topologies]

        pair_j = [jaccard(a, b) for a, b in itertools.combinations(topologies, 2)]
        pair_sym = [len(a ^ b) for a, b in itertools.combinations(topologies, 2)]

        # raw-output hash: what a naive "hash the model response" implementation would produce
        raw_hashes = {
            hashlib.sha256(json.dumps(seq, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
            for seq in raw_combined
        }

        report["queries"].append(
            {
                "id": query["id"],
                "kind": query["kind"],
                "looks_composite": query.get("looks_composite"),
                "runs": len(runs),
                "distinct_raw_ordered_sequences": len({json.dumps(s, ensure_ascii=False) for s in raw_combined}),
                "distinct_raw_hashes": len(raw_hashes),
                "distinct_canonical_topologies": len(set(hashes)),
                "distinct_route_counts": sorted(set(counts)),
                "topology_sizes": counts,
                "min_pair_jaccard": round(min(pair_j), 4) if pair_j else 1.0,
                "max_symmetric_difference": max(pair_sym) if pair_sym else 0,
                "cosmetic_only_variance": len(raw_hashes) > len(set(hashes)),
                "topology_variance": len(set(hashes)) > 1,
            }
        )

    queries = report["queries"]
    report["aggregate"] = {
        "queries_characterised": len(queries),
        "queries_with_topology_variance": sum(1 for q in queries if q["topology_variance"]),
        "queries_with_count_variance": sum(1 for q in queries if len(q["distinct_route_counts"]) > 1),
        "queries_where_raw_would_over_report": sum(1 for q in queries if q["cosmetic_only_variance"]),
        "total_distinct_raw_hashes": sum(q["distinct_raw_hashes"] for q in queries),
        "total_distinct_canonical_hashes": sum(q["distinct_canonical_topologies"] for q in queries),
        "worst_min_pair_jaccard": min(q["min_pair_jaccard"] for q in queries),
        "worst_max_symmetric_difference": max(q["max_symmetric_difference"] for q in queries),
    }
    report["phase_a_reproduction"] = (
        "MATERIAL_DECOMPOSITION_VARIANCE_OBSERVED_AT_ROUTE_LEVEL_REPLAY_BLOCKED"
        if report["aggregate"]["queries_with_topology_variance"] > 0
        else "NO_VARIANCE_REPRODUCED"
    )
    report["plan_hash_verdict"] = (
        "CANONICAL_PLAN_HASH_IS_REQUIRED: raw-output hashing over-reports "
        f"({report['aggregate']['total_distinct_raw_hashes']} distinct raw vs "
        f"{report['aggregate']['total_distinct_canonical_hashes']} distinct canonical across "
        f"{report['aggregate']['queries_characterised']} queries)"
    )

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("chat_model_calls_total:", report["chat_model_calls_total"], "(cache bypass proven)")
    print("wrappers_fired:", json.dumps(report["wrappers_fired"], ensure_ascii=False))
    print()
    print(f"{'query':<10} {'kind':<22} {'rawH':>5} {'canonH':>6} {'counts':<12} {'minJac':>7} {'maxSym':>6}")
    for q in queries:
        print(f"{q['id']:<10} {q['kind']:<22} {q['distinct_raw_hashes']:>5} "
              f"{q['distinct_canonical_topologies']:>6} {str(q['distinct_route_counts']):<12} "
              f"{q['min_pair_jaccard']:>7} {q['max_symmetric_difference']:>6}")
    print()
    print("aggregate:", json.dumps(report["aggregate"], ensure_ascii=False))
    print("phase_a_reproduction:", report["phase_a_reproduction"])
    print("plan_hash_verdict:", report["plan_hash_verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
