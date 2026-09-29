"""Per-document metadata rows for the two authoritative documents. Read-only."""
import json
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import DocMetadata  # noqa: E402
from api.db.services.doc_metadata_service import DocMetadataService  # noqa: E402

KB = "9463d93eb97511f1938f2592e9bc6fe4"
PART1, PART2, PART3 = "b1a2c3d4", "28668474ba1b11f1be9555eabe501d5b", "f18db09cba1211f18bee33eac9b39c66"

for label, doc in (("PART2", PART2), ("PART3", PART3)):
    rows = []
    for row in DocMetadata.select().where((DocMetadata.kb_id == KB) & (DocMetadata.doc_id == doc)).dicts():
        rows.append({k: str(row.get(k)) for k in ("meta_key", "meta_value")})
    print(f"{label} {doc}: {len(rows)} metadata rows -> {json.dumps(rows, ensure_ascii=False)}")

flat = DocMetadataService.get_flatted_meta_by_kbs([KB])
print()
print("flatted standard_no ->", json.dumps(flat.get("standard_no"), ensure_ascii=False))
print("flatted year        ->", json.dumps(flat.get("year"), ensure_ascii=False))
print()
print("Does any metadata row in this KB mention 73286.3 ?")
hits = [r for r in DocMetadata.select().where(DocMetadata.kb_id == KB).dicts()
        if "73286.3" in str(r.get("meta_value")) or "73286.3" in str(r.get("meta_key"))]
print(f"  rows found: {len(hits)}", json.dumps([{k: str(h.get(k)) for k in ('doc_id', 'meta_key', 'meta_value')} for h in hits[:10]], ensure_ascii=False))
