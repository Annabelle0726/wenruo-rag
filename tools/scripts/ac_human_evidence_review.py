"""Human evidence review harness for A/C (reads the immutable trace; never re-retrieves).

It produces `ac_human_evidence_review.md` from two inputs:

* `ac_trace_raw.json` - the immutable retrieval trace (OBSERVED facts only);
* `ac_evidence_judgment.json` - the SEMANTIC fields a person fills in. It is created here as a
  template with every judgment left `PENDING`, and this script NEVER fills one in: the standing
  rule is that relevance / evidence_type / answerability / authority_scope / cross_document_needed
  are human calls, and an agent grading them would silently turn judgement into "fact".

Once any row is filled, re-running this script recomputes the metrics and the classification for
those rows without touching the retrieval engine - that is the whole point of the raw/evaluation
split. Rows still PENDING are reported as NOT REVIEWED rather than counted as irrelevant.

Metrics per query (only over reviewed rows):
  Document-family Recall@8        - the target family appears in the final window
  Authoritative Evidence Recall@8/@20 - a relevance-3 row inside that window
  Answerable Evidence Recall@8/@20   - a FULL-answerability row inside that window
  best authoritative rank / best FULL rank - NONE when absent
"""

from __future__ import annotations

import json
import pathlib

JUDGMENT_FIELDS = ("relevance", "evidence_type", "answerability", "authority_scope", "cross_document_needed")
TARGET = {"A": "第2部分", "C": "第3部分"}
GRADES = {3: "AUTHORITATIVE", 2: "SUPPORTING", 1: "CONTEXT_ONLY", 0: "IRRELEVANT"}


def part_of(name: str) -> str:
    for marker in ("第1部分", "第2部分", "第3部分"):
        if marker in name:
            return marker
    return "other-document"


def candidates(entry: dict, limit: int = 20) -> list:
    """Final-window rows first, then the hybrid ranks beyond the cut, in rank order."""
    final = (entry["stages"].get("stage6_final_context") or {}).get("chunks") or []
    hybrid = (entry["stages"].get("stage3_hybrid") or {}).get("chunks") or []
    seen = set()
    rows = []
    for fact in final + hybrid:
        key = fact["chunk_id"]
        if key in seen:
            continue
        seen.add(key)
        rows.append({"stage": "final" if fact in final else "hybrid_pool", **fact})
        if len(rows) >= limit:
            break
    return rows


def load_judgments() -> dict:
    path = pathlib.Path("ac_evidence_judgment.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def template(data: dict) -> dict:
    out = {}
    for tag, entry in data["queries"].items():
        out[tag] = {}
        for fact in candidates(entry):
            out[tag][fact["chunk_id"]] = {field: "PENDING" for field in JUDGMENT_FIELDS}
    return out


def reviewed(row: dict) -> bool:
    return all(value != "PENDING" for value in row.values())


def main() -> int:
    data = json.loads(pathlib.Path("ac_trace_raw.json").read_text(encoding="utf-8"))
    judgments = load_judgments()
    if not judgments:
        pathlib.Path("ac_evidence_judgment.json").write_text(json.dumps(template(data), ensure_ascii=False, indent=1), encoding="utf-8")
        judgments = template(data)

    lines: list[str] = []
    add = lines.append
    add("# A/C human evidence review")
    add("")
    add("* source: `ac_trace_raw.json` (immutable, OBSERVED) + `ac_evidence_judgment.json` (semantic fields)")
    add("* every `relevance` / `evidence_type` / `answerability` / `authority_scope` / `cross_document_needed` cell is a HUMAN call; rows still `PENDING` are reported as NOT REVIEWED, never as irrelevant")
    add("* the blank-template signal below is DERIVED from the host canonical detector and is NOT a relevance verdict")
    add("")

    profiles = {}
    for tag, entry in data["queries"].items():
        target = TARGET[tag]
        rows = candidates(entry)
        judged = judgments.get(tag, {})
        add(f"## Query {tag}: `{entry['query']}`")
        add("")
        add(f"* query tokens (OBSERVED): `{entry['query_tokens']}`")
        add("")
        add("| rank | stage | chunk | document | Part | score | blank_template (DERIVED) | relevance | evidence_type | answerability | authority_scope | cross_document_needed |")
        add("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for fact in rows:
            marks = judged.get(fact["chunk_id"], {field: "PENDING" for field in JUDGMENT_FIELDS})
            add(
                f"| {fact['rank']} | {fact['stage']} | {fact['chunk_id'][:14]} | {fact['document_name'][:22]} | {part_of(fact['document_name'])} | {fact['score']:.4f} | "
                f"{'UNKNOWN' if 'content_with_weight' not in fact else 'false'} | {marks['relevance']} | {marks['evidence_type']} | {marks['answerability']} | {marks['authority_scope']} | {marks['cross_document_needed']} |"
            )
        add("")

        # metrics over REVIEWED rows only
        def reviewable(limit):
            return [fact for fact in rows[:limit] if reviewed(judged.get(fact["chunk_id"], {}))]

        window8, window20 = reviewable(8), reviewable(20)
        auth8 = [fact for fact in window8 if judged[fact["chunk_id"]]["relevance"] == 3]
        auth20 = [fact for fact in window20 if judged[fact["chunk_id"]]["relevance"] == 3]
        full8 = [fact for fact in window8 if judged[fact["chunk_id"]]["answerability"] == "FULL"]
        full20 = [fact for fact in window20 if judged[fact["chunk_id"]]["answerability"] == "FULL"]
        family8 = [fact for fact in window8 if part_of(fact["document_name"]) == target]
        beyond = [fact for fact in rows if fact["stage"] == "hybrid_pool" and fact["rank"] > 8]
        better_beyond = [fact for fact in beyond if reviewed(judged.get(fact["chunk_id"], {})) and (judged[fact["chunk_id"]]["relevance"] == 3 or judged[fact["chunk_id"]]["answerability"] == "FULL")]

        add("### Evidence recall (REVIEWED rows only; unreviewed rows are excluded, not counted as failures)")
        add("")
        add(f"* Document-family Recall@8 (`{target}` present in the final window): {'PASS' if family8 else ('FAIL' if window8 else 'NOT REVIEWED')}")
        add(f"* Authoritative Evidence Recall@8 / @20: {'PASS' if auth8 else 'FAIL'} / {'PASS' if auth20 else 'FAIL'}  (reviewed {len(window8)} of 8, {len(window20)} of 20)")
        add(f"* Answerable Evidence Recall@8 / @20: {'PASS' if full8 else 'FAIL'} / {'PASS' if full20 else 'FAIL'}")
        add(f"* best authoritative rank: {min((fact['rank'] for fact in auth20), default='NONE')}; best FULL-answerability rank: {min((fact['rank'] for fact in full20), default='NONE')}")
        add(f"* better evidence already retrieved but BEYOND the cut (hybrid ranks 9-20): {[fact['chunk_id'][:12] for fact in better_beyond] or 'none reviewed as such'}")
        add("")

        profile = {
            "document_family_recall": "PASS" if family8 else ("FAIL" if window8 else "NOT REVIEWED"),
            "authoritative_recall_at_8": "PASS" if auth8 else ("FAIL" if window8 else "NOT REVIEWED"),
            "authoritative_recall_at_20": "PASS" if auth20 else ("FAIL" if window20 else "NOT REVIEWED"),
            "answerable_recall_at_8": "PASS" if full8 else ("FAIL" if window8 else "NOT REVIEWED"),
            "answerable_recall_at_20": "PASS" if full20 else ("FAIL" if window20 else "NOT REVIEWED"),
            "best_authoritative_rank": min((fact["rank"] for fact in auth20), default="NONE"),
            "best_full_rank": min((fact["rank"] for fact in full20), default="NONE"),
            "better_evidence_beyond_cutoff": [fact["chunk_id"] for fact in better_beyond],
            "cross_document_needed": sorted({judged[fact["chunk_id"]]["cross_document_needed"] for fact in window20}) if window20 else ["NOT REVIEWED"],
        }
        profiles[tag] = profile
        add("```text")
        add(f"Query {tag}")
        for key, value in profile.items():
            add(f"{key}: {value}")
        add("```")
        add("* root cause: **NOT DETERMINED** until the semantic rows above are filled (a structural classification only becomes defensible with judged evidence)")
        add("")

    add("## Root-cause classification (only from judged evidence)")
    add("")
    if all(all(not reviewed(row) for row in judgments.get(tag, {}).values()) for tag in data["queries"]):
        add("**NOT DETERMINED** for both queries: no semantic row has been filled yet, so no")
        add("classification of the form candidate-generation / evidence-ranking / cutoff /")
        add("cross-document / source-document-insufficiency / blank-template-dominance is supportable.")
    else:
        add("See the per-query profiles above; each classification must quote the rank and the judged evidence it rests on.")
    add("")
    add("## Observed failure mechanism (no implementation proposed)")
    add("")
    add("* nothing is asserted yet; the standing rules forbid proposing a fix this round.")
    pathlib.Path("ac_human_evidence_review.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:8]))
    print("wrote ac_human_evidence_review.md and ac_evidence_judgment.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
