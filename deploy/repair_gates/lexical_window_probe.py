"""Dump the pure-lexical candidate windows, identically, in production AND in the isolated replay.

The point is comparability: the same questions, the same parameters, the same code path
(`embd_mdl=None`, so no provider and no dense leg), dumped as full ordered id lists with their ES
scores. Diffing the two dumps localises any harness fidelity gap to an exact chunk position
instead of leaving it as "the numbers differ by one".

Read-only. Writes only /tmp/lexical_window_probe.json inside whichever container it runs in.
"""
import asyncio
import json
import pathlib
import sys
import time

sys.path.insert(0, "/ragflow")
import common.settings  # noqa: F401  (import-order fix for the Redis-dependent import chain)

if not pathlib.Path("/ragflow/conf/service_conf.yaml").exists():
    raise SystemExit("service_conf.yaml missing")

FIXTURE = pathlib.Path("/tmp/corpus.json")
ISOLATED = FIXTURE.exists()
if ISOLATED:
    from common import settings

    settings.ES = {"hosts": "http://repair-es:9200"}
else:
    from common import settings

    settings.init_settings()

from rag.nlp.search import Dealer, _chunk_scalar, is_kb_scoped_chunk
from rag.utils.es_conn import ESConnection

KB = "9463d93eb97511f1938f2592e9bc6fe4"
TENANT = "a9e28731ab7011f19b833887d563fb04"
INDEX = "ragflow_" + TENANT
THREE = "d1d75672f2dbc333"
SINGLE = "b5aaf72bcd33d44a"
INCIDENT = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
CONTROL = "根据 Q/GDW 73286.2-2026 表 1，单芯电缆的导体标称截面有哪些规格？"
STRUCTURE = "220kV 三芯海缆的主要结构有哪些？"


def make_dealer(store):
    dealer = Dealer(store)
    if not ISOLATED:
        return dealer
    documents = {doc["id"] for doc in json.loads(pathlib.Path("/tmp/sql-documents.json").read_text(encoding="utf-8-sig"))}
    corpus = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
    now = time.time()
    for hit in corpus["hits"]:
        source = hit.get("_source") or {}
        if is_kb_scoped_chunk(source):
            continue
        doc_id = _chunk_scalar(source.get("doc_id"))
        if doc_id:
            dealer._doc_exists_cache[doc_id] = (now, doc_id in documents)
    return dealer


def req(question, page):
    return {"question": question, "kb_ids": [KB], "page": page, "size": 30, "similarity": 0.55, "vector_similarity_weight": 0.25, "available_int": 1, "must_not": {"exists": "compile_kwd"}}


async def window(dealer, store, question, page):
    captured = {}

    def capture(*a, **kw):
        result = original(*a, **kw)
        captured["ids"] = [str(i) for i in store.get_doc_ids(result)]
        raw_scores = store.get_scores(result)
        if isinstance(raw_scores, dict):
            raw_scores = [raw_scores.get(chunk_id) for chunk_id in captured["ids"]]
        captured["scores"] = [None if s is None else round(float(s), 6) for s in raw_scores]
        captured["limit"] = a[6]
        return result

    original = store.search
    store.search = capture
    try:
        result = await dealer.search(req(question, page), [INDEX], [KB], None, rank_feature=None, min_match=True)
    finally:
        store.search = original
    return {"requested_page": page, "es_window_size": len(captured.get("ids", [])), "es_ids": captured.get("ids", []), "es_scores": captured.get("scores", []), "pruned_size": len(result.ids), "pruned_total": int(result.total)}


async def main():
    store = ESConnection()
    dealer = make_dealer(store)
    out = {"environment": "isolated_repair_es" if ISOLATED else "production", "index": INDEX, "document_rows": None if not ISOLATED else len(json.loads(pathlib.Path("/tmp/sql-documents.json").read_text(encoding="utf-8-sig")))}
    for name, question in (("INCIDENT", INCIDENT), ("CONTROL", CONTROL), ("STRUCTURE", STRUCTURE)):
        pages = [await window(dealer, store, question, page) for page in (1, 2)]
        flat = []
        for page in pages:
            flat.extend(page["es_ids"])
        for page in pages:
            for index, chunk_id in enumerate(page["es_ids"]):
                page.setdefault("ranks", {})[chunk_id] = (page["requested_page"] - 1) * 30 + index + 1
        out[name] = {
            "pages": pages,
            "ordered_window": flat,
            "three_rank": flat.index(THREE) + 1 if THREE in flat else None,
            "single_rank": flat.index(SINGLE) + 1 if SINGLE in flat else None,
        }
    pathlib.Path("/tmp/lexical_window_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("WINDOW_PROBE_BEGIN")
    print(json.dumps({name: {"three_rank": out[name]["three_rank"], "single_rank": out[name]["single_rank"], "window": out[name]["ordered_window"][:6]} for name in ("INCIDENT", "CONTROL", "STRUCTURE")}, ensure_ascii=False))
    print("WINDOW_PROBE_END")


if __name__ == "__main__":
    asyncio.run(main())
