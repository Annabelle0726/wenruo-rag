"""GROUP F - the real retrieval closure chain, executed on the candidate image's own product modules.

The chain the release must close, asserted link by link and never inferred from the absence of an
exception:

    Dealer.search  ->  Dealer.retrieval  ->  _body_text  ->  carries_value

Every call resolves to `/ragflow/...` inside the candidate image. The only external fixture is a
disposable index in the isolated repair ES. No production datastore is read or written.

The final pair of assertions is the differential that keeps the group non-vacuous: a chunk WITHOUT
verified provenance must return its whole content and remain evidence, so a PASS on the provenanced
chunk cannot be produced by `_body_text` being unconditionally lossy.
"""
import asyncio
import hashlib
import json
import pathlib
import sys
import traceback

sys.path.insert(0, "/ragflow")

TENANT = "phase4closure"
INDEX = f"ragflow_{TENANT}"
KB = "kb-phase4-closure"
NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
BODY = "5.3.4 内衬层厚度应不小于1.5mm，外被层应光滑无缺陷。"
HEADER_ONLY_TOKEN = ("220",)
BODY_TOKEN = ("1.5",)

FAILURES = []
COUNTS = {"executed": 0, "failed": 0}


def check(label, observed, expected, ok=None):
    passed = (observed == expected) if ok is None else bool(ok)
    COUNTS["executed"] += 1
    if not passed:
        COUNTS["failed"] += 1
        FAILURES.append(f"F::{label}: observed={observed!r} expected={expected!r}")
    print(f"  [{'PASS' if passed else 'FAIL'}] F::{label}: observed={observed!r} expected={expected!r}", flush=True)
    return passed


def verdict():
    if COUNTS["executed"] == 0:
        return "ABORTED"
    return "FAIL" if COUNTS["failed"] else "PASS"


def _abort(exc_type, exc, tb):
    traceback.print_exception(exc_type, exc, tb)
    print(f"VERDICT GROUP_F_FINAL_RETRIEVAL_CLOSURE = ABORTED   assertions={COUNTS['executed']} "
          f"failed={COUNTS['failed']}", flush=True)
    print(f"ABORTED_BY {exc_type.__name__}: {exc}", flush=True)


sys.excepthook = _abort

import requests  # noqa: E402
import yaml  # noqa: E402

from common import settings  # noqa: E402

settings.init_settings()

from rag.nlp import doc_context, rag_tokenizer  # noqa: E402
from rag.nlp import search as rag_search  # noqa: E402
from rag.retrieval.chunk_profile import carries_value, _body_text  # noqa: E402

print("===== GROUP F: real retrieval closure chain =====", flush=True)

conf = yaml.safe_load(pathlib.Path("/ragflow/conf/service_conf.yaml").read_text(encoding="utf-8"))["es"]
host = str(conf["hosts"]).rstrip("/")
auth = (conf.get("username"), conf.get("password"))
check("isolated datastore host", host, "http://repair-es:9200",
      ok="es01" not in host and "repair-es" in host)

for module in (rag_search, doc_context):
    inside = str(pathlib.Path(module.__file__).resolve()).startswith("/ragflow/")
    check(f"module {module.__name__} resolves inside the image", inside, True, ok=inside)
    print(f"    {module.__name__} -> {module.__file__}", flush=True)

mapping = json.loads(pathlib.Path("/ragflow/conf/mapping.json").read_text(encoding="utf-8"))
requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
created = requests.put(f"{host}/{INDEX}", auth=auth, timeout=60,
                       json={"settings": mapping.get("settings", {}), "mappings": mapping.get("mappings", {})})
check("disposable index created", created.status_code, 200, ok=created.status_code in (200, 201))
requests.post(f"{host}/{INDEX}/_refresh", auth=auth, timeout=30)

FIELDS = doc_context.PREFIX_FIELDS


def produce():
    chunk = {"content_with_weight": BODY, "doc_id": "closure", "docnm_kwd": NAME,
             "content_ltks": "", "content_sm_ltks": ""}
    doc_context.apply_document_context([chunk], NAME, language="Chinese")
    return chunk


provenanced = produce()
# Same bytes as the provenanced chunk but with NO provenance fields. The only difference between the
# two arms is therefore verified provenance itself, so the differential isolates exactly what
# provenance changes at the final boundary.
legacy = {"content_with_weight": provenanced["content_with_weight"], "doc_id": "closure-legacy",
          "docnm_kwd": NAME}

check("producer emitted the provenance quartet", [f for f in FIELDS if f in provenanced], list(FIELDS))
check("producer extent covers the injected header",
      int(provenanced["content_prefix_chars_int"]) > 0, True,
      ok=int(provenanced["content_prefix_chars_int"]) == len(provenanced["content_with_weight"]) - len(BODY))

for chunk in (provenanced, legacy):
    content = chunk["content_with_weight"]
    document = {"id": f"{chunk['doc_id']}-c", "doc_id": chunk["doc_id"], "kb_id": KB, "docnm_kwd": NAME,
                "available_int": 1, "content_with_weight": content,
                "content_ltks": rag_tokenizer.tokenize(content), "doc_type_kwd": "text"}
    for field in FIELDS:
        if field in chunk:
            document[field] = chunk[field]
    status = requests.post(f"{host}/{INDEX}/_doc/{chunk['doc_id']}-c?refresh=true",
                           auth=auth, timeout=30, json=document).status_code
    check(f"stored {chunk['doc_id']}", status, 200, ok=status in (200, 201))

requests.post(f"{host}/{INDEX}/_refresh", auth=auth, timeout=30)


def dealer():
    d = rag_search.Dealer(settings.docStoreConn)

    async def keep(result):
        return result

    d._prune_deleted_chunks = keep
    return d


# --- link 1: Dealer.search -----------------------------------------------------------------------------
async def do_search():
    return await dealer().search(
        {"question": "内衬层厚度", "page": 1, "size": 5, "similarity": 0.0, "vector": True},
        [INDEX], [KB], None, False)


search_result = asyncio.run(do_search())
check("Dealer.search returned a retrieval mode", getattr(search_result, "retrieval_mode", None), "LEXICAL_ONLY")
search_ids = list(search_result.ids)
check("Dealer.search returned ranked ids", len(search_ids) > 0, True, ok=len(search_ids) > 0)
check("Dealer.search surfaced the provenanced chunk", "closure-c" in search_ids, True,
      ok="closure-c" in search_ids)
print(f"  search ids: {search_ids}", flush=True)


# --- link 2: Dealer.retrieval --------------------------------------------------------------------------
async def do_retrieval():
    return await dealer().retrieval(
        question="内衬层厚度", embd_mdl=None, tenant_ids=[TENANT], kb_ids=[KB], page=1, page_size=10,
        similarity_threshold=0.0, vector_similarity_weight=0.3, rerank_mdl=None, rank_feature=None)


retrieved = asyncio.run(do_retrieval())
final = {c.get("doc_id"): c for c in retrieved["chunks"]}
check("Dealer.retrieval returned chunks", len(retrieved["chunks"]) > 0, True, ok=len(retrieved["chunks"]) > 0)
check("Dealer.retrieval carried the provenanced chunk through", "closure" in final, True, ok="closure" in final)
check("Dealer.retrieval carried the legacy chunk through", "closure-legacy" in final, True,
      ok="closure-legacy" in final)
print(f"  retrieval doc_ids: {sorted(final)}", flush=True)

chunk = final["closure"]

# --- link 3: _body_text over verified provenance -------------------------------------------------------
extent = doc_context.verified_prefix_extent(chunk)
check("verified provenance survives to the final boundary", extent is not None, True, ok=extent is not None)
check("-- the four fields arrived intact",
      [f for f in FIELDS if f in chunk],
      list(FIELDS))
check("_body_text strips the verified header", _body_text(chunk), BODY)
check("_body_text did not silently return the raw field", _body_text(chunk), chunk["content_with_weight"],
      ok=_body_text(chunk) != chunk["content_with_weight"])

# --- link 4: carries_value over body-only text ---------------------------------------------------------
check("body evidence is visible to carries_value", carries_value(chunk, BODY_TOKEN), True)
check("header contaminant is NOT evidence", carries_value(chunk, HEADER_ONLY_TOKEN), False)


# --- non-vacuity differential: no provenance => whole content is evidence ------------------------------
control = final["closure-legacy"]
check("both arms carry byte-identical content", control["content_with_weight"], chunk["content_with_weight"])
check("control chunk has no provenance", doc_context.verified_prefix_extent(control), None)
check("control content is returned whole", _body_text(control), chunk["content_with_weight"])
check("control header text is still evidence", carries_value(control, HEADER_ONLY_TOKEN), True)
check("the two arms differ, so the group is not vacuous",
      (_body_text(chunk), carries_value(chunk, HEADER_ONLY_TOKEN)),
      (_body_text(control), carries_value(control, HEADER_ONLY_TOKEN)),
      ok=(_body_text(chunk), carries_value(chunk, HEADER_ONLY_TOKEN))
         != (_body_text(control), carries_value(control, HEADER_ONLY_TOKEN)))

requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)

RESULT = verdict()
print(f"VERDICT GROUP_F_FINAL_RETRIEVAL_CLOSURE = {RESULT}   assertions={COUNTS['executed']} "
      f"failed={COUNTS['failed']}", flush=True)
if FAILURES:
    print(f"FIRST FAILING ASSERTION: {FAILURES[0]}", flush=True)
    raise SystemExit(1)
print("GROUP F PASSED", flush=True)
