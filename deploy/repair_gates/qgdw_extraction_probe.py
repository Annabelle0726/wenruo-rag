"""Read-only: what does the authoritative extractor yield for the Part 3 document TODAY?

Runs `auto_tag` (the same call the ingest makes) WITHOUT persisting, on the document's real chunks, so
the root cause can be stated from evidence: if the extractor yields standard_no/year now, the original
omission was a historical ingest outcome; if it does not, the attribute genuinely cannot be derived and
the repair had to supply it.
"""
import asyncio
import json
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Knowledgebase  # noqa: E402
from api.db.services.doc_metadata_service import DocMetadataService  # noqa: E402
from rag.nlp.auto_metadata import auto_tag, document_text, LLM_SCAN_CHARS  # noqa: E402
from rag.svr.auto_metadata_service import resolve_chat_model  # noqa: E402
from rag.utils.es_conn import OrderByExpr  # noqa: E402

KB = "9463d93eb97511f1938f2592e9bc6fe4"
PART3 = "f18db09cba1211f18bee33eac9b39c66"
PART3_NAME = "220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范.pdf"
PART2 = "28668474ba1b11f1be9555eabe501d5b"
PART2_NAME = "220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"

kb = Knowledgebase.get_by_id(KB)
llm_id = (kb.parser_config or {}).get("llm_id")
index = "ragflow_" + kb.tenant_id


def fetch_chunks(doc_id, limit=24):
    order_by = OrderByExpr()
    raw = settings.docStoreConn.search(
        select_fields=["content_with_weight"], highlight_fields=[], condition={"doc_id": [doc_id]},
        match_expressions=[], order_by=order_by, offset=0, limit=limit,
        index_names=index, knowledgebase_ids=[KB])
    out = []
    for item in DocMetadataService._iter_search_results(raw):
        # _iter_search_results yields (id, doc)
        out.append(item[1] if isinstance(item, tuple) else item)
    return out


llm = resolve_chat_model(kb.tenant_id, llm_id, kb.language or "Chinese")
print("chat model resolved:", llm is not None)

for label, doc_id, name in (("PART2", PART2, PART2_NAME), ("PART3", PART3, PART3_NAME)):
    chunks = fetch_chunks(doc_id)
    print(f"\n=== {label}: {len(chunks)} chunks fetched; "
          f"first chunk type={type(chunks[0]).__name__ if chunks else 'n/a'}")
    text = document_text(chunks, limit=LLM_SCAN_CHARS)
    print(f"    head-scan text: {len(text)} chars")
    print(f"    head excerpt : {' '.join(text.split())[:180]}")
    result = asyncio.run(auto_tag(name, text, llm=llm))
    print(f"    auto_tag source={result.source!r}")
    print(f"    auto_tag fields={json.dumps(result.fields, ensure_ascii=False)}")
    print(f"    CURRENTLY STORED={json.dumps(DocMetadataService.get_document_metadata(doc_id) or {}, ensure_ascii=False)}")
