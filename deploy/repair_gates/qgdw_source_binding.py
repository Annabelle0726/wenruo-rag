"""Source binding: the document row behind the pinned Part 3 chunk. Read-only."""
import json
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Document, File  # noqa: E402

DOC_ID = "f18db09cba1211f18bee33eac9b39c66"
out = {}
row = Document.get_or_none(Document.id == DOC_ID)
if row is None:
    out["document_row"] = "NOT FOUND"
else:
    out["document_row"] = {k: str(getattr(row, k, None)) for k in
                           ("id", "kb_id", "name", "location", "size", "type", "parser_id",
                            "chunk_num", "token_num", "run", "progress", "status")}
    fid = getattr(row, "id", None)
    frow = File.get_or_none(File.id == fid)
    out["file_row"] = {k: str(getattr(frow, k, None)) for k in ("id", "name", "location", "size", "type")} if frow else "NOT FOUND"

print(json.dumps(out, ensure_ascii=False, indent=1))
