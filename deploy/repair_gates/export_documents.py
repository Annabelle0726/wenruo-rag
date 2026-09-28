"""READ-ONLY export of the document rows the retrieval path's prune step consults.

`Dealer._prune_deleted_chunks` drops chunks whose `doc_id` no longer has a MySQL row, so an
isolated replay that cannot reach MySQL behaves DIFFERENTLY from production: with no rows to
consult it keeps chunks production prunes, and every lexical rank shifts by a place or two
(measured: the frozen single-core rank came out 39 instead of 38).

Only `id`, `name` and `kb_id` are selected. No credentials, no API keys, no document content.
"""
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")
from common import settings

settings.init_settings()

from api.db.db_models import Document

rows = [{"id": row["id"], "name": row["name"], "kb_id": row["kb_id"]} for row in Document.select(Document.id, Document.name, Document.kb_id).dicts()]
pathlib.Path("/tmp/sql-documents.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("DOCS_EXPORTED", len(rows))
print("kbs:", sorted({row["kb_id"] for row in rows}))
