# `deploy/repair_gates` — the isolated dense-failure repair harness

Everything here runs against a **disposable** Elasticsearch and Redis on a private Docker network.
Production ES, MySQL, Redis and configuration are never addressed; the only production access is the
read-only fixture export described below.

## Why the harness exists

The incumbent gate suite reported `14 errors, 0 failures` — every case had failed during fixture
**setup**, so the repair had never actually been exercised. Two environment defects caused it:

1. **The isolated index was created without the production index's custom similarity.** The mapping's
   `*_tks` dynamic template names `scripted_sim`, which lives in `index.settings.similarity`, so ES
   rejected the whole mapping with `mapper_parsing_exception: dynamic template [tks] has invalid
   content`. `export_fixture.py` now exports that block and the gate applies it on create.
2. **The image ships a local-dev `conf/service_conf.yaml`** (Redis on `localhost:6379`, ES on
   `127.0.0.1:1200`), so the tokenizer's synonym lookup failed with `Connection refused` even though
   the isolated ES was reachable. The harness points the container's own config at the isolated
   services.

A third defect was found in the gate itself: `_doc_exists_cache` was seeded for the live documents
only. A doc_id with no cache entry falls through to MySQL, which the replay cannot reach, and
`_prune_deleted_chunks` then fail-opens — so chunks production deletes survived and every lexical rank
shifted. The cache is now seeded with the true answer for **every** doc_id the corpus carries.

## Bringing it up

```bash
# 1. private network + disposable services
docker network create wenruo-repair-test
docker run -d --name wenruo-repair-es  --network wenruo-repair-test --network-alias repair-es elasticsearch:8.11.3
docker run -d --name repair-redis       --network wenruo-repair-test --network-alias redis \
  valkey/valkey:8 valkey-server --requirepass infini_rag_flow        # matches the shipped config
docker run -d --name wenruo-repair-gates --network wenruo-repair-test --entrypoint sleep \
  my-wenruorag:p0-7-obs-9f3d2c79 infinity

# 2. mount the code under test into the gate container (the repaired files)
docker run ... -v <repo>/rag/nlp/search.py:/ragflow/rag/nlp/search.py:ro
              -v <repo>/rag/retrieval/multi_route.py:/ragflow/rag/retrieval/multi_route.py:ro
              -v <repo>:/workspace:ro

# 3. read-only fixture export, run INSIDE the production container (no mutation)
docker cp export_fixture.py   wenruo-rag-cpu:/tmp/ && docker exec wenruo-rag-cpu python /tmp/export_fixture.py > /tmp/corpus.json
docker cp export_documents.py wenruo-rag-cpu:/tmp/ && docker exec wenruo-rag-cpu python /tmp/export_documents.py
docker cp wenruo-rag-cpu:/tmp/corpus_reexport.json   wenruo-repair-gates:/tmp/corpus.json
docker cp wenruo-rag-cpu:/tmp/sql-documents.json     wenruo-repair-gates:/tmp/sql-documents.json

# 4. point the container's own config at the isolated services
python patch: conf/service_conf.yaml -> redis.host 'redis:6379', es.hosts 'http://repair-es:9200'

# 5. run the gates
docker exec wenruo-repair-gates bash -lc "cd /ragflow && python -m pytest deploy/repair_gates -q"
```

`/tmp/repair-gate-report.json` is written at session end and holds every measured number the report
cites.

## Files

| file | role |
| --- | --- |
| `test_degradation.py` | the behavioural gates: healthy differential, dense-failure-to-lexical, 60 s blocking timeout, late-result isolation, dense not-triggered, genuine zero-hit, all-evidence-failed, partial/mixed routes, `MIXED_ROUTE_SELECTION_GATE`, the frozen Q/GDW facts, harness fidelity |
| `test_embedding_execution.py` | the mechanism gates: healthy call semantics, contextvar propagation, bounded admission, bounded queue, budget release on success/failure/submit-failure/late worker, twelve-cycle leak test, late result isolation, control-signal classification, cancellation, exit-join semantics |
| `export_fixture.py` | read-only export of the index mapping, the `similarity` block, the index shard count and every `_source` (vector fields excluded) |
| `export_documents.py` | read-only export of the `document` rows `_prune_deleted_chunks` consults, so the replay reproduces production's pruning without a database |
| `lexical_window_probe.py` | dumps ordered lexical windows + ES scores identically in production and in the replay, to localise any fidelity gap to an exact chunk position |
| `production_frozen_facts.py` | read-only measurement of the frozen Q/GDW ranks **on production**, which is the authority for the numbers the replay cannot reproduce |
| `diagnose_failures.py` | the three-case diagnostic that identified the empty healthy side, the STRUCTURE window flip and the single-core rank offset |
| `repair_gate_report.json` | the captured measurement artifact from the passing run |

## The fidelity limit, stated once

The replay reproduces the live document set (486), the shard distribution (251/235), the stored field
lengths and the term statistics **exactly** — verified by dumping all four from both environments. It
cannot reproduce production's `docs_deleted: 42`, and Lucene's collection statistics still count
deleted documents, so the same query over the same live corpus scores each hit slightly differently
(measured: BM25 `3.455974` in production against `3.376191` in the copy for one document and one term,
with identical `freq` and `docFreq`).

Consequences, which the gates encode rather than paper over:

* the replay is evidence for **control flow** and for **window membership**, not for exact scores;
* the frozen Q/GDW facts are asserted as membership (three-core inside the original 30, single-core
  main-question target outside it, single-core control-question target inside it) with **both** ranks
  recorded, never as an exact copy rank;
* the candidate window is never widened to move a target, in either direction;
* the STRUCTURE question's rank is **measured, not asserted**, because it is not one of the operator's
  frozen facts and its membership flips between environments.
