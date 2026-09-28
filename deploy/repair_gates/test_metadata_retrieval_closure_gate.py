"""Final provenance propagation through `Dealer.retrieval()` - the authoritative wiring gate.

The break this reproduces: `Dealer.search` returns the four provenance fields inside `SearchResult.field`,
and then `Dealer.retrieval` RECONSTRUCTS each chunk from an explicit key list (`search.py:1138-1156`) that
does not name them, so the chunk a consumer actually receives has no provenance, `_body_text` keeps the
injected prefix, and a figure that lives only in that prefix contaminates `carries_value`.

Nothing here stops at `SearchResult.field`: every case goes producer -> datastore -> `Dealer.search` ->
`Dealer.retrieval` -> final returned chunk -> `_body_text` -> `carries_value`.
"""
import asyncio
import hashlib
import json
import pathlib
import sys

import pytest
import requests

sys.path.insert(0, "/ragflow")

from rag.nlp import doc_context, rag_tokenizer, retrieval_projection
from rag.retrieval.chunk_profile import carries_value, _body_text
from rag.retrieval.decomposition import question_values

TENANT = "closuretenant"
INDEX = f"ragflow_{TENANT}"
KB = "kb-closure"
NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
BODY = "5.3.4 内衬层厚度应不小于1.5mm，外被层应光滑无缺陷。"
LOOK_ALIKE = "[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准 | 章节: 4 表] 原文引用，内衬层厚度要求同上。"
AUDITED_DECOMPOSITION = "ee2a060d95be16acc099d18a15cc0ef630857ea6e38c047edd80d8828fdffc9f"
PROVENANCE_FIELDS = doc_context.PREFIX_FIELDS


def es():
    import yaml

    with open("/ragflow/conf/service_conf.yaml", encoding="utf-8") as handle:
        conf = yaml.safe_load(handle)["es"]
    return str(conf["hosts"]).rstrip("/"), (conf.get("username"), conf.get("password"))


def produce(body=BODY) -> dict:
    chunk = {"content_with_weight": body, "doc_id": "d", "docnm_kwd": NAME, "content_ltks": "", "content_sm_ltks": ""}
    doc_context.apply_document_context([chunk], NAME, language="Chinese")
    return chunk


def store(doc_id: str, chunk: dict) -> None:
    host, auth = es()
    content = chunk["content_with_weight"]
    document = {"id": f"{doc_id}-c", "doc_id": doc_id, "kb_id": KB, "docnm_kwd": NAME, "available_int": 1,
                "content_with_weight": content, "content_ltks": rag_tokenizer.tokenize(content), "doc_type_kwd": "text"}
    for field in PROVENANCE_FIELDS:
        if field in chunk:
            document[field] = chunk[field]
    written = requests.post(f"{host}/{INDEX}/_doc/{doc_id}-c?refresh=true", auth=auth, timeout=30, json=document)
    assert written.status_code in (200, 201), written.text[:300]


def dealer_without_mysql():
    """The real Dealer, with the one harness shim the isolated network needs: the deleted-document prune
    consults MySQL, which does not exist here. It is replaced by an identity coroutine so the retrieval
    path under test (projection, scoring, RECONSTRUCTION) is the product's own code."""
    from common import settings

    settings.init_settings()
    from rag.nlp import search as rag_search

    dealer = rag_search.Dealer(settings.docStoreConn)

    async def keep(result):
        return result

    dealer._prune_deleted_chunks = keep
    return dealer, rag_search


def search_result_field(question="内衬层厚度"):
    """The intermediate boundary: what `Dealer.search` alone hands back."""
    async def go():
        dealer, _ = dealer_without_mysql()
        result = await dealer.search({"question": question, "page": 1, "size": 10, "similarity": 0.0, "vector": False}, [INDEX], [KB], None, False)
        return {cid: result.field[cid] for cid in result.ids}
    return asyncio.run(go())


def final_chunks(question="内衬层厚度", embd_mdl=None):
    """The FINAL boundary: what `Dealer.retrieval` returns to every caller."""
    async def go():
        dealer, _ = dealer_without_mysql()
        ranks = await dealer.retrieval(question=question, embd_mdl=embd_mdl, tenant_ids=[TENANT], kb_ids=[KB],
                                       page=1, page_size=10, similarity_threshold=0.0, vector_similarity_weight=0.3,
                                       rerank_mdl=None, rank_feature=None)
        return ranks
    return asyncio.run(go())


@pytest.fixture(scope="module")
def corpus():
    host, auth = es()
    mapping = json.loads(pathlib.Path("/ragflow/conf/mapping.json").read_text(encoding="utf-8"))
    requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
    created = requests.put(f"{host}/{INDEX}", auth=auth, timeout=60,
                           json={"settings": mapping.get("settings", {}), "mappings": mapping.get("mappings", {})})
    assert created.status_code in (200, 201), created.text[:300]

    provenanced = produce()
    collision = {"content_with_weight": LOOK_ALIKE, "doc_id": "collision", "docnm_kwd": NAME}
    corrupt_extent = produce(); corrupt_extent["content_prefix_chars_int"] = int(corrupt_extent["content_prefix_chars_int"]) + 3
    corrupt_hash = produce(); corrupt_hash["content_prefix_hash_kwd"] = "0" * 16
    corrupt_version = produce(); corrupt_version["content_prefix_version_int"] = 99
    legacy = {"content_with_weight": BODY, "doc_id": "legacy", "docnm_kwd": NAME}
    for label, chunk in (("provenanced", provenanced), ("collision", collision), ("corrupt_extent", corrupt_extent),
                         ("corrupt_hash", corrupt_hash), ("corrupt_version", corrupt_version), ("legacy", legacy)):
        store(label, chunk)

    final = final_chunks()
    assert final["chunks"], "Dealer.retrieval returned no chunks"
    yield {"stored": {"provenanced": provenanced, "collision": collision, "corrupt_extent": corrupt_extent,
                      "corrupt_hash": corrupt_hash, "corrupt_version": corrupt_version, "legacy": legacy},
           "intermediate": search_result_field(), "final": final}
    requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)


def final_for(loaded, doc_id):
    matches = [chunk for chunk in loaded["final"]["chunks"] if chunk.get("doc_id") == doc_id]
    assert matches, f"{doc_id} missing from the retrieval result: {[c.get('doc_id') for c in loaded['final']['chunks']]}"
    return matches[0]


# ===========================================================================
# The RED classification
# ===========================================================================


def test_red_search_result_has_provenance_but_the_final_chunk_does_not(corpus):
    """Codex's two-boundary finding, asserted at both boundaries."""
    intermediate = [c for c in corpus["intermediate"].values() if c.get("doc_id") == "provenanced"][0]
    for field in PROVENANCE_FIELDS:
        assert field in intermediate, f"SEARCH_RESULT_PROVENANCE must be PRESENT: {field} missing"

    final = final_for(corpus, "provenanced")
    present = [field for field in PROVENANCE_FIELDS if field in final]
    assert present == list(PROVENANCE_FIELDS), f"FINAL_RETRIEVAL_CHUNK_PROVENANCE = ABSENT: carried {present}"


def test_red_header_contamination_after_retrieval(corpus):
    final = final_for(corpus, "provenanced")
    assert doc_context.verified_prefix_extent(final) == corpus["stored"]["provenanced"]["content_prefix_chars_int"]
    assert _body_text(final) == BODY
    assert carries_value(final, ("220",)) is False, "HEADER_CONTAMINATION_AFTER_RETRIEVAL"


# ===========================================================================
# A-F through the final boundary
# ===========================================================================


def test_case_a_provenanced(corpus):
    final = final_for(corpus, "provenanced")
    stored = corpus["stored"]["provenanced"]
    assert final["content_prefix_kind_kwd"] == stored["content_prefix_kind_kwd"]
    assert final["content_prefix_hash_kwd"] == stored["content_prefix_hash_kwd"]
    assert final["content_prefix_chars_int"] == str(stored["content_prefix_chars_int"])
    assert final["content_prefix_version_int"] == str(stored["content_prefix_version_int"])
    assert doc_context.verified_prefix_extent(final) == stored["content_prefix_chars_int"]
    assert _body_text(final) == BODY
    assert "220kv" not in _body_text(final).replace(" ", "").lower()
    assert carries_value(final, ("220",)) is False


def test_case_b_body_collision(corpus):
    final = final_for(corpus, "collision")
    assert doc_context.verified_prefix_extent(final) is None
    assert _body_text(final) == LOOK_ALIKE
    assert carries_value(final, ("220",)) is True


@pytest.mark.parametrize("doc_id", ["corrupt_extent", "corrupt_hash", "corrupt_version"])
def test_case_c_corrupted_provenance(corpus, doc_id):
    final = final_for(corpus, doc_id)
    stored = corpus["stored"][doc_id]
    assert final["content_prefix_chars_int"] == str(stored["content_prefix_chars_int"]), "values pass through unchanged"
    assert final["content_prefix_hash_kwd"] == stored["content_prefix_hash_kwd"]
    assert doc_context.verified_prefix_extent(final) is None
    assert _body_text(final) == final["content_with_weight"], "no partial strip"
    assert _body_text(final).startswith("[标准号: ")


def test_case_d_legacy(corpus):
    final = final_for(corpus, "legacy")
    assert [field for field in PROVENANCE_FIELDS if field in final] == [], "no provenance synthesized"
    assert _body_text(final) == BODY
    assert carries_value(final, ("1.5",)) is True


def test_case_e_edit_invalidation(corpus):
    """The authorised edit/invalidation semantics, through the FINAL `Dealer.retrieval` boundary.

    Two mutations, because the contract distinguishes them: an edit that destroys the recorded prefix must
    be invalidated, while an edit that leaves those bytes untouched legitimately keeps its provenance (G6's
    second branch). The earlier version of this case appended to the body and asserted invalidation, which
    the contract permits to preserve - that was a gate expectation error, not a product defect: the trace
    shows the prefix was intact and verification correctly succeeded.
    """
    # Sub-case 1: the edit alters the prefix region, so the record no longer describes the content.
    destroyed = dict(corpus["stored"]["provenanced"])
    prefix = destroyed["content_with_weight"][: int(destroyed["content_prefix_chars_int"])]
    rewritten = "X" + destroyed["content_with_weight"][1:]
    assert not rewritten.startswith(prefix), "the mutation must destroy the recorded prefix bytes"
    doc_context.invalidation_after_edit(destroyed, rewritten)
    destroyed["content_with_weight"] = rewritten
    assert doc_context.verified_prefix_extent(destroyed) is None, "the authorised path must invalidate"
    store("edited_destroy", destroyed)

    stored = requests.get(f"{es()[0]}/{INDEX}/_doc/edited_destroy-c", auth=es()[1], timeout=30).json()["_source"]
    assert stored["content_prefix_kind_kwd"] == doc_context.PREFIX_NONE, "the datastore must reflect the invalidation"
    assert stored["content_prefix_chars_int"] == 0

    loaded = final_chunks()
    returned = [chunk for chunk in loaded["chunks"] if chunk.get("doc_id") == "edited_destroy"]
    assert returned, "the edited chunk must reach the final boundary for this case to mean anything"
    final = returned[0]
    assert [field for field in PROVENANCE_FIELDS if field in final] == list(PROVENANCE_FIELDS), "fields travel, as values"
    assert final["content_prefix_kind_kwd"] == doc_context.PREFIX_NONE
    assert doc_context.verified_prefix_extent(final) is None, "stale provenance cannot authorise stripping"
    assert _body_text(final) == final["content_with_weight"], "the consumer fails closed to whole-content evidence"
    assert carries_value(final, ("220",)) is True, "the unverifiable header text is evidence again"

    # Sub-case 2: an edit that preserves the prefix bytes keeps valid provenance and body-only evidence.
    appended = dict(corpus["stored"]["provenanced"])
    extended = appended["content_with_weight"] + "编辑追加：外被层颜色应为黑色。"
    doc_context.invalidation_after_edit(appended, extended)
    appended["content_with_weight"] = extended
    assert doc_context.verified_prefix_extent(appended) == int(appended["content_prefix_chars_int"])
    store("edited_append", appended)

    loaded = final_chunks()
    returned = [chunk for chunk in loaded["chunks"] if chunk.get("doc_id") == "edited_append"]
    assert returned, "the append-edited chunk must reach the final boundary"
    final = returned[0]
    assert doc_context.verified_prefix_extent(final) == int(corpus["stored"]["provenanced"]["content_prefix_chars_int"])
    assert _body_text(final) == extended[int(corpus["stored"]["provenanced"]["content_prefix_chars_int"]) :]
    assert carries_value(final, ("220",)) is False


def test_case_f_reprojection(corpus):
    reprojected = dict(corpus["stored"]["provenanced"])
    metadata = retrieval_projection.resolve_metadata([], title=doc_context.document_title(NAME), category="power_cable")
    retrieval_projection.apply_projection(reprojected, metadata)
    assert reprojected["content_prefix_kind_kwd"] == doc_context.PREFIX_KIND_PROFILE
    store("reprojected", reprojected)

    loaded = final_chunks()
    final = [chunk for chunk in loaded["chunks"] if chunk.get("doc_id") == "reprojected"][0]
    assert doc_context.verified_prefix_extent(final) == reprojected["content_prefix_chars_int"]
    assert _body_text(final) == BODY
    assert carries_value(final, ("220",)) is False


# ===========================================================================
# Propagation is not branch-specific
# ===========================================================================


def test_healthy_path_provenance_propagation(corpus):
    """No embedding model: the lexical-only path, which is the healthy shape here."""
    final = final_for(corpus, "provenanced")
    assert all(field in final for field in PROVENANCE_FIELDS)
    assert doc_context.verified_prefix_extent(final) is not None


def test_degraded_path_provenance_propagation(corpus):
    """A recoverable dense failure degrades the run; the reconstruction must still carry provenance."""
    from rag.llm.embedding_model import EmbeddingError

    class StubEmb:
        def encode(self, texts):
            raise EmbeddingError("provider precondition", retryable=False)

        def encode_queries(self, texts):
            raise EmbeddingError("provider precondition", retryable=False)

    loaded = final_chunks(embd_mdl=StubEmb())
    assert loaded["chunks"], "the degraded path returned nothing, so propagation cannot be shown"
    modes = {chunk.get("score_provenance", {}).get("mode") for chunk in loaded["chunks"]}
    assert modes == {"LEXICAL_DEGRADED"}, modes
    provenanced = [c for c in loaded["chunks"] if c.get("doc_id") == "provenanced"][0]
    assert all(field in provenanced for field in PROVENANCE_FIELDS)
    assert doc_context.verified_prefix_extent(provenanced) is not None
    assert _body_text(provenanced) == BODY


# ===========================================================================
# Numeric revision guard - the recurrence guard for the rejected seven-file candidate
# ===========================================================================


def test_the_numeric_layer_is_the_audited_revision():
    digest = hashlib.sha256(pathlib.Path("/ragflow/rag/retrieval/decomposition.py").read_bytes()).hexdigest()
    assert digest == AUDITED_DECOMPOSITION, "the overlay must carry the audited Rev-3.1 decomposition.py"


def test_numeric_semantic_guard():
    assert question_values("根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？") == ["3.9", "4.1"]
