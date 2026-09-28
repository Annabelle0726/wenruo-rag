"""Retrieval wiring: the provenance contract must survive the projection that reads ES.

The defect this gate reproduces: the producer persists the four provenance fields, but `Dealer.search`'s
default field projection (`rag/nlp/search.py:443-468`) does not request them, so the chunk dict handed to
`chunk_profile` has no provenance and the consumer must fail closed - safe, but inert, and an injected header
therefore still contaminates `carries_value`.

Nothing here bypasses `search.py`: the chunks under test are exactly what the real projection returns
(`SearchResult.field`), read out through the real `Dealer.search` against an isolated index. The gate also
asserts, on the source, that `Dealer.retrieval` calls `search` without a `fields=` override - which is why
this one list governs the whole retrieval path.
"""
import asyncio
import json
import pathlib
import sys

import pytest
import requests

sys.path.insert(0, "/ragflow")

from rag.nlp import doc_context
from rag.retrieval.chunk_profile import carries_value, _body_text

INDEX = "metadata_wiring_gate"
TENANT = "wiringtenant"
KB = "kb-wiring-gate"
NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
BODY = "5.3.4 内衬层厚度应不小于1.5mm，外被层应光滑无缺陷。"
HEADERLESS_BODY = "[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准 | 章节: 4 表] 这是原文引用的一行，内衬层厚度要求同上。"
PROVENANCE_FIELDS = doc_context.PREFIX_FIELDS


def es_client():
    import yaml

    with open("/ragflow/conf/service_conf.yaml", encoding="utf-8") as handle:
        conf = yaml.safe_load(handle)["es"]
    return str(conf["hosts"]).rstrip("/"), (conf.get("username"), conf.get("password"))


def make_index() -> None:
    host, auth = es_client()
    mapping = json.loads(pathlib.Path("/ragflow/conf/mapping.json").read_text(encoding="utf-8"))
    requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
    created = requests.put(f"{host}/{INDEX}", auth=auth, timeout=60, json={"settings": mapping.get("settings", {}), "mappings": mapping.get("mappings", {})})
    assert created.status_code in (200, 201), created.text[:300]


def store(doc_id: str, chunk: dict, host: str, auth) -> None:
    """Store the chunk the PRODUCER produced, with the indexed fields a real ingest writes."""
    from rag.nlp import rag_tokenizer

    content = chunk["content_with_weight"]
    document = {
        "id": f"{doc_id}-chunk",
        "doc_id": doc_id,
        "kb_id": KB,
        "docnm_kwd": NAME,
        "available_int": 1,
        "content_with_weight": content,
        "content_ltks": rag_tokenizer.tokenize(content),
        "doc_type_kwd": "text",
    }
    for field in PROVENANCE_FIELDS:
        if field in chunk:
            document[field] = chunk[field]
    written = requests.post(f"{host}/{INDEX}/_doc/{doc_id}-chunk?refresh=true", auth=auth, timeout=30, json=document)
    assert written.status_code in (200, 201), written.text[:300]


def produce(body: str) -> dict:
    chunk = {"content_with_weight": body, "doc_id": "produced-doc", "docnm_kwd": NAME, "content_ltks": "", "content_sm_ltks": ""}
    doc_context.apply_document_context([chunk], NAME, language="Chinese")
    return chunk


async def retrieve(question: str) -> dict:
    """The REAL projection: Dealer.search with the default field list, as retrieval() calls it."""
    from common import settings

    settings.init_settings()
    from rag.nlp import search as rag_search

    dealer = rag_search.Dealer(settings.docStoreConn)
    req = {"question": question, "page": 1, "size": 10, "similarity": 0.0, "vector": False}
    result = await dealer.search(req, [INDEX], [KB], None, False)
    fields = {}
    for chunk_id in result.ids:
        fields[chunk_id] = result.field[chunk_id]
    return fields


@pytest.fixture(scope="module")
def stored_index():
    import asyncio as _asyncio

    host, auth = es_client()
    make_index()

    provenanced = produce(BODY)
    collision = {"content_with_weight": HEADERLESS_BODY, "doc_id": "collision-doc", "docnm_kwd": NAME}
    corrupted = produce(BODY)
    corrupted["content_prefix_chars_int"] = int(corrupted["content_prefix_chars_int"]) + 3
    legacy = {"content_with_weight": BODY, "doc_id": "legacy-doc", "docnm_kwd": NAME}

    store("provenanced", provenanced, host, auth)
    store("collision", collision, host, auth)
    store("corrupted", corrupted, host, auth)
    store("legacy", legacy, host, auth)

    retrieved = _asyncio.get_event_loop().run_until_complete(retrieve("内衬层厚度")) if False else _asyncio.run(retrieve("内衬层厚度"))
    assert retrieved, "the isolated retrieval returned nothing to inspect"
    yield {"stored": {"provenanced": provenanced, "collision": collision, "corrupted": corrupted, "legacy": legacy}, "retrieved": retrieved}
    requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)


def by_doc(retrieved: dict, doc_id: str) -> dict:
    matches = [chunk for chunk in retrieved.values() if chunk.get("doc_id") == doc_id]
    assert matches, f"no retrieved chunk for {doc_id}: {[c.get('doc_id') for c in retrieved.values()]}"
    return matches[0]


# ===========================================================================
# The wiring itself
# ===========================================================================


def test_the_projection_carries_the_provenance_fields(stored_index):
    """RED pre-wiring: the stored fields exist, the retrieved chunk must carry them byte-identically."""
    assert stored_index["stored"]["provenanced"]["content_prefix_kind_kwd"] == doc_context.PREFIX_KIND_LEGACY
    retrieved = by_doc(stored_index["retrieved"], "provenanced")
    missing = [field for field in PROVENANCE_FIELDS if field not in retrieved]
    assert not missing, f"the retrieval projection dropped {missing}"


def test_the_retrieval_path_uses_that_same_projection():
    """`Dealer.retrieval` must not pass its own `fields=`, or the list above would not govern retrieval."""
    source = pathlib.Path("/ragflow/rag/nlp/search.py").read_text(encoding="utf-8")
    call = [line for line in source.splitlines() if "await self.search(req, idx_names, kb_ids" in line]
    assert call, "the retrieval call site was not found"
    assert "fields=" not in call[0], call[0]


# ===========================================================================
# End-to-end, through storage and the projection
# ===========================================================================


def test_e2e_provenanced_chunk(stored_index):
    stored = stored_index["stored"]["provenanced"]
    retrieved = by_doc(stored_index["retrieved"], "provenanced")
    # Field for field, through the datastore's declared representation: keywords as written, integers as
    # canonical unsigned decimals (pinned by test_the_datastore_representations_are_pinned).
    assert retrieved["content_prefix_kind_kwd"] == stored["content_prefix_kind_kwd"]
    assert retrieved["content_prefix_hash_kwd"] == stored["content_prefix_hash_kwd"]
    assert retrieved["content_prefix_version_int"] == str(stored["content_prefix_version_int"])
    assert retrieved["content_prefix_chars_int"] == str(stored["content_prefix_chars_int"])

    extent = doc_context.verified_prefix_extent(retrieved)
    assert extent == stored["content_prefix_chars_int"], (extent, stored["content_prefix_chars_int"])
    body = _body_text(retrieved)
    assert body == BODY, body
    assert "220kv" not in body.lower().replace(" ", "")
    assert carries_value(retrieved, ("220",)) is False, "the injected header is metadata, not evidence"


def test_e2e_body_collision(stored_index):
    retrieved = by_doc(stored_index["retrieved"], "collision")
    assert doc_context.verified_prefix_extent(retrieved) is None, "a look-alike body carries no provenance"
    assert _body_text(retrieved) == HEADERLESS_BODY
    assert carries_value(retrieved, ("220",)) is True, "the document's own words remain evidence"


def test_e2e_corrupted_provenance(stored_index):
    stored = stored_index["stored"]["corrupted"]
    retrieved = by_doc(stored_index["retrieved"], "corrupted")
    assert retrieved["content_prefix_kind_kwd"] == stored["content_prefix_kind_kwd"]
    assert retrieved["content_prefix_hash_kwd"] == stored["content_prefix_hash_kwd"]
    assert retrieved["content_prefix_chars_int"] == str(stored["content_prefix_chars_int"]), "transported unchanged"
    assert retrieved["content_prefix_version_int"] == str(stored["content_prefix_version_int"])
    assert doc_context.verified_prefix_extent(retrieved) is None, "the consumer must reject it"
    body = _body_text(retrieved)
    assert body == retrieved["content_with_weight"], "no partial strip"
    assert body.startswith("[标准号: ")


def test_e2e_legacy_chunk(stored_index):
    retrieved = by_doc(stored_index["retrieved"], "legacy")
    assert doc_context.verified_prefix_extent(retrieved) is None
    assert _body_text(retrieved) == BODY
    assert carries_value(retrieved, ("1.5",)) is True


def test_projection_fidelity(stored_index):
    """Field for field through the transport, with no normalization, coercion or reconstruction by it: the
    keywords arrive as written and the integers arrive as the canonical decimals the datastore writes."""
    stored = stored_index["stored"]["provenanced"]
    retrieved = by_doc(stored_index["retrieved"], "provenanced")
    assert retrieved["content_prefix_chars_int"] == str(stored["content_prefix_chars_int"])
    assert retrieved["content_prefix_version_int"] == str(stored["content_prefix_version_int"])
    assert retrieved["content_prefix_kind_kwd"] == stored["content_prefix_kind_kwd"]
    assert retrieved["content_prefix_hash_kwd"] == stored["content_prefix_hash_kwd"]
    # The contract verifies against the bytes, whatever wire form carried the extent:
    extent = doc_context.verified_prefix_extent(retrieved)
    assert extent == stored["content_prefix_chars_int"]
    header = retrieved["content_with_weight"][:extent]
    assert doc_context.prefix_hash(header) == retrieved["content_prefix_hash_kwd"]


# ===========================================================================
# The datastore's integer wire form, and the canonical parser that must accept it
# ===========================================================================


def test_the_datastore_representations_are_pinned(stored_index):
    """What the transport actually hands a consumer, recorded here so the contract cannot drift from it.

    `es_conn.get_fields` stringifies every non-list value except `available_int`, so the two integer
    provenance fields arrive as canonical unsigned decimal strings - not as the ints the producer wrote.
    """
    stored = stored_index["stored"]["provenanced"]
    retrieved = by_doc(stored_index["retrieved"], "provenanced")
    assert isinstance(stored["content_prefix_version_int"], int) and stored["content_prefix_version_int"] == 1
    assert isinstance(stored["content_prefix_chars_int"], int)

    assert retrieved["content_prefix_version_int"] == "1", retrieved["content_prefix_version_int"]
    assert retrieved["content_prefix_chars_int"] == str(stored["content_prefix_chars_int"])
    assert retrieved["content_prefix_kind_kwd"] == doc_context.PREFIX_KIND_LEGACY
    assert isinstance(retrieved["content_prefix_hash_kwd"], str)


def test_the_projection_transports_all_four_fields_before_the_parser_is_considered(stored_index):
    retrieved = by_doc(stored_index["retrieved"], "provenanced")
    for field in PROVENANCE_FIELDS:
        assert field in retrieved, field
        assert retrieved[field] == stored_index["stored"]["provenanced"][field] or str(
            stored_index["stored"]["provenanced"][field]
        ) == retrieved[field]


def _produced() -> dict:
    return produce(BODY)


@pytest.mark.parametrize("wire", [1, "1"])
def test_canonical_wire_form_is_accepted_for_the_version(wire):
    chunk = _produced()
    chunk["content_prefix_version_int"] = wire
    assert doc_context.verified_prefix_extent(chunk) == len(chunk["content_with_weight"]) - len(BODY)


@pytest.mark.parametrize("wire", ["int", "str"])
def test_canonical_wire_form_is_accepted_for_the_extent(wire):
    chunk = _produced()
    extent = chunk["content_prefix_chars_int"]
    chunk["content_prefix_chars_int"] = extent if wire == "int" else str(extent)
    assert doc_context.verified_prefix_extent(chunk) == extent
    assert _body_text(chunk) == BODY


@pytest.mark.parametrize(
    "wire",
    [
        True,
        False,
        None,
        1.0,
        " 1",
        "1 ",
        "+1",
        "-1",
        "01",
        "00105",
        "1.0",
        "1e0",
        "１",
        "",
        "abc",
        ["1"],
        {"value": 1},
        object(),
    ],
)
def test_a_non_canonical_representation_fails_closed(wire):
    """`True` is an int in Python, full-width digits are digits to `str.isdigit`, and `"01"` is a valid
    decimal - none of them is a canonical unsigned decimal, and each must leave the whole content as
    evidence."""
    chunk = _produced()
    chunk["content_prefix_chars_int"] = wire
    assert doc_context.verified_prefix_extent(chunk) is None, wire
    assert _body_text(chunk) == chunk["content_with_weight"]


@pytest.mark.parametrize("wire", [0, "0", -5, "-5"])
def test_a_canonical_but_semantically_impossible_extent_fails_closed(wire):
    chunk = _produced()
    chunk["content_prefix_chars_int"] = wire
    assert doc_context.verified_prefix_extent(chunk) is None, wire
    assert _body_text(chunk) == chunk["content_with_weight"]


@pytest.mark.parametrize("wire", [3, "3", 0, "0", None, "x"])
def test_an_unsupported_version_fails_closed(wire):
    chunk = _produced()
    chunk["content_prefix_version_int"] = wire
    assert doc_context.verified_prefix_extent(chunk) is None, wire


def test_an_out_of_range_extent_still_fails_closed_with_the_wire_form():
    chunk = _produced()
    size = len(chunk["content_with_weight"])
    chunk["content_prefix_chars_int"] = str(size + 100)
    assert doc_context.verified_prefix_extent(chunk) is None
    chunk["content_prefix_chars_int"] = size
    assert doc_context.verified_prefix_extent(chunk) is None, "an extent covering the whole content has no body"
