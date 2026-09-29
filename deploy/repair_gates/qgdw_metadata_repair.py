"""Minimal metadata repair for the Part 3 document, via the ingest's OWN metadata path.

Order of operations:
  1. print the current stored record;
  2. re-run the AUTHORITATIVE extraction (`tag_document_metadata` -> `auto_tag`) for this document and
     report what it yields;
  3. compute the proposed record and prove only the missing attributes are added;
  4. persist through `persist_document_metadata` (the same read-modify-write merge the ingest uses, which
     preserves operator/parser fields);
  5. read back and verify.

No chunk, vector, document content, index mapping, retrieval parameter or config is touched.
"""
import asyncio
import json
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Knowledgebase  # noqa: E402
from api.db.services.doc_metadata_service import DocMetadataService  # noqa: E402
from rag.svr.auto_metadata_service import tag_document_metadata, persist_document_metadata  # noqa: E402
from rag.utils.es_conn import OrderByExpr  # noqa: E402

KB = "9463d93eb97511f1938f2592e9bc6fe4"
PART3 = "f18db09cba1211f18bee33eac9b39c66"
PART3_NAME = "220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范.pdf"
REQUIRED = {"standard_no": "Q/GDW 73286.3-2026", "year": "2026"}

kb = Knowledgebase.get_by_id(KB)
llm_id = (kb.parser_config or {}).get("llm_id")

before = DocMetadataService.get_document_metadata(PART3) or {}
print("=== PART3_METADATA_BEFORE ===")
print(json.dumps(before, ensure_ascii=False, indent=1))

# The document's own chunks, as the ingest would pass them (head scan only).
order_by = OrderByExpr()
batch = settings.docStoreConn.search(
    select_fields=["content_with_weight"], highlight_fields=[], condition={"doc_id": [PART3]},
    match_expressions=[], order_by=order_by, offset=0, limit=24,
    index_names="ragflow_" + kb.tenant_id, knowledgebase_ids=[KB])
chunks = [doc for _id, doc in settings.docStoreConn.__class__._iter_search_results(batch)] \
    if hasattr(settings.docStoreConn.__class__, "_iter_search_results") else []
if not chunks:
    from rag.nlp import search as _rs  # noqa: F401
    hits = settings.docStoreConn.search(
        select_fields=["content_with_weight"], highlight_fields=[], condition={"doc_id": [PART3]},
        match_expressions=[], order_by=order_by, offset=0, limit=24,
        index_names="ragflow_" + kb.tenant_id, knowledgebase_ids=[KB])
    chunks = [h.get("_source") if isinstance(h, dict) and "_source" in h else h for h in (hits or [])]
print(f"\nchunks available for the head scan: {len(chunks)}")

print("\n=== authoritative re-extraction (tag_document_metadata) ===")
extracted = asyncio.run(tag_document_metadata(
    doc_id=PART3, name=PART3_NAME, chunks=chunks, tenant_id=kb.tenant_id,
    llm_id=llm_id, language=kb.language or "Chinese"))
print("extraction yielded:", json.dumps(extracted, ensure_ascii=False))

after_extract = DocMetadataService.get_document_metadata(PART3) or {}
print("record after extraction:", json.dumps(after_extract, ensure_ascii=False))

# Ensure the two required attributes exist, using the same supported writer.
missing = {k: v for k, v in REQUIRED.items() if not after_extract.get(k)}
print("\nstill missing after extraction:", json.dumps(missing, ensure_ascii=False))

proposed = dict(after_extract)
proposed.update(missing)
print("\n=== proposed record ===")
print(json.dumps(proposed, ensure_ascii=False, indent=1))

added = set(proposed) - set(after_extract)
print(f"\nattributes ADDED: {sorted(added)}")
print(f"attributes REMOVED: {sorted(set(after_extract) - set(proposed))}")
preserved = all(proposed[k] == v for k, v in after_extract.items() if k not in added)
print(f"all pre-existing values preserved: {preserved}")
assert added <= set(REQUIRED), f"refusing to write: unexpected added attributes {added}"
assert not (set(after_extract) - set(proposed)), "refusing to write: an attribute would be removed"
assert preserved, "refusing to write: a pre-existing value would change"

if missing:
    ok = persist_document_metadata(PART3, missing)
    print(f"\npersist_document_metadata -> {ok}")

final = DocMetadataService.get_document_metadata(PART3) or {}
print("\n=== PART3_METADATA_AFTER ===")
print(json.dumps(final, ensure_ascii=False, indent=1))
print("\nrequired present:", {k: final.get(k) == v for k, v in REQUIRED.items()})
print("previous fields intact:", all(final.get(k) == v for k, v in after_extract.items()))
