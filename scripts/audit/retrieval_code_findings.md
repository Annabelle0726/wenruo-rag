## 9. Static code findings (read-only, deployed revision)

These were obtained by reading the deployed files inside the running container. Nothing was modified,
copied over, patched, restarted, or reconfigured, and Elasticsearch was accessed with GET requests only.

### 9.1 Query decomposition does call an LLM, with sampling left at provider defaults

- `rag/retrieval/decomposition.py:390` — `result = await gen_json(rendered, "Output:\n", chat_mdl)`, which
  reaches `rag/llm/chat_model.py:1013` — `chat.completions.create(model=..., messages=history, **gen_conf, **kwargs)`
  with `gen_conf` left at its `{}` default.
- **No `temperature`, `top_p`, `seed`, `max_tokens`, or `stream` is set anywhere on that path**, so the
  provider's default sampling applies. This is the only genuine source of run-to-run variation found in
  the retrieval package.
- The call is gated by `looks_composite(question)` (`pipeline.py:268`) together with
  `chat_mdl is None or max_sub_queries <= 0` (`decomposition.py:386`). It is **not** gated by
  `max_sub_queries > 1`.
- `chat_mdl is None` returns `[]` — decomposition is simply skipped, with **no deterministic splitting
  fallback**. The pipeline's own comparative/clause routes are separate and are LLM-free.
- The result is **memoized in Redis for 24 h** (`generator.py:574/587`, `graphrag/utils.py:170-187`); no
  `lru_cache` exists. Observation from this round: 360 `decompose_question` calls produced only **3**
  actual chat-model calls, i.e. almost every decomposition in this round was served from the warm cache.
- Decomposition returns a plain `list[str]` (`decomposition.py:377`): route entries are strings with **no**
  per-route `top_k`.

### 9.2 `routes_top_k = 20` provenance — a hardcoded router constant, not a configuration leak

- `rag/retrieval/query_router.py:69` — `NUMERIC_TOP_K = 20`, returned at `query_router.py:167`, applied at
  `pipeline.py:242` — `routes_top_k = max(decision.routes_top_k, required)`, and warned about at
  `multi_route.py:105` (`routes_top_k=20 is outside the recommended 10-15 band`).
- Ruled out as sources: the `routes_top_k` parameter default (12), the decomposition output, and any config
  file or environment variable — `routes_top_k` does not appear anywhere under `/ragflow/conf`.
- **Provenance: `NUMERIC_TOP_K = 20` (numeric-query router constant) → `max()` at `pipeline.py:242` →
  effective value 20 for numeric-standard questions.** Per this round's instruction the value was left
  exactly as deployed and only recorded.

### 9.3 No deterministic tie-breaker exists on the ordering path

- `multi_route.py:195` and `rerank.py:321` sort by score only; `select_context` ends with
  `[chunk for chunk in ordered if chunk_key(chunk) in chosen_keys]` (`rerank.py:563`). Ties therefore
  resolve purely through Python's stable sort on **pool insertion order** — there is no secondary key such
  as `_id`, `chunk_id`, or `doc_id`.
- No `set` / `sorted(set(...))` / dict-iteration construct determines candidate order in the package.
- No `random`, `uuid`, `time`, or string `hash()` is used anywhere in `/ragflow/rag/retrieval/`; the only
  hashing is content-addressed `hashlib.sha1` (`chunk_profile.py:244`).

### 9.4 Dense retrieval is approximate kNN over two shards

- `rag/nlp/es_conn.py:263-270` builds `s.knn(field, k, num_candidates, query_vector=..., filter=bool_query.to_dict(), similarity=similarity)`.
  There is **no `script_score`** path (NOT FOUND).
- Defaults: `knn_top_k = 1024`, `knn_num_candidates = 2048` (`rag/nlp/search.py:255-256`).
- `tie_breaker`: **NOT FOUND**. `boost` appears only at `es_conn.py:250-251`, where it evaluates to
  `bool_query.boost = 0.0` because the ES fusion weights are hardcoded `"0.001,1"`.
- The kNN `filter` includes the lexical `query_string`; the helper intended to strip it
  (`es_conn.py:75-97`) is **dead code**.
- Live store: `conf/service_conf.yaml:37-40` → `http://es01:9200`, **Elasticsearch 8.11.3**. Index
  `ragflow_a9e28731ab7011f19b833887d563fb04`: `number_of_shards = 2`, `number_of_replicas = 0`,
  `refresh_interval = 1000ms` (`conf/mapping.json:4-6`). `q_3072_vec` = `dense_vector, dims 3072, index
  true, similarity cosine`, with **no `index_options`**, so Elasticsearch HNSW defaults apply
  (`m`/`ef_construction`/`ef_search` NOT FOUND). **Two shards means per-shard merge order is in play.**
- Not used: `dfs_query_then_fetch` (only a comment in `opensearch_conn.py:472`), `preference`, `scroll`,
  `terminate_after`. `search_after` is unreachable on the dense routes (`es_conn.py:303`). `size` differs
  per route/caller (route cut `routes_top_k`, ES fetch `rerank_candidates_count`, second KNN leg
  `len(sres.ids)`).

### 9.5 The final cut, and why ES itself is not the culprit

- Cut: `np.argsort(sim_np * -1, kind="stable")` → threshold filter → `valid_idx[begin:end]`
  (`rag/nlp/search.py:848-863`). The sort is stable but has **no explicit tie-breaker**.
- Fusion is computed Python-side (`search.py:626-628`) from the local `term_similarity` and the
  Elasticsearch-returned cosine; the final window is the retrieval module's `final_top_n`
  (`rerank.py:94` default 8; the live canary kept 12 candidates into the selection step).
- **Direct determinism check (subagent, read-only GET):** three identical kNN probes against the frozen
  index returned **bit-identical** results. Combined with 9.4 this says Elasticsearch is deterministic for
  a fixed input, so a changing window must come from a changed **input** — the query text/sub-queries, the
  query embedding, or mutable ranking state — not from Elasticsearch wandering on its own.
- **OBSERVED IN LOGS:** the same question with reportably identical routes produced pools of
  `25/25/27/27/27` drawn from 1-3 documents, with final cuts of `0 prose / 12 table` versus
  `11 prose / 1 table` — indicative of a pool-composition-sensitive adjustment (table/prose dominance)
  rather than of random ordering. Provenance: log reading, not a controlled experiment; it motivated the
  stage-capture probe in section 10.

### 9.6 What can and cannot differ between two identical calls

Can differ: sub-queries from the LLM decomposition path (provider-default sampling, currently masked by the
24 h Redis cache), the query embedding if the embedding service is not bit-reproducible, per-shard merge
order for the approximate kNN leg on a 2-shard index, and any tie resolved by pool insertion order.
Cannot differ from the code read: the fusion formula, the sort implementation, the threshold filter, and the
slice bounds — all are pure functions of their inputs.
