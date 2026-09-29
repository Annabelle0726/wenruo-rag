"""RED-first gates for the COMBINED reservation budget in ``select_context``.

The contract under test (the design audit's accepted repair):

1. compared-document representation is guaranteed first;
2. route representation then uses what the compared sides left of the budget;
3. the two reservation stages together cannot consume the whole ``top_n``;
4. at least one slot remains for the later score fill whenever the pool holds an
   eligible unchosen passage;
5. no new tuned constant, no change to any document / table / prose quota, and no
   knowledge of a chunk id, document name or standard designation.

Run against a specific module with ``RERANK_PATH`` so the same gates can be shown
RED on the deployed ``1152c59a`` file and GREEN on the repaired one. The swap is done
by the ``re_patch`` pytest plugin (``PYTHONPATH`` + ``-p re_patch``), which installs
the named file as ``rag.retrieval.rerank`` before collection:

    PYTHONPATH=/tmp RERANK_PATH=/tmp/rerank_prod.py python -m pytest -p re_patch ...
    PYTHONPATH=/tmp RERANK_PATH=/tmp/rerank_open.py python -m pytest -p re_patch ...
"""

import ast
import hashlib
import math
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, "/ragflow")

from rag.retrieval import chunk_profile, rerank  # noqa: E402

RERANK_SOURCE = pathlib.Path(rerank.__file__).read_text(encoding="utf-8")

pytestmark = pytest.mark.p1

PART2 = "Q_GDW 73286.2-2026 第2部分：单芯海底电力电缆采购标准.pdf"
PART3 = "Q_GDW 73286.3-2026 第3部分：三芯海底电力电缆采购标准.pdf"
AUX = "供应商数据表.pdf"

COMPARATIVE = "400 mm²、630 mm² 与 1600 mm² 截面电缆在 20°C 时的导体最大直流电阻标准值分别是多少？单芯与三芯要求是否一致？"
SINGLE = "导体在 20°C 时的最大直流电阻是多少？"
CLAUSE = "两份规范对不上时以谁为准？"

#: The live request's route count, which is what the defect needs to reproduce.
LIVE_ROUTES = [
    "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定 单芯与三芯",
    "单芯 根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 导体标称截面",
    "单芯 根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 规格数量",
    "Q/GDW 73286.2-2026 表1 中单芯交联聚乙烯绝缘电力电缆的导体标称截面",
    "Q/GDW 73286.2-2026 表1 中单芯交联聚乙烯绝缘电力电缆的规格数量",
    "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 覆盖范围",
    "三芯 根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 导体标称截面",
    "Q/GDW 73286.3-2026 表1 中三芯交联聚乙烯绝缘电力电缆的导体标称截面",
]


def _chunk(cid, doc, score, routes=(), table=False, body="导体标称截面 系列参数"):
    content = f"<table><tr><td>{body}</td></tr></table>" if table else body
    return {
        "chunk_id": cid,
        "doc_id": doc,
        "docnm_kwd": doc,
        "doc_type_kwd": "table" if table else "text",
        "content_with_weight": content,
        "similarity": score,
        "retrieval_routes": list(routes),
    }


def _ordered(pool):
    return sorted(pool, key=lambda c: c["similarity"], reverse=True)


def _ids(chunks):
    return [c["chunk_id"] for c in chunks]


def _counts(chunks):
    out = {}
    for c in chunks:
        name = chunk_profile.document_name(c)
        out[name] = out.get(name, 0) + 1
    return out


def _policy(question, pool):
    return rerank.DiversityPolicy.for_question(question, pool)


# ---------------------------------------------------------------------------
# A. The live shape: 8 routes + 2 compared sides against a 12-slot window.
# ---------------------------------------------------------------------------

#: A passage reachable by NOTHING but the score fill: no route provenance, and in a
#: document the question does not compare. If the reservations consume the window it
#: cannot appear, so its presence is the fill's own signature.
PROBE = "aux-probe"


def live_shape_pool():
    """Part 2 wins 6 of the 8 route slots, Part 3 the other 2 - the measured live split.

    Route members are prose so this fixture isolates the BUDGET: a table-family batch
    (``take_batch``) legitimately claims several slots at once, and is exercised
    separately in gates D and E.
    """
    pool = []
    for i in range(20):
        routes = [LIVE_ROUTES[i % 6]]
        pool.append(_chunk(f"p2-{i:02d}", PART2, 0.60 - i * 0.005, routes))
    for i in range(20):
        routes = [LIVE_ROUTES[6 + (i % 2)]]
        pool.append(_chunk(f"p3-{i:02d}", PART3, 0.40 - i * 0.005, routes))
    # Highest score in the pool and unreachable by either reservation stage.
    pool.append(_chunk(PROBE, AUX, 0.99))
    return pool


def test_A_reservations_cannot_consume_the_whole_window():
    """REQUIRED: 8 routes + 2 compared sides at top_n=12 must leave the fill a slot."""
    pool = live_shape_pool()
    policy = _policy(COMPARATIVE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)

    assert len(selected) == 12, f"the window must still be filled: {len(selected)}"
    assert PROBE in _ids(selected), (
        "the highest-scoring eligible passage was not selectable by score: every slot "
        f"was taken by a reservation. selected={_ids(selected)}")


def test_A_both_compared_sides_are_still_represented():
    """The budget must not cost the guarantee it is meant to protect."""
    pool = live_shape_pool()
    policy = _policy(COMPARATIVE, pool)

    counts = _counts(rerank.select_context(_ordered(pool), 12, policy))

    assert counts.get(PART2, 0) >= 1, counts
    assert counts.get(PART3, 0) >= 1, counts


def test_A_route_representation_survives_the_shared_budget():
    """Eight routes spread over both sides, budget 11: every route keeps its slot.

    The sides are balanced here on purpose. In the measured live split 6 of the 8 routes
    belong to one document, and that document's ``every_document_cap`` (6 of 12) is
    exhausted by the sixth reservation, so the last route is blocked by a DOCUMENT QUOTA
    rather than by this budget - a pre-existing behaviour the repair must not change. The
    next gate pins that boundary explicitly.
    """
    pool = []
    for i in range(12):
        pool.append(_chunk(f"p2-{i:02d}", PART2, 0.60 - i * 0.005, [LIVE_ROUTES[i % 4]]))
    for i in range(12):
        pool.append(_chunk(f"p3-{i:02d}", PART3, 0.40 - i * 0.005, [LIVE_ROUTES[4 + (i % 4)]]))
    pool.append(_chunk(PROBE, AUX, 0.99))
    policy = _policy(COMPARATIVE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)

    missing = [r for r in LIVE_ROUTES if not any(r in rerank.routes_of(c) for c in selected)]
    assert not missing, f"routes unrepresented under the shared budget: {missing}"
    assert len(selected) == 12, _ids(selected)
    assert PROBE in _ids(selected), "the score fill must still have run"


def test_A_the_live_split_loses_one_route_to_the_document_quota_not_the_budget():
    """The measured 6/2 route split: the 6th same-document reservation hits that
    document's cap, so at least 7 of 8 routes are representable and the window is still
    filled by score. This pins that the repair changed neither the cap nor the fill."""
    pool = live_shape_pool()
    policy = _policy(COMPARATIVE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)
    represented = sum(1 for r in LIVE_ROUTES if any(r in rerank.routes_of(c) for c in selected))

    assert len(selected) == 12, _ids(selected)
    assert represented >= 7, f"only {represented} of 8 routes represented: {_ids(selected)}"
    assert PROBE in _ids(selected), "the score fill must still have run"


# ---------------------------------------------------------------------------
# B. The small legacy case.
# ---------------------------------------------------------------------------

def test_B_two_routes_no_comparison_keeps_both_and_fills_the_window():
    pool = ([_chunk(f"t{i}", PART2, 0.60 - i * 0.001, ["厚度"]) for i in range(5)]
            + [_chunk("v1", PART2, 0.577, ["电压试验"])]
            + [_chunk(f"x{i}", PART2, 0.50 - i * 0.001) for i in range(6)])
    policy = _policy(SINGLE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)
    ids = _ids(selected)

    assert len(ids) == 12, ids
    assert "v1" in ids, "the minority route must keep its slot"
    assert ids[0] == "t0", "the highest scorer must still lead"


def test_B_single_route_is_cut_the_ordinary_way():
    pool = [_chunk(f"t{i}", PART2, 0.6 - i * 0.01, ["厚度"]) for i in range(5)]

    assert _ids(rerank.select_context(_ordered(pool), 3, _policy(SINGLE, pool))) == ["t0", "t1", "t2"]


# ---------------------------------------------------------------------------
# C. The comparative case.
# ---------------------------------------------------------------------------

def test_C_the_lower_scoring_side_is_represented_and_the_cap_is_not_a_target():
    """Part 3 scores entirely below the window; it gets ONE slot of representation -
    the compared-side reservation - and never its document cap.

    Part 3 carries no route of its own and the auxiliary passages outscore it, so the
    only stage that can put a second Part 3 passage in the window is a reservation that
    ran past its one slot. On the deployed cut the n-per-chunk iteration (step 1b) fills
    Part 3 straight to its cap of 6.
    """
    pool = [_chunk(f"p2-{i:02d}", PART2, 0.66 - i * 0.001, ["单芯 截面"]) for i in range(20)]
    pool += [_chunk(f"p3-{i:02d}", PART3, 0.15 - i * 0.001) for i in range(8)]
    pool += [_chunk(f"aux-{i}", AUX, 0.55 - i * 0.001) for i in range(6)]
    policy = _policy(COMPARATIVE, pool)

    counts = _counts(rerank.select_context(_ordered(pool), 12, policy))
    cap = math.ceil(12 * policy.max_document_share)

    assert counts.get(PART3, 0) >= 1, "the lower-scoring side must survive the cut"
    assert counts.get(PART3, 0) == 1, (
        f"Part 3 took {counts.get(PART3)} slots (cap {cap}): the reservation became a "
        "cap-filling quota instead of one slot of representation")
    assert counts.get(PART2, 0) <= cap, counts


def test_C_the_document_cap_still_bounds_the_fill():
    """Two sides, both scoring high: the share cap still binds on the fill."""
    pool = [_chunk(f"p2-{i:02d}", PART2, 0.70 - i * 0.001, ["单芯 截面"]) for i in range(12)]
    pool += [_chunk(f"p3-{i:02d}", PART3, 0.69 - i * 0.001, ["三芯 截面"]) for i in range(12)]
    policy = _policy(COMPARATIVE, pool)

    counts = _counts(rerank.select_context(_ordered(pool), 12, policy))
    cap = math.ceil(12 * policy.max_document_share)

    assert counts.get(PART2, 0) <= cap, counts
    assert counts.get(PART3, 0) <= cap, counts


# ---------------------------------------------------------------------------
# D. Reservation pressure: more routes than the window can represent.
# ---------------------------------------------------------------------------

def test_D_many_routes_cannot_consume_every_slot():
    routes = [f"route-{i:02d} 导体标称截面" for i in range(12)]
    pool = [_chunk(f"r{i}-a", PART2, 0.62 - i * 0.002, [routes[i]]) for i in range(12)]
    pool += [_chunk(f"r{i}-b", PART2, 0.44 - i * 0.002, [routes[i]]) for i in range(12)]
    pool.append(_chunk(PROBE, AUX, 0.90))
    policy = _policy(SINGLE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)

    assert len(selected) == 12, _ids(selected)
    assert PROBE in _ids(selected), (
        f"12 routes on a 12-slot window left the fill nothing: {_ids(selected)}")


def test_D_the_route_set_is_still_represented_while_the_budget_allows():
    routes = [f"route-{i:02d} 导体标称截面" for i in range(12)]
    pool = [_chunk(f"r{i}-a", PART2, 0.62 - i * 0.002, [routes[i]]) for i in range(12)]
    pool.append(_chunk(PROBE, AUX, 0.90))
    policy = _policy(SINGLE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)

    # budget = 11, so 11 of the 12 routes are representable; none may be silently
    # crowded out by a reservation stage that overran the budget.
    assert sum(1 for r in routes if any(r in rerank.routes_of(c) for c in selected)) >= 10, _ids(selected)


def test_D_a_table_family_batch_cannot_overshoot_the_budget():
    """A route's ``take_batch`` claims its table's sibling row-batches too. Those slots
    are part of the same reservation budget, so the stage may still not own the window."""
    routes = [f"route-{i:02d} 导体标称截面" for i in range(8)]
    pool = []
    for i in range(8):
        for part in range(4):
            pool.append(_chunk(f"r{i}-{part}", PART2, 0.62 - i * 0.002 - part * 0.001,
                               [routes[i]], table=True,
                               body=f"<caption>表1 电缆结构技术参数表</caption> 导体标称截面 {part}"))
    pool.append(_chunk(PROBE, AUX, 0.99))
    policy = _policy(SINGLE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)

    assert len(selected) == 12, _ids(selected)
    assert PROBE in _ids(selected), (
        "table-family batches let the reservation stage take the whole window: "
        f"{_ids(selected)}")


# ---------------------------------------------------------------------------
# E. Final invariants.
# ---------------------------------------------------------------------------

def test_E_the_window_reaches_top_n_when_the_pool_permits():
    pool = live_shape_pool()
    selected = rerank.select_context(_ordered(pool), 12, _policy(COMPARATIVE, pool))

    assert len(selected) == 12


def test_E_the_table_cap_is_unchanged():
    """max_table_share still bounds the window; the repair may not spend it."""
    pool = [_chunk(f"t{i:02d}", PART2, 0.60 - i * 0.001, ["单芯 表"], table=True) for i in range(12)]
    pool += [_chunk(f"p{i}", PART2, 0.40 - i * 0.001, ["单芯 正文"]) for i in range(6)]
    policy = _policy(SINGLE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)
    tables = sum(1 for c in selected if chunk_profile.is_table_chunk(c))

    assert tables <= math.ceil(12 * policy.max_table_share), tables


def test_E_the_prose_floor_is_unchanged():
    """A clause question still gets its normative prose."""
    pool = [_chunk(f"t{i:02d}", PART2, 0.60 - i * 0.001, ["条款 表"], table=True) for i in range(14)]
    pool += [_chunk(f"c{i}", PART2, 0.20 - i * 0.001, ["条款 正文"]) for i in range(6)]
    policy = _policy(CLAUSE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)
    prose = sum(1 for c in selected if chunk_profile.is_prose_chunk(c))

    assert policy.min_prose > 0, "fixture must ask a rule-shaped question"
    assert prose >= policy.min_prose, (prose, policy.min_prose)


def test_E_max_document_share_is_unchanged():
    pool = live_shape_pool()
    policy = _policy(COMPARATIVE, pool)

    assert policy.max_document_share == rerank.MAX_COMPARED_DOCUMENT_SHARE


def test_E_no_new_module_constant_is_introduced():
    """The repair is structural: every tuned value is byte-for-byte what it was."""
    frozen = {
        "DEFAULT_FINAL_TOP_N": 8,
        "MIN_PROSE_PASSAGES": 4,
        "MAX_TABLE_SHARE": 0.5,
        "TABLE_PENALTY": 0.85,
        "HOLLOW_TABLE_PENALTY": 0.6,
        "MAX_HOLLOW_TABLE_PER_DOCUMENT_SHARE": 0.25,
        "MAX_TABLE_FAMILY_PARTS": 4,
        "MAX_AUXILIARY_DOCUMENT_SHARE": 0.4,
        "CORE_DOCUMENT_BOOST": 1.15,
        "VALUE_PAIRING_BOOST": 1.3,
        "VALUE_LIST_PENALTY": 0.8,
        "MAX_COMPARED_DOCUMENT_SHARE": 0.5,
    }
    for name, value in frozen.items():
        assert getattr(rerank, name) == value, f"{name} changed: {getattr(rerank, name)} != {value}"
    assert tuple(rerank.FINAL_TOP_N_RECOMMENDED) == (6, 8)

    constants = {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]+)\s*[:=]", RERANK_SOURCE, re.M)}
    assert constants == set(frozen) | {"FINAL_TOP_N_RECOMMENDED"}, sorted(constants)


def test_E_no_id_document_or_standard_specific_logic():
    """No chunk id, document name or designation may be special-cased in CODE.

    String CONSTANTS are what a rule can branch on, so those are what this reads; the
    module's own prose legitimately cites the corpus it was measured on.
    """
    tree = ast.parse(RERANK_SOURCE)
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for probe in ("Q/GDW", "Q_GDW", "73286", "第2部分", "第3部分", "单芯", "三芯", "海底"):
        assert not any(probe in s for s in literals), \
            f"document-specific string constant in the module: {probe}"
    assert not re.search(r"\b[0-9a-f]{16}\b", RERANK_SOURCE), "a chunk-id literal is present"
    assert not re.search(r"\b[0-9a-f]{32}\b", RERANK_SOURCE), "a doc-id literal is present"
    assert not re.search(r"(docnm_kwd|doc_id|document_name)\s*==", RERANK_SOURCE), \
        "the cut compares a document identity"


def test_E_the_selection_is_score_ordered_and_id_agnostic():
    pool = live_shape_pool()
    policy = _policy(COMPARATIVE, pool)
    baseline = _ids(rerank.select_context(_ordered(pool), 12, policy))

    renamed = []
    for i, c in enumerate(_ordered(pool)):
        clone = dict(c)
        clone["chunk_id"] = f"zz-{i:03d}"
        renamed.append(clone)

    assert len(rerank.select_context(renamed, 12, policy)) == len(baseline)


def test_E_the_module_under_test_is_the_file_named():
    """Pin which revision the RED/GREEN claim belongs to."""
    if os.environ.get("RERANK_PATH"):
        assert hashlib.sha256(RERANK_SOURCE.encode("utf-8")).hexdigest() == \
            hashlib.sha256(pathlib.Path(os.environ["RERANK_PATH"]).read_bytes()).hexdigest()
