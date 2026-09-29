"""The metadata the filter model actually sees, per document, via the same call the loader makes."""
import json
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Knowledgebase  # noqa: E402
from api.db.services.doc_metadata_service import DocMetadataService  # noqa: E402
from rag.utils.es_conn import OrderByExpr  # noqa: E402

KB = "9463d93eb97511f1938f2592e9bc6fe4"
PART2, PART3 = "28668474ba1b11f1be9555eabe501d5b", "f18db09cba1211f18bee33eac9b39c66"

print("DOC_ENGINE_INFINITY:", getattr(settings, "DOC_ENGINE_INFINITY", None))
print("docStoreConn class :", type(settings.docStoreConn).__name__)

kb = Knowledgebase.get_by_id(KB)
index_name = DocMetadataService._get_doc_meta_index_name(kb.tenant_id)
order_by = OrderByExpr()
if not settings.DOC_ENGINE_INFINITY:
    order_by.asc("id")

batch = settings.docStoreConn.search(
    select_fields=["*"], highlight_fields=[], condition={"kb_id": [KB]}, match_expressions=[],
    order_by=order_by, offset=0, limit=1000, index_names=index_name, knowledgebase_ids=[KB])

docs = list(DocMetadataService._iter_search_results(batch))
print(f"records returned: {len(docs)}")
found = {}
for doc_id, doc in docs:
    if doc_id in (PART2, PART3):
        found[doc_id] = DocMetadataService._extract_metadata(doc)
    if len(found) == 2:
        break

for label, did in (("PART2", PART2), ("PART3", PART3)):
    meta = found.get(did)
    print(f"\n{label} {did}")
    print(f"   metadata visible to the filter model: {json.dumps(meta, ensure_ascii=False)}")

print("\nALL record ids seen:")
ids = [d for d, _ in docs]
print("  ", json.dumps(ids[:12], ensure_ascii=False), f"... total {len(ids)}")
print("  PART2 present:", PART2 in ids, " PART3 present:", PART3 in ids)
