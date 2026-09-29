"""Offline gates for the QGDW ranking/selection policy repair.

PURE FUNCTIONS ONLY: no Elasticsearch, no retrieval, no network, no datastore. The gates call the
DEPLOYED `rag.retrieval.rerank` units directly:

    apply_rank_adjustments(pool, policy)   the ordering pass
    select_context(ordered, top_n, policy) the context cut

Two families of input:

* the FROZEN captured 45-chunk pool (`trace_qgdw_now.json`), whose structure - per-chunk similarity,
  table/prose, document - comes from the capture. Bodies are synthesised because the capture keeps no
  content; every table is built NON-HOLLOW, which is the assumption under which the replayed selection
  reproduced the captured window exactly, and the CONTROL chunk is independently measured non-hollow.
* SYNTHETIC pools for the two policy controls (hollow-heavy, cap-exhausted).

The policy is the one the deployed run actually used for the incident question (recorded in the
capture), with `question_values` empty - measured fact, not an assumption.

Gate polarity: every test in this file states REQUIRED behaviour, so the deployed code FAILS the RED
ones and the repaired code PASSES all of them. Nothing here inspects chunk ids for behaviour; the
id-agnostic gate re-runs a pool with renamed ids and requires an identical outcome.
"""
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

import pytest

from rag.retrieval import rerank
from rag.retrieval.rerank import DiversityPolicy, apply_rank_adjustments, select_context

POOL_FILE = pathlib.Path("/gates/trace_qgdw_now.json")
CONTROL = "b5aaf72bcd33d44a"
TARGET = "d1d75672f2dbc333"
TOP_N = 12
TABLE_CAP = 6

INCIDENT = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"


# --------------------------------------------------------------------------------------------- helpers
def table_body(caption, filled, empty, result=""):
    cells = "".join(f"<td>v{i}</td>" for i in range(filled))
    blanks = "".join("<td></td>" for _ in range(empty))
    return f"<table><caption>{caption}</caption><tr><th>项目</th><th>值</th></tr><tr>{cells}{blanks}</tr>{result}</table>"


def chunk(cid, doc, similarity, is_table, *, hollow=False, caption=None):
    """A passage whose predicates the deployed code can evaluate from real markup."""
    if not is_table:
        body = f"5.3.4 条款正文 {cid}：内衬层厚度应不小于 1.5mm，外被层应光滑无缺陷。"
        return {"chunk_id": cid, "doc_id": doc, "docnm_kwd": doc, "doc_type_kwd": "text",
                "content_with_weight": body, "similarity": similarity, "retrieval_routes": []}
    if hollow:
        body = table_body(caption or f"表 {cid} 参数表", filled=0, empty=6)
    else:
        body = table_body(caption or f"表 {cid} 技术参数表", filled=5, empty=1)
    return {"chunk_id": cid, "doc_id": doc, "docnm_kwd": doc, "doc_type_kwd": "table",
            "content_with_weight": body, "similarity": similarity, "retrieval_routes": []}


def deployed_policy():
    """The policy the deployed run used for the incident question, read from the capture."""
    recorded = json.loads(POOL_FILE.read_text(encoding="utf-8"))["trace"]["selection"][0]["policy"]
    return DiversityPolicy(
        min_prose=recorded["min_prose"],
        max_table_share=recorded["max_table_share"],
        table_penalty=rerank.TABLE_PENALTY,
        max_auxiliary_document_share=recorded["max_auxiliary_document_share"],
        core_document_boost=rerank.CORE_DOCUMENT_BOOST,
        core_documents=frozenset(recorded["core_documents"]),
        max_document_share=recorded["max_document_share"],
        compared_documents=frozenset(recorded["compared_documents"]),
        question_values=frozenset(),
    )


def frozen_pool():
    """Frozen capture -> real chunk dicts, in the PRE-adjustment (similarity) order.

    The capture proves the pre-adjustment pool order IS the similarity order (target 27 / control 8
    in both), so this is the faithful input to the pipeline: the adjustment pass is then applied by
    the code under test, not pre-applied by the fixture. Feeding the post-adjustment order instead
    would run the adjustment twice and move passages off the deployed positions.
    """
    profile = json.loads(POOL_FILE.read_text(encoding="utf-8"))["trace"]["selection"][0]["ordered_profile"]
    ordered = sorted(profile, key=lambda e: (-e["similarity"], e["position"]))
    return [chunk(e["chunk_id"], e["document_key"], e["similarity"], e["is_table"]) for e in ordered]


def selected_ids(ordered, policy, top_n=TOP_N):
    chosen = select_context(apply_rank_adjustments(list(ordered), policy), top_n, policy)
    return [c["chunk_id"] for c in chosen]


def count_tables(pool, ids):
    by_id = {c["chunk_id"]: c for c in pool}
    tables = sum(1 for i in ids if by_id[i]["doc_type_kwd"] == "table")
    return tables, len(ids) - tables


# ------------------------------------------------------------------------- 1. RANKING RED
def test_ranking_non_hollow_table_is_not_demoted_solely_for_type():
    """REQUIRED: a non-hollow table and an identical prose passage keep the SAME ordering value."""
    doc = "28668474ba1b11f1be9555eabe501d5b"
    policy = deployed_policy()
    prose = chunk("prose-x", doc, 0.50, is_table=False)
    table = chunk("table-x", doc, 0.50, is_table=True, hollow=False)
    ordered = apply_rank_adjustments([prose, table], policy)
    scores = {c["chunk_id"]: c["rank_score"] for c in ordered}
    assert scores["table-x"] == pytest.approx(scores["prose-x"]), (
        f"non-hollow table demoted purely for being a table: {scores}")
    assert ordered[0]["chunk_id"] in {"prose-x", "table-x"}


def test_ranking_hollow_table_still_demoted():
    """REQUIRED: the hollow-quality penalty survives - a blank grid is not evidence."""
    doc = "28668474ba1b11f1be9555eabe501d5b"
    policy = deployed_policy()
    hollow = chunk("hollow-x", doc, 0.50, is_table=True, hollow=True)
    prose = chunk("prose-y", doc, 0.50, is_table=False)
    scores = {c["chunk_id"]: c["rank_score"] for c in apply_rank_adjustments([hollow, prose], policy)}
    assert scores["hollow-x"] < scores["prose-y"]
    assert scores["hollow-x"] == pytest.approx(scores["prose-y"] * rerank.HOLLOW_TABLE_PENALTY)


def test_ranking_core_document_boost_and_value_factors_preserved():
    """REQUIRED: core boost still applies; value factors still reachable when the question HAS values."""
    core = "28668474ba1b11f1be9555eabe501d5b"
    other = "otherdoc"
    base = DiversityPolicy(core_document_boost=rerank.CORE_DOCUMENT_BOOST, core_documents=frozenset({core}))
    scores = {c["chunk_id"]: c["rank_score"] for c in apply_rank_adjustments(
        [chunk("core-p", core, 0.50, is_table=False), chunk("other-p", other, 0.50, is_table=False)], base)}
    assert scores["core-p"] == pytest.approx(scores["other-p"] * rerank.CORE_DOCUMENT_BOOST)


# ------------------------------------------------------------------------- 2. SELECTION RED
def test_selection_frozen_pool_admits_a_top_scoring_table():
    """REQUIRED: with a table cap > 0, a table inside the score top 12 must be selectable."""
    policy = deployed_policy()
    pool = frozen_pool()
    ids = selected_ids(pool, policy)
    tables, prose = count_tables(pool, ids)
    assert TABLE_CAP > 0
    assert tables >= 1, f"table_cap={TABLE_CAP} but chosen_tables=0 (prose={prose})"


def test_selection_frozen_pool_selects_the_control():
    """REQUIRED (primary acceptance): the CONTROL passage enters the final context."""
    policy = deployed_policy()
    pool = frozen_pool()
    ids = selected_ids(pool, policy)
    assert CONTROL in ids, f"CONTROL not selected; window={ids}"
    assert len(ids) == TOP_N, f"window size {len(ids)} != {TOP_N}"


def test_selection_window_size_is_final_top_n():
    policy = deployed_policy()
    pool = frozen_pool()
    assert len(selected_ids(pool, policy)) == TOP_N


def test_selection_table_cap_enforced_on_frozen_pool():
    policy = deployed_policy()
    pool = frozen_pool()
    tables, _ = count_tables(pool, selected_ids(pool, policy))
    assert tables <= TABLE_CAP, f"chosen_tables={tables} exceeds cap {TABLE_CAP}"


def test_selection_prose_floor_preserved_on_frozen_pool():
    policy = deployed_policy()
    pool = frozen_pool()
    _, prose = count_tables(pool, selected_ids(pool, policy))
    assert prose >= policy.min_prose, f"chosen_prose={prose} below floor {policy.min_prose}"


def test_selection_table_inside_top12_is_not_superseded_by_lower_scoring_prose():
    """REQUIRED: the defect signature - a top-12 table excluded while weaker prose is chosen."""
    policy = deployed_policy()
    pool = frozen_pool()
    ordered = apply_rank_adjustments(list(pool), policy)
    ids = [c["chunk_id"] for c in select_context(ordered, TOP_N, policy)]
    by_id = {c["chunk_id"]: c for c in ordered}
    chosen_tables = [i for i in ids if by_id[i]["doc_type_kwd"] == "table"]
    chosen_prose_sims = [by_id[i]["similarity"] for i in ids if by_id[i]["doc_type_kwd"] == "text"]
    best_table_rank = next((n for n, c in enumerate(ordered, 1) if c["doc_type_kwd"] == "table"), None)
    assert best_table_rank is not None and best_table_rank <= TOP_N, "fixture precondition"
    assert chosen_tables, (
        f"best table at rank {best_table_rank} (sim={ordered[best_table_rank-1]['similarity']:.6f}) "
        f"excluded while prose down to sim={min(chosen_prose_sims):.6f} was chosen")


# ------------------------------------------------------------------------- 3. NEGATIVE CONTROL
def test_negative_control_low_score_passage_is_not_forced_in():
    """REQUIRED: with no quota pressure, a passage below the window's score band stays out.

    The target's OWN recorded similarity is used, in its own document, against twelve higher-scoring
    prose passages in twelve other documents, so neither the table cap nor a document cap binds and
    selection follows score alone. This is what proves the repair preserves evidence fairly instead of
    targeting one chunk; the frozen-pool composition (where quota pressure legitimately deepens the
    fill) is reported separately by `qgdw_frozen_pool_after.py`, not asserted here.
    """
    policy = deployed_policy()
    pool = [chunk(f"prose-{i}", f"doc-{i}", 0.90 - i * 0.001, is_table=False) for i in range(12)]
    pool.append(chunk(TARGET, "doc-target", 0.4572200467994867, is_table=True))
    ids = selected_ids(pool, policy)
    assert TARGET not in ids, "the unrecoverable target was force-included with no score support"
    assert len(ids) == TOP_N


def test_selection_is_id_agnostic():
    """REQUIRED: renaming every chunk id must not change the outcome (no id-specific behaviour)."""
    policy = deployed_policy()
    pool = frozen_pool()
    renamed, mapping = [], {}
    for n, c in enumerate(pool):
        clone = dict(c)
        clone["chunk_id"] = f"renamed-{n:03d}"
        mapping[c["chunk_id"]] = clone["chunk_id"]
        renamed.append(clone)
    before = selected_ids(pool, policy)
    after = selected_ids(renamed, policy)
    assert [mapping[i] for i in before] == after, "selection depends on chunk identity, not on score/structure"


# ------------------------------------------------------------------------- 4. SYNTHETIC POLICY CONTROLS
def test_control_A_hollow_heavy_pool_tables_suppressible():
    """A. A pool of hollow grids must not take the window from prose.

    Every passage sits in its OWN document so the document quotas cannot bind: the only rules under
    test here are the hollow penalty and the table cap.
    """
    policy = deployed_policy()
    pool = [chunk(f"hollow-{i}", f"hdoc-{i}", 0.90 - i * 0.001, is_table=True, hollow=True) for i in range(12)]
    pool += [chunk(f"prose-{i}", f"pdoc-{i}", 0.80 - i * 0.001, is_table=False) for i in range(12)]
    ids = selected_ids(pool, policy)
    tables, prose = count_tables(pool, ids)
    assert prose >= policy.min_prose, "hollow grids crowded out the prose floor"
    assert tables <= TABLE_CAP
    assert len(ids) == TOP_N


def test_control_B_cap_exhausted_pool_rejects_further_high_score_tables():
    """B. Once the table cap is reached, further high-scoring tables must be rejected.

    One document per passage, so the table cap is the only constraint that can bind.
    """
    policy = deployed_policy()
    pool = [chunk(f"table-{i}", f"tdoc-{i}", 0.99 - i * 0.001, is_table=True) for i in range(10)]
    pool += [chunk(f"prose-{i}", f"qdoc-{i}", 0.50 - i * 0.001, is_table=False) for i in range(10)]
    ids = selected_ids(pool, policy)
    tables, prose = count_tables(pool, ids)
    assert tables == TABLE_CAP, f"chosen_tables={tables} != cap {TABLE_CAP}"
    assert len(ids) == TOP_N
    ranked = [c["chunk_id"] for c in apply_rank_adjustments(list(pool), policy)]
    excluded_tables = [i for i in ranked if i.startswith("table-") and i not in ids]
    assert excluded_tables, "fixture precondition: some table must be beyond the cap"


def test_no_minimum_table_quota():
    """A pool whose tables all score below the window's prose must return ZERO tables.

    One document per passage, so score alone decides - this rules out any hidden minimum table quota.
    """
    policy = deployed_policy()
    pool = [chunk(f"prose-{i}", f"rdoc-{i}", 0.90 - i * 0.001, is_table=False) for i in range(20)]
    pool += [chunk(f"table-{i}", f"sdoc-{i}", 0.10 - i * 0.001, is_table=True) for i in range(6)]
    ids = selected_ids(pool, policy)
    tables, prose = count_tables(pool, ids)
    assert tables == 0, f"tables forced in with no score support: {tables}"


# ------------------------------------------------------------------------- 5. FROZEN PARAMETERS
def test_frozen_parameter_values_unchanged():
    assert rerank.TABLE_PENALTY == 0.85
    assert rerank.HOLLOW_TABLE_PENALTY == 0.6
    assert rerank.VALUE_LIST_PENALTY == 0.8
    assert rerank.VALUE_PAIRING_BOOST == 1.3
    assert rerank.CORE_DOCUMENT_BOOST == 1.15
    assert rerank.MAX_TABLE_SHARE == 0.5
    assert rerank.MIN_PROSE_PASSAGES == 4
    assert rerank.MAX_AUXILIARY_DOCUMENT_SHARE == 0.4
    assert rerank.MAX_COMPARED_DOCUMENT_SHARE == 0.5
    assert rerank.MAX_HOLLOW_TABLE_PER_DOCUMENT_SHARE == 0.25
    assert rerank.MAX_TABLE_FAMILY_PARTS == 4
    assert rerank.DEFAULT_FINAL_TOP_N == 8


def test_policy_produced_for_a_question_is_unchanged():
    """The policy CONSTRUCTOR must keep producing the same field values (predicate change only)."""
    policy = DiversityPolicy.for_question(INCIDENT, [])
    assert policy.min_prose == 4
    assert policy.max_table_share == 0.5
    assert policy.table_penalty == 0.85
    assert policy.question_values == frozenset()


def test_compared_document_cap_unchanged():
    policy = deployed_policy()
    assert policy.max_document_share == 0.5
    assert len(policy.compared_documents) >= 2
    pool = []
    for doc in sorted(policy.compared_documents):
        pool += [chunk(f"{doc[:4]}-t{i}", doc, 0.90 - i * 0.001, is_table=True) for i in range(8)]
    pool += [chunk(f"aux-p{i}", "auxdoc", 0.50 - i * 0.001, is_table=False) for i in range(8)]
    ids = selected_ids(pool, policy)
    per_doc = {}
    by_id = {c["chunk_id"]: c for c in pool}
    for i in ids:
        per_doc[by_id[i]["doc_id"]] = per_doc.get(by_id[i]["doc_id"], 0) + 1
    assert max(per_doc.values()) <= 6, f"compared-document cap breached: {per_doc}"


# =================================================================================================
# COMPARED-DOCUMENT RESERVATION CONTRACT
#
# `select_context` documents step 1b as "one slot per document a COMPARATIVE question names" and its
# own comment says the reservation "changes WHICH passage the reservation takes, never how many are
# reserved". The implementation iterated a list with ONE ENTRY PER COMPARED CHUNK, so a document with n
# compared chunks received n reservation attempts and was filled up to its document CAP.
#
# The fixtures below ISOLATE the reservation: the compared documents hold only passages that score
# BELOW the window's band, so the score fill cannot reach them, and any compared passage in the window
# can only have come from the reservation stage.
# =================================================================================================
COMPARED_A, COMPARED_B = "docA", "docB"
CORE_C, CORE_D = "docC", "docD"


def reservation_policy():
    """Comparison active: compared = {A, B}; C and D are core (so no auxiliary cap) and high-scoring."""
    return DiversityPolicy(
        min_prose=4, max_table_share=0.5, table_penalty=rerank.TABLE_PENALTY,
        max_auxiliary_document_share=0.4, core_document_boost=rerank.CORE_DOCUMENT_BOOST,
        core_documents=frozenset({CORE_C, CORE_D}),
        max_document_share=0.5, compared_documents=frozenset({COMPARED_A, COMPARED_B}),
        question_values=frozenset(),
    )


def reservation_fixture(a_chunks=10, a_top=0.30, a_step=0.01, duplicate_extras=0):
    """A/B compared, A scoring far below the window; C/D carry the high-scoring prose."""
    pool = [chunk(f"a-{i}", COMPARED_A, a_top - i * a_step, is_table=False) for i in range(a_chunks)]
    pool += [chunk(f"a-dup-{i}", COMPARED_A, a_top - i * a_step, is_table=False) for i in range(duplicate_extras)]
    pool.append(chunk("b-0", COMPARED_B, 0.99, is_table=False))
    pool += [chunk(f"c-{i}", CORE_C, 0.95 - i * 0.01, is_table=False) for i in range(8)]
    pool += [chunk(f"d-{i}", CORE_D, 0.87 - i * 0.01, is_table=False) for i in range(8)]
    return pool


def per_document(pool, ids):
    by_id = {c["chunk_id"]: c for c in pool}
    counts = {}
    for i in ids:
        counts[by_id[i]["doc_id"]] = counts.get(by_id[i]["doc_id"], 0) + 1
    return counts


def test_compared_document_receives_at_most_one_reservation_slot():
    """REQUIRED: step 1b grants ONE slot per compared document, not one per compared chunk."""
    policy = reservation_policy()
    pool = reservation_fixture()
    counts = per_document(pool, selected_ids(pool, policy))
    from_a = counts.get(COMPARED_A, 0)
    assert from_a <= 1, (
        f"compared document A took {from_a} slots; the contract grants one reservation per document "
        "and A's passages score far below the window, so the rest can only be repeated reservations")


def test_duplicate_compared_chunks_do_not_multiply_reservation_attempts():
    """REQUIRED: adding more chunks to a compared document must not add reservation attempts."""
    policy = reservation_policy()
    small = per_document(reservation_fixture(a_chunks=10), selected_ids(reservation_fixture(a_chunks=10), policy))
    large_pool = reservation_fixture(a_chunks=20, duplicate_extras=0)
    large = per_document(large_pool, selected_ids(large_pool, policy))
    assert large.get(COMPARED_A, 0) <= 1, (
        f"20 compared chunks in A produced {large.get(COMPARED_A, 0)} slots; "
        "reservation attempts must not scale with the chunk count")
    assert small.get(COMPARED_A, 0) == large.get(COMPARED_A, 0), (
        f"A's slots changed with its chunk count: {small.get(COMPARED_A, 0)} -> {large.get(COMPARED_A, 0)}")


def test_minimal_case_at_most_one_passage_per_compared_document():
    """Minimal synthetic case: A has many compared chunks, B has at least one -> <= 1 each."""
    policy = reservation_policy()
    pool = reservation_fixture(a_chunks=25, duplicate_extras=5)
    counts = per_document(pool, selected_ids(pool, policy))
    assert counts.get(COMPARED_A, 0) <= 1, f"A took {counts.get(COMPARED_A, 0)}, expected <= 1"
    assert counts.get(COMPARED_B, 0) == 1, f"B took {counts.get(COMPARED_B, 0)}, expected exactly 1"


def test_document_cap_remains_a_cap_not_a_reservation_count():
    """REQUIRED: the document cap still bounds the FILL; it is not converted into a reservation quota."""
    policy = reservation_policy()
    pool = reservation_fixture()
    counts = per_document(pool, selected_ids(pool, policy))
    cap = 6  # ceil(12 * max_document_share 0.5)
    assert counts.get(COMPARED_A, 0) <= 1, "the reservation must not fill A up to its cap"
    assert counts.get(CORE_C, 0) <= cap and counts.get(CORE_D, 0) <= cap, (
        f"document cap not enforced as a cap: {counts}")


def test_reservation_stage_does_not_saturate_the_frozen_window():
    """REQUIRED: with <= 1 reservation per compared document the score fill must still execute."""
    policy = deployed_policy()
    pool = frozen_pool()
    ids = selected_ids(pool, policy)
    counts = per_document(pool, ids)
    compared = set(policy.compared_documents)
    assert len(ids) == TOP_N, f"window {len(ids)} != {TOP_N}"
    assert any(d not in compared for d in counts), (
        f"every slot came from a compared document: {counts} - the fill never executed")


def test_frozen_pool_control_selected_and_target_not_reserved_in():
    """REQUIRED: CONTROL selected by score; TARGET must not enter through repeated reservation."""
    policy = deployed_policy()
    pool = frozen_pool()
    ids = selected_ids(pool, policy)
    assert CONTROL in ids, f"CONTROL not selected; window={ids}"
    assert TARGET not in ids, f"TARGET entered the window: {ids}"
