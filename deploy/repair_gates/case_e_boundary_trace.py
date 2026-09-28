"""Case E boundary trace: is the unresolved failure a fixture problem or a product defect?

Prints, in order: the two runtime hashes as actually imported, then the same chunk identity across the nine
boundaries the review names, for (1) an append-only edit, (2) a prefix-destroying edit, and (3) the
reprojection control. Everything goes through the real `Dealer.search` and `Dealer.retrieval`.
"""
import asyncio
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

EXPECTED_SEARCH = "abdf9a25813c00dda59b393ae3cd29143a33e98409e9cbfa056a92b8c7ea6912"
EXPECTED_DECOMPOSITION = "ee2a060d95be16acc099d18a15cc0ef630857ea6e38c047edd80d8828fdffc9f"

TENANT = "closuretenant"
INDEX = f"ragflow_{TENANT}"
KB = "kb-closure"
NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
BODY = "5.3.4 内衬层厚度应不小于1.5mm，外被层应光滑无缺陷。"

print("===== RUNTIME HASHES (the files this process imports) =====", flush=True)
SEARCH_PATH = pathlib.Path("/ragflow/rag/nlp/search.py")
DECOMPOSITION_PATH = pathlib.Path("/ragflow/rag/retrieval/decomposition.py")
search_sha = hashlib.sha256(SEARCH_PATH.read_bytes()).hexdigest()
decomposition_sha = hashlib.sha256(DECOMPOSITION_PATH.read_bytes()).hexdigest()
print(f"rag.nlp.search              {search_sha}  {'MATCH' if search_sha == EXPECTED_SEARCH else 'MISMATCH'}", flush=True)
print(f"rag.retrieval.decomposition {decomposition_sha}  {'MATCH' if decomposition_sha == EXPECTED_DECOMPOSITION else 'MISMATCH'}", flush=True)
if search_sha != EXPECTED_SEARCH or decomposition_sha != EXPECTED_DECOMPOSITION:
    print("STOP: runtime hash differs; the gate result must not be interpreted", flush=True)
    raise SystemExit(2)

# settings first: `rag.nlp.search` imports `rag.nlp.query` -> `rag.utils.redis_conn` -> `common.settings`,
# so importing the search module before settings is initialised trips a circular import.
from common import settings  # noqa: E402

settings.init_settings()
from rag.nlp import search as rag_search  # noqa: E402
from rag.retrieval import decomposition  # noqa: E402

print(f"search module path:      {rag_search.__file__}", flush=True)
print(f"decomposition module:    {decomposition.__file__}", flush=True)
if pathlib.Path(rag_search.__file__).resolve() != SEARCH_PATH or pathlib.Path(decomposition.__file__).resolve() != DECOMPOSITION_PATH:
    print("STOP: the imported modules are not the hashed files", flush=True)
    raise SystemExit(2)

import requests  # noqa: E402
from rag.nlp import doc_context, rag_tokenizer  # noqa: E402
from rag.retrieval.chunk_profile import carries_value, _body_text  # noqa: E402

settings.init_settings()
import yaml  # noqa: E402

conf = yaml.safe_load(pathlib.Path("/ragflow/conf/service_conf.yaml").read_text(encoding="utf-8"))["es"]
host, auth = str(conf["hosts"]).rstrip("/"), (conf.get("username"), conf.get("password"))
mapping = json.loads(pathlib.Path("/ragflow/conf/mapping.json").read_text(encoding="utf-8"))
requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
requests.put(f"{host}/{INDEX}", auth=auth, timeout=60, json={"settings": mapping.get("settings", {}), "mappings": mapping.get("mappings", {})})

FIELDS = doc_context.PREFIX_FIELDS


def content_hash(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]


def snapshot(label, chunk):
    fields = {f: chunk.get(f) for f in FIELDS if f in chunk}
    extent = doc_context.verified_prefix_extent(chunk)
    print(f"  [{label}] id={chunk.get('chunk_id') or chunk.get('id')} doc_id={chunk.get('doc_id')} "
          f"content={content_hash(chunk.get('content_with_weight'))} len={len(str(chunk.get('content_with_weight') or ''))} "
          f"fields={fields} verified={extent}", flush=True)
    return extent


def produce(body=BODY):
    chunk = {"content_with_weight": body, "doc_id": "d", "docnm_kwd": NAME, "content_ltks": "", "content_sm_ltks": ""}
    doc_context.apply_document_context([chunk], NAME, language="Chinese")
    return chunk


def store(doc_id, chunk):
    content = chunk["content_with_weight"]
    document = {"id": f"{doc_id}-c", "doc_id": doc_id, "kb_id": KB, "docnm_kwd": NAME, "available_int": 1,
                "content_with_weight": content, "content_ltks": rag_tokenizer.tokenize(content), "doc_type_kwd": "text"}
    for field in FIELDS:
        if field in chunk:
            document[field] = chunk[field]
    status = requests.post(f"{host}/{INDEX}/_doc/{doc_id}-c?refresh=true", auth=auth, timeout=30, json=document).status_code
    stored = requests.get(f"{host}/{INDEX}/_doc/{doc_id}-c", auth=auth, timeout=30).json()["_source"]
    print(f"  [datastore {doc_id}] status={status} content={content_hash(stored.get('content_with_weight'))} "
          f"fields={ {f: stored.get(f) for f in FIELDS if f in stored} }", flush=True)
    return stored


def dealer():
    dealer_obj = rag_search.Dealer(settings.docStoreConn)

    async def keep(result):
        return result

    dealer_obj._prune_deleted_chunks = keep
    return dealer_obj


async def search_and_retrieve(question="内衬层厚度"):
    d = dealer()
    sres = await d.search({"question": question, "page": 1, "size": 10, "similarity": 0.0, "vector": False}, [INDEX], [KB], None, False)
    ids = list(sres.ids)
    ranks = await d.retrieval(question=question, embd_mdl=None, tenant_ids=[TENANT], kb_ids=[KB], page=1, page_size=10,
                              similarity_threshold=0.0, vector_similarity_weight=0.3, rerank_mdl=None, rank_feature=None)
    return ids, {cid: sres.field[cid] for cid in ids}, ranks


base = produce()
print("\n===== boundary 1: original chunk before the edit =====", flush=True)
snapshot("original", base)

# --- edit 1: append-only (the authorised path permits preserving an intact prefix) -----------
append_edit = dict(base)
appended = append_edit["content_with_weight"] + "编辑追加：外被层颜色应为黑色。"
doc_context.invalidation_after_edit(append_edit, appended)
append_edit["content_with_weight"] = appended
print("\n===== edit 1: append-only edit =====", flush=True)
print(f"  prefix bytes preserved: {appended.startswith(base['content_with_weight'][: int(base['content_prefix_chars_int'])])}", flush=True)
snapshot("after append edit", append_edit)
store("edited_append", append_edit)

# --- edit 2: a prefix-destroying content edit ------------------------------------------------
destroy_edit = dict(base)
rewritten = "X" + destroy_edit["content_with_weight"][1:]
doc_context.invalidation_after_edit(destroy_edit, rewritten)
destroy_edit["content_with_weight"] = rewritten
print("\n===== edit 2: prefix-destroying edit =====", flush=True)
print(f"  prefix bytes preserved: {rewritten.startswith(base['content_with_weight'][: int(base['content_prefix_chars_int'])])}", flush=True)
snapshot("after destroy edit", destroy_edit)
store("edited_destroy", destroy_edit)

store("original", base)
ids, field, ranks = asyncio.run(search_and_retrieve())

print("\n===== boundaries 4-5: search result =====", flush=True)
print(f"  query='内衬层厚度' window={len(ids)} returned ids={ids}", flush=True)
for cid in ids:
    print(f"    {cid}: doc_id={field[cid].get('doc_id')} content={content_hash(field[cid].get('content_with_weight'))} "
          f"fields={ {f: field[cid][f] for f in FIELDS if f in field[cid]} }", flush=True)

print("\n===== boundaries 6-9: final chunks from Dealer.retrieval =====", flush=True)
final_by_doc = {}
for chunk in ranks["chunks"]:
    final_by_doc[chunk.get("doc_id")] = chunk
    extent = snapshot(f"final {chunk.get('doc_id')}", chunk)
    mode = (chunk.get("score_provenance") or {}).get("mode")
    body = _body_text(chunk)
    print(f"      mode={mode} body_hash={content_hash(body)} body_len={len(body)} "
          f"carries_220={carries_value(chunk, ('220',))} carries_15={carries_value(chunk, ('1.5',))}", flush=True)

print("\n===== CLASSIFICATION =====", flush=True)
for doc_id, label in (("original", "EDITED_CHUNK"), ("edited_append", "APPEND_EDITED_CHUNK"), ("edited_destroy", "DESTROY_EDITED_CHUNK")):
    in_search = doc_id in {field[cid].get("doc_id") for cid in ids}
    in_final = doc_id in final_by_doc
    print(f"  {label} doc_id={doc_id}: RETURNED_BY_SEARCH={in_search} RETURNED_BY_RETRIEVAL={in_final}", flush=True)

retrieved_append = final_by_doc.get("edited_append")
retrieved_destroy = final_by_doc.get("edited_destroy")
if retrieved_append is not None:
    extent = doc_context.verified_prefix_extent(retrieved_append)
    print(f"  append edit through the final boundary: verified_extent={extent} body={_body_text(retrieved_append)!r} "
          f"carries_220={carries_value(retrieved_append, ('220',))}", flush=True)
if retrieved_destroy is not None:
    extent = doc_context.verified_prefix_extent(retrieved_destroy)
    whole = retrieved_destroy["content_with_weight"]
    print(f"  destroy edit through the final boundary: verified_extent={extent} "
          f"body_is_whole={_body_text(retrieved_destroy) == whole} carries_220={carries_value(retrieved_destroy, ('220',))}", flush=True)

# --- control: invalidation then legitimate reprojection --------------------------------------
print("\n===== REPROJECTION CONTROL =====", flush=True)
from rag.nlp import retrieval_projection  # noqa: E402

control = dict(destroy_edit)
snapshot("invalidated", control)
metadata = retrieval_projection.resolve_metadata([], title=doc_context.document_title(NAME), category="power_cable")
retrieval_projection.apply_projection(control, metadata)
extent = snapshot("after reprojection", control)
store("reprojected_control", control)
_ids, _field, _ranks = asyncio.run(search_and_retrieve())
control_final = [c for c in _ranks["chunks"] if c.get("doc_id") == "reprojected_control"]
if control_final:
    chunk = control_final[0]
    print(f"  control through the final boundary: verified_extent={doc_context.verified_prefix_extent(chunk)} "
          f"body={_body_text(chunk)!r} carries_220={carries_value(chunk, ('220',))}", flush=True)
else:
    print("  control chunk was not returned by Dealer.retrieval", flush=True)

requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
print("\nTRACE COMPLETE", flush=True)
