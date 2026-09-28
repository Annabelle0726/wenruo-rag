"""Read-only export for an isolated ES replay; run via stdin, never on startup.

Only search/mapping/settings reads. No credentials or vectors are exported.
The replay restores this snapshot to a disposable ES node, never production.

The index's `similarity` block is exported as well, and that is not cosmetic: the mapping's
dynamic template for `*_tks` names the custom `scripted_sim` similarity, so an isolated index
created WITHOUT it rejects the whole mapping with

    mapper_parsing_exception: dynamic template [tks] has invalid content ... similarity [scripted_sim]

which is exactly how an earlier replay harness failed all fourteen of its cases during fixture
setup, before a single retrieval ran.
"""
import json
import sys

sys.path.insert(0, "/ragflow")
from common import settings

settings.ES = settings.get_base_config("es", {})
from rag.utils.es_conn import ESConnection

es = ESConnection().es
index = "ragflow_a9e28731ab7011f19b833887d563fb04"
mapping = es.indices.get_mapping(index=index)[index]["mappings"]
index_settings = es.indices.get_settings(index=index)[index]["settings"]["index"]
hits = es.search(index=index, body={"size": 10000, "query": {"match_all": {}}, "_source": {"excludes": ["q_*_vec"]}}, track_total_hits=True)["hits"]
assert len(hits["hits"]) == hits["total"]["value"]
print("FIXTURE_BEGIN")
print(
    json.dumps(
        {
            "index": index,
            "mapping": mapping,
            "shards": index_settings["number_of_shards"],
            # Named similarities the mapping depends on. Without this the isolated index cannot be
            # created at all; see the module docstring.
            "similarity": index_settings.get("similarity", {}),
            "hits": hits["hits"],
        },
        ensure_ascii=False,
    )
)
print("FIXTURE_END")
