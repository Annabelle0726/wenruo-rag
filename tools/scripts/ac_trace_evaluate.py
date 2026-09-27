"""Host-side evaluation of the deployed trace: annotate with explicit provenance.

Reads the immutable `ac_trace_raw.json` (produced by the domain-blind deployed tracer) and
writes `ac_trace_evaluation.md`. It never re-runs retrieval, and it never rewrites the raw
artifact - that is the point of the split: retrieval execution and relevance judgement are
separate, so a future blank-template detector or rubric can re-evaluate the SAME trace.

Every annotated value carries its provenance:

    OBSERVED            - read out of the trace, produced by the deployed engine
    DERIVED(<source>)   - computed here from the observed facts (host canonical code)
    HUMAN_JUDGMENT      - a person's call; left PENDING where nobody has made it yet

The canonical blank-template detector is CALLED, never reimplemented; a chunk it cannot judge
is reported UNKNOWN rather than given a fallback verdict.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from rag.nlp import retrieval_projection as rp  # canonical detector, host side
from rag.nlp.retrieval_projection import resolve_family  # canonical family resolver


def load() -> dict:
    return json.loads(pathlib.Path("ac_trace_raw.json").read_text(encoding="utf-8"))


def derived_blank_template(fact: dict) -> str:
    """true / false / UNKNOWN - via the canonical detector, never a local re-implementation."""
    text = fact.get("content_with_weight")
    if text is None:
        return "UNKNOWN (beyond the text-capture limit)"
    try:
        return "true" if rp.is_blank_response_template({"content_with_weight": text, "doc_type_kwd": fact.get("doc_type_kwd")}) else "false"
    except Exception:  # noqa: BLE001 - an unusable detector is reported, not worked around
        return "UNKNOWN (detector raised)"


def derived_family(document_name: str) -> dict:
    family = resolve_family(designation=None, name=document_name)
    return {"family_id": family.family_id or "?", "part_no": family.part_no, "document_role": family.document_role, "source": "DERIVED(host resolve_family)"}


def observed_part(document_name: str) -> str:
    for marker in ("第1部分", "第2部分", "第3部分"):
        if marker in document_name:
            return marker
    return "other-document"


def stage_facts(entry: dict, stage: str) -> list:
    return (entry["stages"].get(stage) or {}).get("chunks") or []


def first_rank(facts, part: str):
    for fact in facts:
        if observed_part(fact["document_name"]) == part:
            return fact
    return None


def main() -> int:
    data = load()
    lines: list[str] = []
    add = lines.append
    add("# A/C trace evaluation (provenance-tagged)")
    add("")
    add("* source artifact: `ac_trace_raw.json` (immutable; produced by the deployed tracer)")
    add(f"* configuration: {json.dumps(data['config'], ensure_ascii=False)}")
    add(f"* embedding model id (OBSERVED): `{data.get('embedding_model_id')}`")
    add(f"* deployed `Dealer.retrieval` parameters (OBSERVED): `{data.get('deployed_retrieval_signature')}`")
    add(f"* standard-number probe tokens (OBSERVED): `{data['standard_no_probe']['tokens']}`")
    add("")
    add("## Superseded / Invalidated Findings")
    add("")
    add("The following conclusions were reached with a HOST-side benchmark and are hereby")
    add("**INVALIDATED** by the deployed trace. They were artifacts of how the host benchmark")
    add("constructed its call, not behaviour of the deployed engine:")
    add("")
    add("* \"Query A fails lexical recall\" - INVALIDATED. Deployed: Part 2 holds 32 of the lexical top 50.")
    add("* \"Part 2 is absent from the Top-10 / Top-50\" - INVALIDATED. Deployed: Part 2 is present and dominant.")
    add("* \"other-document parameter tables (`4 标准技术参数表`, `5 组件材料配置表`) own the candidate pool\" -")
    add("  INVALIDATED for the deployed engine: other-document chunks are **0** of the top 50 for Query A.")
    add("* \"wrong-document lexical collision\" as an A/C root cause - INVALIDATED as a candidate-level claim.")
    add("")
    add("Consequently no root-cause classification from that period may be carried forward, and the")
    add("Generalization Risk table stays empty until human relevance review exists.")
    add("")
    add("## Benchmark Trust Boundary")
    add("")
    add("| layer | what it may be used for | what it may NOT be used for |")
    add("|---|---|---|")
    add("| Synthetic / unit tests | mechanism correctness (parser, normalisation, projection, convergence) | stating anything about real retrieval behaviour |")
    add("| **Host benchmark** | **development-time auxiliary diagnosis only** | **any root-cause claim about production retrieval** |")
    add("| **Controlled deployed trace** | **the basis for statements about real retrieval behaviour** | semantic relevance (it holds no judgement) |")
    add("| Human-reviewed corpus | semantic relevance | generalisation |")
    add("| Holdout corpus | generalisation | mechanism proof |")
    add("")

    for tag, entry in data["queries"].items():
        add(f"## Query {tag}: `{entry['query']}`")
        add("")
        add(f"* query tokens (OBSERVED): `{entry['query_tokens']}`")
        add("")
        add("### Stage summary (all counts OBSERVED)")
        add("")
        add("| stage | total | returned | 第1部分 | 第2部分 | 第3部分 | other-document |")
        add("|---|---|---|---|---|---|---|")
        for stage in ("stage1_lexical_only", "stage2_dense_only", "stage3_hybrid", "stage6_final_context"):
            body = entry["stages"].get(stage) or {}
            if not body.get("chunks") and "returned" not in body:
                add(f"| {stage} | {body.get('status', 'NOT_SEPARATELY_OBSERVABLE')} | | | | | |")
                continue
            counts = {key: 0 for key in ("第1部分", "第2部分", "第3部分", "other-document")}
            for fact in body["chunks"]:
                counts[observed_part(fact["document_name"])] += 1
            add(f"| {stage} | {body.get('total')} | {body.get('returned')} | {counts['第1部分']} | {counts['第2部分']} | {counts['第3部分']} | {counts['other-document']} |")
        add("")
        for stage in ("stage4_reranker", "stage5_rank_adjustments"):
            body = entry["stages"].get(stage) or {}
            add(f"* `{stage}`: {body.get('status', 'OBSERVED')} {('- ' + str(body.get('reason'))) if body.get('reason') else ''}")
        moves = (entry["stages"].get("stage5_rank_adjustments") or {}).get("rank_moves") or []
        add(f"* stage 5 rank moves (OBSERVED): {moves[:8] if moves else 'none'}")
        add("")

        # Computed here because the tables below need them; the classification block reuses them.
        target = "第2部分" if tag == "A" else "第3部分"
        lex, hyb, final = stage_facts(entry, "stage1_lexical_only"), stage_facts(entry, "stage3_hybrid"), stage_facts(entry, "stage6_final_context")
        dense_facts = stage_facts(entry, "stage2_dense_only")
        lex_hit, hyb_hit, final_hit = first_rank(lex, target), first_rank(hyb, target), first_rank(final, target)
        dense_hit = first_rank(dense_facts, target)

        add("### Stage transition, by family (counts OBSERVED, Part from the document name)")
        add("")
        add("| family | lexical Top50 | dense Top50 | hybrid Top50 | final window |")
        add("|---|---|---|---|---|")
        for part in ("第1部分", "第2部分", "第3部分", "other-document"):
            counts = []
            for stage in ("stage1_lexical_only", "stage2_dense_only", "stage3_hybrid", "stage6_final_context"):
                facts = stage_facts(entry, stage)
                counts.append(sum(1 for fact in facts if observed_part(fact["document_name"]) == part))
            add(f"| {part} | {counts[0]} | {counts[1]} | {counts[2]} | {counts[3]} |")
        add("")
        add(f"* target family `{target}` rank per stage: lexical {lex_hit['rank'] if lex_hit else 'ABSENT'} -> dense {dense_hit['rank'] if dense_hit else 'ABSENT'} -> hybrid {hyb_hit['rank'] if hyb_hit else 'ABSENT'} -> final {final_hit['rank'] if final_hit else 'ABSENT'}")
        add("* Document-family recall (the family appears at all) and Authoritative-evidence recall (the passage states the requirement) are DIFFERENT questions: this artifact answers only the first; the second needs the human review table below.")
        add("")

        add("### Human review table (relevance and evidence type left PENDING_HUMAN_REVIEW)")
        add("")
        add("| rank (OBSERVED) | chunk | document (OBSERVED) | Part (OBSERVED) | family role (DERIVED) | score (OBSERVED) | blank_template (DERIVED) | evidence_type (PENDING_HUMAN_REVIEW) | relevance (PENDING_HUMAN_REVIEW) | snippet (OBSERVED) |")
        add("|---|---|---|---|---|---|---|---|---|---|")
        for fact in stage_facts(entry, "stage3_hybrid")[:20]:
            snippet = " ".join((fact.get("content_with_weight") or "").split())[:60]
            family = derived_family(fact["document_name"])
            add(f"| {fact['rank']} | {fact['chunk_id'][:14]} | {fact['document_name'][:24]} | {observed_part(fact['document_name'])} | {family['document_role']} | {fact['score']:.4f} | {derived_blank_template(fact)} | | | {snippet} |")
        add("")
        add("* `blank_template` is DERIVED from the host canonical detector and is NOT a relevance verdict: `true` does not imply relevance 0, and `UNKNOWN` means the detector could not judge that chunk.")

        add("### Factual token overlap (OBSERVED tokenizer output)")
        add("")
        for term, body in (entry.get("token_overlap") or {}).items():
            add(f"* `{term}` -> tokens `{body['term_tokens']}`")
            for sample in body["samples"][:3]:
                add(f"  - {sample['stage']} rank {sample['rank']} chunk {sample['chunk_id'][:14]}: overlap `{sample['overlap']}` coverage {sample['coverage']}")
        add("")

        # Root cause from OBSERVED transitions only.
        target = "第2部分" if tag == "A" else "第3部分"
        lex, hyb, final = stage_facts(entry, "stage1_lexical_only"), stage_facts(entry, "stage3_hybrid"), stage_facts(entry, "stage6_final_context")
        lex_hit, hyb_hit, final_hit = first_rank(lex, target), first_rank(hyb, target), first_rank(final, target)
        add("### Root-cause evidence (from stage transitions only)")
        add("")
        add(f"* {target} in lexical Top 50 (OBSERVED): rank {lex_hit['rank'] if lex_hit else 'ABSENT'}")
        add(f"* {target} in hybrid Top 50 (OBSERVED): rank {hyb_hit['rank'] if hyb_hit else 'ABSENT'}")
        add(f"* {target} in stage 6 window (OBSERVED): rank {final_hit['rank'] if final_hit else 'ABSENT'}")
        if not lex_hit:
            add("* classification: **lexical recall failure (candidate level)** is SUPPORTED for this query under this configuration")
        elif hyb_hit and lex_hit["rank"] < hyb_hit["rank"] and lex_hit["rank"] <= 10:
            add("* classification: **fusion suppression** is SUPPORTED (lexical rank better than hybrid rank)")
        elif final is not None and hyb_hit and not final_hit:
            add("* classification: **cutoff issue** is SUPPORTED (present in hybrid, absent from the final window)")
        else:
            add("* classification: NOT DETERMINED by the observed transitions alone")
        add("")

    add("## Generalization risk (proposed mechanisms only - nothing implemented)")
    add("")
    add("| Proposed mechanism | Failure it addresses | Generic? | Risk of 73286 overfit | Validation corpus needed |")
    add("|---|---|---|---|---|")
    add("| (none proposed) | no stage data has been turned into a mechanism yet; the evidence above is the input to that discussion | - | - | - |")
    add("")
    add("Nothing was fixed, tuned or re-run in this round, and no relevance grade was invented: the")
    add("`relevance` and `evidence type` columns are marked PENDING because no human has made that call")
    add("yet, and this evaluator will not guess on their behalf.")
    pathlib.Path("ac_trace_evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:6]))
    print("wrote ac_trace_evaluation.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
