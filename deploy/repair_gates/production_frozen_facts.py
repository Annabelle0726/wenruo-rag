"""READ-ONLY production probe for the four frozen Q/GDW lexical facts.

Run in the production container, on the DEPLOYED code, with no mutation of any kind: only
`Dealer.search` / `Dealer.retrieval` reads against the live ES index and the MySQL doc-existence
cache. Nothing is written to ES, MySQL, Redis or any file inside the container.

Purpose: the isolated replay must be shown to reproduce these facts, or the difference must be
named. Both are measured here so the frozen numbers are pinned to production rather than to a
fixture.
"""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()
from rag.nlp import search as rag_search
from rag.utils.es_conn import ESConnection

KB = "9463d93eb97511f1938f2592e9bc6fe4"
TENANT = "a9e28731ab7011f19b833887d563fb04"
INDEX = "ragflow_" + TENANT
THREE = "d1d75672f2dbc333"
SINGLE = "b5aaf72bcd33d44a"
INCIDENT = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
CONTROL = "根据 Q/GDW 73286.2-2026 表 1，单芯电缆的导体标称截面有哪些规格？"
STRUCTURE = "220kV 三芯海缆的主要结构有哪些？"


def base_req(question, page=1):
    return {"question": question, "kb_ids": [KB], "page": page, "size": 30, "similarity": 0.55, "vector_similarity_weight": 0.25, "available_int": 1, "must_not": {"exists": "compile_kwd"}}


async def window_for(dealer, store, question, page=1):
    """The pure-lexical (embd_mdl=None) candidate window, plus its captured ES ids."""
    captured = {}
    original = store.search

    def capture(*a, **kw):
        result = original(*a, **kw)
        captured["ids"] = list(store.get_doc_ids(result))
        captured["limit"] = a[6]
        captured["expressions"] = [type(e).__name__ for e in a[3]]
        return result

    store.search = capture
    try:
        result = await dealer.search(base_req(question, page), [INDEX], [KB], None, rank_feature=None, min_match=True)
    finally:
        store.search = original
    return result, captured


async def main():
    store = ESConnection()
    dealer = rag_search.Dealer(store)
    out = {"index": INDEX, "mode": "READ_ONLY pure lexical (embd_mdl=None)"}

    async def rank_of(question, target):
        found = None
        for page in (1, 2, 3):
            result, captured = await window_for(dealer, store, question, page=page)
            ids = list(result.ids)
            if target in ids:
                found = (page - 1) * 30 + ids.index(target) + 1
                break
        return found

    incident_rank_three = await rank_of(INCIDENT, THREE)
    incident_rank_single = await rank_of(INCIDENT, SINGLE)
    control_rank_single = await rank_of(CONTROL, SINGLE)
    structure_rank_three = await rank_of(STRUCTURE, THREE)

    out["facts"] = {
        "incident_three_rank": incident_rank_three,
        "incident_three_in_30_window": bool(incident_rank_three and incident_rank_three <= 30),
        "incident_single_rank": incident_rank_single,
        "incident_single_in_30_window": bool(incident_rank_single and incident_rank_single <= 30),
        "control_single_rank": control_rank_single,
        "control_single_in_window": bool(control_rank_single and control_rank_single <= 30),
        "structure_three_rank": structure_rank_three,
        "structure_three_in_window": bool(structure_rank_three and structure_rank_three <= 30),
    }
    result, captured = await window_for(dealer, store, CONTROL)
    out["control_window"] = {
        "limit": captured.get("limit"),
        "expressions": captured.get("expressions"),
        "window_size": len(captured.get("ids", [])),
        "single_rank_in_window": (captured.get("ids", []).index(SINGLE) + 1) if SINGLE in captured.get("ids", []) else None,
        "returned_count": len(result.ids),
        "returned_head": list(result.ids)[:10],
    }

    pathlib.Path("/tmp/production_frozen_facts.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PROD_FACTS_BEGIN")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("PROD_FACTS_END")


if __name__ == "__main__":
    asyncio.run(main())
