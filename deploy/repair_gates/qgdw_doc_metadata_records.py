"""Per-document metadata RECORDS for the two authoritative documents (doc-metadata index). Read-only."""
import json
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Knowledgebase  # noqa: E402
from api.db.services.doc_metadata_service import DocMetadataService  # noqa: E402

KB = "9463d93eb97511f1938f2592e9bc6fe4"
PART2, PART3 = "28668474ba1b11f1be9555eabe501d5b", "f18db09cba1211f18bee33eac9b39c66"

kb = Knowledgebase.get_by_id(KB)
index = DocMetadataService._get_doc_meta_index_name(kb.tenant_id)
print("doc-metadata index:", index)

es = settings.docStoreConn.es
for label, doc in (("PART2", PART2), ("PART3", PART3)):
    body = {"size": 20, "query": {"bool": {"filter": [
        {"terms": {"kb_id": [KB]}},
        {"terms": {"doc_id": [doc]}}]}}}
    try:
        res = es.search(index=index, body=body)
        hits = res["hits"]["hits"]
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: query error {type(exc).__name__}: {exc}"[:200])
        continue
    print(f"\n{label} {doc}: {len(hits)} metadata record(s)")
    for h in hits:
        src = h.get("_source") or {}
        fields = src.get("meta_fields")
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except Exception:  # noqa: BLE001
                pass
        print(f"   meta_fields: {json.dumps(fields, ensure_ascii=False)}")

print()
print("=== does ANY metadata record in this KB carry a 73286.3 value? ===")
res = es.search(index=index, body={"size": 20, "query": {"bool": {"filter": [{"terms": {"kb_id": [KB]}}],
                                                               "must": [{"query_string": {"query": "73286.3",
                                                                                          "fields": ["meta_fields"]}}]}}})
hits = res["hits"]["hits"]
print(f"  matching records: {len(hits)}")
for h in hits[:5]:
    print("   ", json.dumps(h.get("_source"), ensure_ascii=False)[:300])
