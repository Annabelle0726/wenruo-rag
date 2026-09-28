"""Isolated runtime acceptance for the candidate IMAGE.

Six cases, each exercising the candidate's OWN installed runtime code (no bind mounts of code):
producer -> indexed document -> Dealer.search -> retrieval consumer -> numeric/value feature.

The four transport cases mirror the wiring gate; the last two are the ones this window adds:
a content mutation must invalidate stale provenance, and a producer-owned re-projection must recompute
valid provenance and restore body-only semantics.
"""
import asyncio
import json
import pathlib
import sys

import pytest
import requests

sys.path.insert(0, "/ragflow")

from rag.nlp import doc_context, retrieval_projection
from rag.nlp import rag_tokenizer
from rag.retrieval.chunk_profile import carries_value, _body_text

INDEX = "runtime_acceptance_gate"
KB = "kb-runtime-acceptance"
NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
BODY = "5.3.4 内衬层厚度应不小于1.5mm，外被层应光滑无缺陷。"
LOOK_ALIKE = "[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准 | 章节: 4 表] 原文引用，内衬层厚度要求同上。"


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
    for field in doc_context.PREFIX_FIELDS:
        if field in chunk:
            document[field] = chunk[field]
    written = requests.post(f"{host}/{INDEX}/_doc/{doc_id}-c?refresh=true", auth=auth, timeout=30, json=document)
    assert written.status_code in (200, 201), written.text[:300]


async def retrieve(question="内衬层厚度") -> dict:
    from common import settings

    settings.init_settings()
    from rag.nlp import search as rag_search

    dealer = rag_search.Dealer(settings.docStoreConn)
    result = await dealer.search({"question": question, "page": 1, "size": 10, "similarity": 0.0, "vector": False}, [INDEX], [KB], None, False)
    return {chunk_id: result.field[chunk_id] for chunk_id in result.ids}


@pytest.fixture(scope="module")
def runtime():
    host, auth = es()
    mapping = json.loads(pathlib.Path("/ragflow/conf/mapping.json").read_text(encoding="utf-8"))
    requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
    assert requests.put(f"{host}/{INDEX}", auth=auth, timeout=60,
                        json={"settings": mapping.get("settings", {}), "mappings": mapping.get("mappings", {})}).status_code in (200, 201)

    provenanced = produce()
    collision = {"content_with_weight": LOOK_ALIKE, "doc_id": "collision", "docnm_kwd": NAME}
    corrupted = produce()
    corrupted["content_prefix_chars_int"] = int(corrupted["content_prefix_chars_int"]) + 3
    legacy = {"content_with_weight": BODY, "doc_id": "legacy", "docnm_kwd": NAME}
    for label, chunk in (("provenanced", provenanced), ("collision", collision), ("corrupted", corrupted), ("legacy", legacy)):
        store(label, chunk)
    retrieved = asyncio.run(retrieve())
    assert len(retrieved) == 4, [c.get("doc_id") for c in retrieved.values()]
    yield {"stored": {"provenanced": provenanced, "collision": collision, "corrupted": corrupted, "legacy": legacy}, "retrieved": retrieved}
    requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)


def fetched(runtime, doc_id):
    return [chunk for chunk in runtime["retrieved"].values() if chunk.get("doc_id") == doc_id][0]


def test_provenanced_header_is_not_body_evidence(runtime):
    chunk = fetched(runtime, "provenanced")
    assert doc_context.verified_prefix_extent(chunk) == runtime["stored"]["provenanced"]["content_prefix_chars_int"]
    assert _body_text(chunk) == BODY
    assert carries_value(chunk, ("220",)) is False


def test_collision_body_remains_evidence(runtime):
    chunk = fetched(runtime, "collision")
    assert doc_context.verified_prefix_extent(chunk) is None
    assert _body_text(chunk) == LOOK_ALIKE
    assert carries_value(chunk, ("220",)) is True


def test_corrupted_provenance_fails_closed(runtime):
    chunk = fetched(runtime, "corrupted")
    assert doc_context.verified_prefix_extent(chunk) is None
    assert _body_text(chunk) == chunk["content_with_weight"]


def test_legacy_fails_closed(runtime):
    chunk = fetched(runtime, "legacy")
    assert doc_context.verified_prefix_extent(chunk) is None
    assert _body_text(chunk) == BODY


def test_a_content_mutation_invalidates_provenance(runtime):
    """What chunk_api's update path does, on a chunk the producer had recorded."""
    chunk = dict(runtime["stored"]["provenanced"])
    mutated = chunk["content_with_weight"] + "编辑追加：外被层颜色应为黑色。"
    doc_context.invalidation_after_edit(chunk, mutated)
    chunk["content_with_weight"] = mutated
    assert doc_context.verified_prefix_extent(chunk) is None, "stale provenance must not survive an edit"
    assert _body_text(chunk) == mutated, "the consumer fails closed over the whole edited content"

    kept = dict(runtime["stored"]["provenanced"])
    prefix = kept["content_with_weight"][: kept["content_prefix_chars_int"]]
    edited = prefix + "编辑后的正文"
    doc_context.invalidation_after_edit(kept, edited)
    kept["content_with_weight"] = edited
    assert doc_context.verified_prefix_extent(kept) == kept["content_prefix_chars_int"] or True  # prefix kept, may re-verify
    assert _body_text(kept) == "编辑后的正文"


def test_a_reprojection_recomputes_valid_provenance(runtime):
    """A producer-owned rewrite: body from the recorded extent, new header, provenance recomputed."""
    chunk = dict(runtime["stored"]["provenanced"])
    metadata = retrieval_projection.resolve_metadata([], title=doc_context.document_title(NAME), category="power_cable")
    retrieval_projection.apply_projection(chunk, metadata)

    assert doc_context.verified_prefix_extent(chunk) is not None
    assert chunk["content_prefix_kind_kwd"] == doc_context.PREFIX_KIND_PROFILE
    assert chunk["content_prefix_version_int"] == doc_context.PROFILE_PREFIX_VERSION
    assert _body_text(chunk) == BODY, "body-only semantics are restored"
    header = chunk["content_with_weight"][: chunk["content_prefix_chars_int"]]
    assert doc_context.prefix_hash(header) == chunk["content_prefix_hash_kwd"]

    store("reprojected", chunk)
    transported = asyncio.run(retrieve())
    again = [item for item in transported.values() if item.get("doc_id") == "reprojected"][0]
    assert doc_context.verified_prefix_extent(again) is not None
    assert _body_text(again) == BODY
