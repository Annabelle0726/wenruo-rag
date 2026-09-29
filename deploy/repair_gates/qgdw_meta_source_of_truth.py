"""Read-only: where does document metadata come from, and why did Part 3 miss standard_no/year?

Prints the KB's metadata configuration, every document-metadata record in the KB, and the raw stored
record for the three standards so the Part 2 / Part 3 production paths can be compared.
"""
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

kb = Knowledgebase.get_by_id(KB)
cfg = kb.parser_config or {}
print("KB name                 :", kb.name)
print("KB parser_id            :", kb.parser_id)
print("KB parser_config keys   :", sorted(cfg))
for key in ("metadata", "enable_metadata", "auto_metadata", "metadata_config", "field_map"):
    if key in cfg:
        print(f"  parser_config[{key!r}] = {json.dumps(cfg[key], ensure_ascii=False)[:600]}")

index_name = DocMetadataService._get_doc_meta_index_name(kb.tenant_id)
print("\ndoc-metadata index      :", index_name)
order_by = OrderByExpr()
if not settings.DOC_ENGINE_INFINITY:
    order_by.asc("id")
batch = settings.docStoreConn.search(
    select_fields=["*"], highlight_fields=[], condition={"kb_id": [KB]}, match_expressions=[],
    order_by=order_by, offset=0, limit=1000, index_names=index_name, knowledgebase_ids=[KB])
docs = list(DocMetadataService._iter_search_results(batch))
print(f"records in KB           : {len(docs)}")
for doc_id, doc in docs:
    print(f"\n  doc {doc_id}")
    print(f"     _extract_metadata -> {json.dumps(DocMetadataService._extract_metadata(doc), ensure_ascii=False)}")
    raw = {k: v for k, v in doc.items() if k in ("id", "doc_id", "kb_id", "meta_fields", "create_time", "update_time")}
    print(f"     raw record        -> {json.dumps(raw, ensure_ascii=False)[:700]}")
