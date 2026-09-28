# Controlled Deployed Retrieval Baseline — Query E

Read-only. No assistant was created, modified or borrowed; the experiment states its own
configuration. Captured from the deployed container (`wenruo-rag-cpu`).

## Configuration and provenance

| item | value | provenance |
|---|---|---|
| raw query = effective query | `单芯 220kV 海缆` | EXPLICIT_EXPERIMENT_VALUE (keyword augmentation OFF; `keyword_extraction` not called) |
| similarity_threshold | 0.2 | DEPLOYED_DEFAULT |
| vector_similarity_weight | 0.6 | DEPLOYED_DEFAULT |
| routes_top_k | 12 | DEPLOYED_DEFAULT |
| final_top_n | 8 | DEPLOYED_DEFAULT |
| knn_top_k | 1024 | DEPLOYED_DEFAULT |
| max_sub_queries | 4 | DEPLOYED_DEFAULT |
| allow_dense_fallback | True | DEPLOYED_DEFAULT |
| rerank_candidates_count / doc_ids / rank_feature / must_not | **omitted** | DEPLOYED_DEFAULT (a non-`None` default must be omitted, not sent as `None`) |
| KB | `9463d93eb97511f1938f2592e9bc6fe4` | KB_VALUE |
| owner tenant | `a9e28731ab70…` | KB_VALUE |
| embedding model | `f79e37e5ab7611f18ecb3887d563fb04` via `resolve_model_config(...)` → dict → `LLMBundle` | MODEL_RESOLUTION |
| vector field | `q_3072_vec = {type: dense_vector, dims: 3072, index: true, similarity: cosine}` | read from the live mapping |

Captured engine call (`rag/retrieval/multi_route.py:235-244`, deployed):

    retriever.retrieval(query, embd_mdl, tenant_ids, kb_ids, 1, routes_top_k, threshold, **kwargs)

so `page=1`, `page_size=routes_top_k` — a CAPTURED value, not an invented default.

## Result

* `retrieve_multi_route` returned **`total=20`, 8 chunks** (the `final_top_n` window) → **CONTROLLED BASELINE AVAILABLE**.
* Determinism: two identical runs produced **the same chunk ids in the same order** (8 vs 8).
* Instrumentation agreement: the lexical-only (weight 0.0), dense-only (1.0), hybrid (0.6) and
  pipeline orderings had **identical top-6**, and the pipeline's top-8 sat **8/8 inside** the
  hybrid top-8.
* Verdict: **CONTROLLED TRACE VALIDATED**.

Precise statement of what that means, and no more:

> No lexical/dense/hybrid Top-6 ranking divergence was observed for **Query E** under the
> controlled configuration.

It is NOT evidence that the lexical and dense legs agree in general — one query on one corpus at
one configuration cannot say that.

## Stage 0 fact captured here (used by the A/C work)

The deployed tokenizer renders `Q/GDW 73286.2-2026` as `['q', 'gdw', '73286', '2', '2026']`, and
it splits `单芯` into `单` + `芯`. Both sides of a lexical match go through the same tokenizer,
which is why the header value and a query naming the same term can still meet in the index.

## Blocked at this boundary, stated for the next round

`../../tools/scripts/ac_stage_trace.py` failed inside the container with
`ModuleNotFoundError: No module named 'rag.nlp.retrieval_projection'`: the tracer imported a
module that exists only in the HOST working tree, not in the deployed image (the container runs
its own revision). The same class of boundary error as the earlier `LLMBundle` and
`Dealer.retrieval(top=...)` mistakes — and the fix is the same in kind: the tracer must depend on
nothing the deployed image does not have, and must implement its own blank-template signal from
the raw body instead of importing the host module.
