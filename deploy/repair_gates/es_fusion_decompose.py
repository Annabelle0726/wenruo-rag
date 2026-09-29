"""Decompose the emitted ES hybrid scoring so the behavioural key states what ES actually does."""
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from common.doc_store.doc_store_base import MatchDenseExpr, MatchTextExpr, OrderByExpr  # noqa: E402
from rag.nlp.search import build_fusion_expr  # noqa: E402
from rag.utils.es_conn import ESConnection  # noqa: E402

INDEX = "es_fusion_probe"
KB = "kb-probe"
MAPPING = {"properties": {"content_ltks": {"type": "text"}, "kb_id": {"type": "keyword"},
                          "doc_id": {"type": "keyword"},
                          "q_2_vec": {"type": "dense_vector", "dims": 2, "index": True, "similarity": "cosine"}}}
LEX_A = "alpha beta gamma delta epsilon zeta conductor nominal section"
LEX_B = "alpha beta zeta filler unrelated words"
CORPUS = {"A": (LEX_A, [0.0, 1.0]), "B": (LEX_B, [1.0, 0.0]), "C": (LEX_A, [1.0, 0.0])}
QUERY_TEXT = LEX_A
QUERY_VECTOR = [1.0, 0.0]

conn = ESConnection()
client = conn.es
client.indices.delete(index=INDEX, ignore_unavailable=True)
client.indices.create(index=INDEX, mappings=MAPPING)
for name, (lex, vec) in CORPUS.items():
    client.index(index=INDEX, id=name, refresh=True,
                 document={"content_ltks": lex, "content_with_weight": lex, "kb_id": KB, "doc_id": name,
                           "q_2_vec": vec})


def body_for(w, knn=True):
    exprs = [MatchTextExpr(["content_ltks"], QUERY_TEXT, 10, {"minimum_should_match": 0.0})]
    if knn:
        exprs += [MatchDenseExpr("q_2_vec", QUERY_VECTOR, "float", "cosine", 10, {"similarity": 0.0}),
                  build_fusion_expr(10, w)]
    c = ESConnection()
    cap = []
    c._es_search_once = lambda i, q, *a, **k: (cap.append(q), {"timed_out": False, "hits": {"hits": []}})[1]
    c.search(select_fields=[], highlight_fields=[], condition={"kb_id": [KB]}, match_expressions=exprs,
             order_by=OrderByExpr(), offset=0, limit=10, index_names=[INDEX], knowledgebase_ids=[KB])
    return cap[0]


def score(body):
    b = {k: v for k, v in body.items() if k in ("query", "knn", "size", "from", "_source")}
    res = client.search(index=INDEX, body=b)
    return {h["_id"]: round(float(h["_score"]), 6) for h in res["hits"]["hits"]}


print("reference, query only (no knn)      :", score(body_for(0.0, knn=False)))
print("reference, knn only  (no query_str) :",
      score({"knn": {**body_for(0.0)["knn"], "boost": None}, "size": 10}))
print("reference, knn only  boost default  :",
      score({"knn": {**{k: v for k, v in body_for(0.0)["knn"].items() if k != "boost"}, "size": 10}})
                 if False else
                 score({"knn": {"field": "q_2_vec", "k": 10, "num_candidates": 20,
                                "query_vector": QUERY_VECTOR, "similarity": 0.0}, "size": 10}))
for w in (0.0, 0.5, 1.0):
    b = body_for(w)
    print(f"w={w}: bool.boost={b['query']['bool'].get('boost')} knn.boost={b['knn'].get('boost')} "
          f"-> scores {score(b)}")
