# RAG QA trace capability — investigation for the v0.1 benchmark

Read-only investigation performed against the **running deployment**, in preparation for the
baseline of `docs/evaluation/rag_qa_benchmark_v0.1.md`.

Nothing was built, deployed, patched, mounted or written into the running system. Every fact
below comes from reading the deployed source tree, the live Elasticsearch index, the live MySQL
rows, and from resolving the deployed functions inside the container.

Companion documents:

- `docs/evaluation/rag_qa_baseline_fullbuild.md` — the baseline record (format fixed by the benchmark).
- `tools/scripts/rag_qa_baseline_trace.py` — the read-only tool that fills it.

---

## 1. What is actually deployed

| | |
|---|---|
| container | `wenruo-rag-cpu` (Up, image `my-wenruorag:latest`) |
| image | `my-wenruorag:fullbuild-6892b3c33` (also tagged `release-20260930-fullbuild`, `latest`) |
| image id / digest | `sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123` |
| built | 2026-09-30T11:22:06Z |
| revision the tag names | git `6892b3c3370835286d6431d274d13cfb217f1b9d` (“test(usage): harden policy concurrency and read-model gates”) |

### 1.1 The tag does not name the revision that is running

**Correction to an earlier reading of this document.** The tag suffix `fullbuild-6892b3c33` was
taken to identify the deployed source, and `git diff --name-only 6892b3c33..HEAD -- rag/ api/ tools/`
returns 0 files, which appeared to confirm it. That reasoning is wrong: it compares the *repository*
at two revisions, not the *image* against either. Hashing the files actually inside the container
against the repository's own git blobs shows the image is a third state:

| deployed file | deployed git blob | relation |
|---|---|---|
| `rag/retrieval/pipeline.py` | `da38414bd59b` | **older than both.** Last present in commit `138a1a79a` (2026-09-29, “test(p0): sync P0 acceptance gates…”). It routes via `decompose_question()` at line 280. |
| `rag/retrieval/planner.py` | — | **absent from the image.** Present at `6892b3c33` and at HEAD (`babab0047` added it). |
| `rag/retrieval/__init__.py` | `7a96a43794` | differs from HEAD (`281beb31a8`), which re-exports the planner symbols. |
| `rag/nlp/search.py`, `rag/retrieval/multi_route.py`, `rag/retrieval/rerank.py`, `rag/retrieval/query_router.py`, `rag/retrieval/health*.py`, `rag/retrieval/decomposition.py`, `rag/retrieval/chunk_profile.py`, `rag/nlp/query.py`, `rag/prompts/generator.py`, `rag/utils/es_conn.py`, `rag/app/tag.py`, `api/db/services/dialog_service.py`, `api/db/cable_defaults.py`, `api/db/db_models.py` | — | byte-identical to HEAD. |

Consequence: the deployed retrieval stack is HEAD's stack **except the route-planning stage**,
where it runs the previous design (LLM `decompose_question()` decomposition, no compiled plan and
no `plan_hash`). Reading `rag/retrieval/pipeline.py` from this working tree describes code that is
*not* running; every other file cited in this document does match the deployed bytes.

The baseline tool therefore records a per-file sha256 fingerprint of the deployed modules
(`planner.py` reported as `ABSENT`) and a verified source-layout note, so a capture identifies the
code it came from without depending on the tag.

---

## 2. The real retrieval call entry

```
HTTP (chat / bot / chunk search)
  └── api/db/services/dialog_service.py::async_chat            (also bot_api.py, chunk_api.py)
        ├── get_models(dialog)                                 :779  -> kbs, embd_mdl, rerank_mdl, chat_mdl
        ├── question preprocessing                             :865-875
        │     full_question()        only if prompt_config.refine_multiturn
        │     cross_languages()      only if prompt_config.cross_languages
        │     keyword_extraction()   only if prompt_config.keyword   -> appended as  question + "," + keywords
        ├── scoped_doc_ids                                     :788-803 (meta_data_filter)
        └── rag.retrieval.retrieve_multi_route(                :897   <-- THE ENTRY POINT
                retriever, question=" ".join(questions), chat_mdl, embd_mdl, rerank_mdl,
                tenant_ids, kb_ids,
                similarity_threshold, vector_similarity_weight,
                final_top_n=dialog.top_n, knn_top_k=dialog.top_k,
                rerank_candidates_count, doc_ids=scoped_doc_ids,
                rank_feature=label_question(...))

rag/retrieval/pipeline.py::retrieve_multi_route                (DEPLOYED revision, pre-planner)
  ├── route_question(question)                                 :224  (module D, in-memory only, never persisted)
  ├── decompose_question(chat_mdl, question, max_sub_queries)   :280  (module A: the routes come from an LLM call)
  ├── multi_route_retrieve(routes)                             :309  (routes retrieved CONCURRENTLY)
  │     └── rag/retrieval/multi_route.py::_retrieve_route      :257
  │           └── retriever.retrieval(query, ...)              :289   <-- one hybrid call per route
  │                 (empty pool at the caller's threshold -> ONE retry at RECALL_FLOOR 0.2  :303)
  ├── core_document_followup(...)                              (2nd pass, document-scoped)
  ├── cross_part_fallback(...)                                 (3rd pass, generic part of the standard)
  ├── rerank_chunks(rerank_mdl, merged, question, final_top_n)  -> select_context cut
  └── attach_retrieval_health(infos)
```
Line numbers above are from the **deployed** `rag/retrieval/pipeline.py` (blob `da38414bd59b`), not
from this working tree's copy. In the working tree the same stage is `compile_retrieval_plan(...)`
at `:404`, which compiles a route plan with a `plan_hash` instead of asking the model for
sub-queries; that code is **not** what this baseline ran (§1.1).

```
rag/nlp/search.py::Dealer.retrieval                            :958
  ├── Dealer.search(req, ...)                                  :1024
  │     └── dataStore.search([matchText, matchDense, fusionExpr], ...)  :558-561
  │           └── rag/utils/es_conn.py::search                 :179  -> Elasticsearch 8.11.3
  ├── _prune_deleted_chunks                                    :1027
  ├── scoring:
  │     rerank model present -> rerank_by_model                :951/1053
  │     LEXICAL_DEGRADED     -> _lexical_scores                :846/1047
  │     ES path              -> _knn_scores + rerank_with_knn   :1092/1093
  ├── threshold filter + stable sort                           :1108-1113
  └── chunk dict emission (see §4)                             :1144-1188
```

**The ES-path scoring formula** (`rag/nlp/search.py:864-875`) is worth stating precisely, because
it is what the trace reports per chunk:

```
sim = (1 - vector_similarity_weight) * term_similarity   # lexical, computed locally
    +      vector_similarity_weight  * vector_similarity # dense, from a SECOND pure-kNN call
    + rank_feature                                       # label_question() tags, usually 0 here
```

The dense term comes from `_knn_scores`, a separate KNN-only round trip over the already-selected
ids; the first, fused request is used for **candidate selection**, not for the reported score.

---

## 3. Effective query and keyword extraction: what is on for this corpus

Two different things are called “keyword extraction” and they must not be conflated:

**App level** — `rag/prompts/generator.py:241 keyword_extraction(chat_mdl, content, topn=3)`, an LLM
call invoked at `dialog_service.py:874` and concatenated onto the question:

```python
if prompt_config.get("keyword", False):
    questions[-1] = questions[-1] + "," + await keyword_extraction(chat_mdl, questions[-1])
```

For the assistants bound to the benchmark knowledge base this is **OFF** (`prompt_config.keyword =
false`), as are `refine_multiturn` (OFF) and `cross_languages` (not configured). **The effective
query therefore equals the user's question verbatim** for this baseline — which is the cleanest
possible starting point, and it is read from the assistant row rather than assumed.

**Retrieval level** — `Dealer.qryr.question(text)` returns `(MatchTextExpr, keywords)`
(`rag/nlp/query.py:94/167/231`): the lexical expression sent to the doc store and the keyword list
it was built from. This is reproducible offline from the deployed tokenizer and the trace tool
does exactly that. No deployed call returns it.

---

## 4. Capability matrix against the eight required signals

| required signal | class | evidence |
|---|---|---|
| effective query | **PRODUCTION** | `retrieve_multi_route`'s `question` argument; equals the user question here (see §3) |
| keyword extraction | **NOT_OBSERVABLE** (app) / **CONTROLLED_VARIANT** (retrieval) | app-level LLM output is discarded into the question string; retrieval-level list is recomputable |
| lexical candidates | **CONTROLLED_VARIANT** | fused server-side — see below |
| dense candidates | **CONTROLLED_VARIANT** | fused server-side — see below |
| hybrid ranking | **PRODUCTION** (returned window only) | `similarity`, `term_similarity`, `vector_similarity`, `score_provenance{...}` |
| final top N | **PRODUCTION** | the returned `chunks` list; the cut diagnostics are logged, not returned |
| document metadata | **PRODUCTION** | `docnm_kwd`, `doc_id`, `kb_id`, `doc_type_kwd`, positions, injected `[标准号: … \| 文档: … \| 章节: …]` prefix + `content_prefix_*` |
| chunk content | **PRODUCTION** | `content_with_weight` (markup preserved) and `content_ltks` (the indexed token stream) |

### 4.1 Per-chunk fields the deployed path already returns

From `rag/nlp/search.py:1144-1188`:

- `chunk_id`, `doc_id`, `docnm_kwd`, `kb_id`, `doc_type_kwd`, `mom_id`, `row_id`, `positions`, `image_id`
- `content_with_weight`, `content_ltks`, `important_kwd`, `tag_kwd`
- `similarity` (the score that ordered the window), `term_similarity` (lexical), `vector_similarity` (dense)
- `score_provenance` = `{mode, score_kind, selection_score, lexical_selection_score, dense_score, configured_threshold, effective_vector_weight, hybrid_admitted}`
- `content_prefix_kind_kwd` / `_version_int` / `_chars_int` / `_hash_kwd` when the chunk carries an injected prefix
- after route merge (`multi_route.py:178-254`): `retrieval_routes`, `route_hits`; and `core_scoped` / `generic_fallback` flags when the 2nd/3rd passes contributed the passage

`rag/retrieval/health_bridge.py:238 attach_retrieval_health` then attaches `retrieval_health`
(leg execution, evidence state, answer action) and, when a route failed or ran degraded,
`route_execution`.

**This means the trace does *not* need a new hook to report the hybrid ranking, the final top N,
document metadata or chunk content.** Those are returned by the deployed call as it stands.

### 4.2 Why lexical and dense candidates are not separately observable

The doc store runs **one** request that fuses both legs inside Elasticsearch:

```python
# rag/nlp/search.py:558-561
matchExprs = [matchText, matchDense, fusionExpr] if matchText else [matchDense]
res = await thread_pool_exec(self.dataStore.search, src, highlightFields, filters,
                             matchExprs, orderBy, offset, limit, idx_names, kb_ids,
                             rank_feature=rank_feature)
```

```python
# rag/utils/es_conn.py:261-288
bool_query.must.append(Q("query_string", fields=m.fields, type="best_fields",
                         query=m.matching_text, minimum_should_match=..., boost=1))
bool_query.boost = term_similarity_weight            # lexical leg weight
s = s.knn(m.vector_column_name, k, num_candidates, query_vector=..., filter=...,
          similarity=similarity, boost=vector_similarity_weight)   # dense leg weight
```

The weighted-sum fusion happens **server-side**, so a single response contains only the fused
hits. There is no per-leg candidate list anywhere in the response, in the returned dict, or in the
logs. The only way to observe the two legs separately is to ask again with the other leg switched
off — which is a **different request**, and is labelled `CONTROLLED_VARIANT` in the trace
(`vector_similarity_weight` 0.0 → lexical only, 1.0 → dense only, plus the configured 0.5).

### 4.3 Also not returned as data (present only in logs)

- the **pre-cut ranked pool**: `rag/retrieval/rerank.py:620 _select` logs
  `[Rerank] N candidate(s) -> M passage(s) kept (P prose / T table; best scores …; documents: …)`
  and the quota shortfall reason, but returns only the selected passages;
- the **decomposition routes**: `retrieve_multi_route` returns no route list; the routes are only
  recoverable from each chunk's `retrieval_routes`. (The working tree's newer pipeline would log a
  compiled plan with a `plan_hash` — that code is not deployed, see §1.1.)
- the **effective (post-preprocessing) query**: `dialog_service.py:940` logs it at DEBUG;
- `LEXICAL_DEGRADED` is the one path that returns structured provenance:
  `multi_route.py:175` returns `selection_trace{policy, before, after}`.

---

## 5. Debug hooks that would close the gap

Not implemented — recorded so the gap is explicit rather than silently papered over. Ordered by
the value they would add to this baseline.

**H1 — per-candidate pre-cap list from `Dealer.retrieval`** (`rag/nlp/search.py`, around :1102-1123).
Additive key on the returned dict, emitted only when an environment flag is set (e.g.
`RAG_DEBUG_RETRIEVAL_TRACE=1`), holding for every candidate *before* the threshold/page cut:
`{id, similarity, term_similarity, vector_similarity, rank_feature_score, rank}`. This is the
single highest-value hook: it turns “the top 12” into “the ranking that produced the top 12”, which
is what a retrieval regression is actually about.

**H2 — per-leg candidates from the doc store** (`rag/utils/es_conn.py::search`, or `Dealer.search`).
Either return the raw `hits` of the lexical-only and KNN-only sub-queries, or issue the two
sub-queries explicitly when the debug flag is set. Without this, lexical/dense attribution stays a
re-ask rather than an observation of the request production actually made.

**H3 — the decomposition result in the returned dict** (`rag/retrieval/pipeline.py:280` in the
deployed revision). Return `{route texts, which stage produced each (original / dimension / side /
clause), and the decomposition call's outcome}` instead of only using it to drive retrieval. The
routes are recoverable from `retrieval_routes`, but a route that was generated and then retrieved
*nothing* leaves no trace at all, and that is precisely the interesting case. (On the working
tree's newer pipeline this hook would instead return the compiled plan with its `plan_hash`.)

**H4 — the context-cut diagnostics in the result** (`rag/retrieval/rerank.py::_select`, :616-640).
Return `{pool_size, kept, prose, tables, per_document, shortfall_reason, dropped_value_passages}`
as data. Today a short window is only explainable by reading the log for that request.

**H5 — the retrieval-stage effective query and which preprocessors ran**
(`api/db/services/dialog_service.py`, around :865-875). Record the post-preprocessing string plus
the flags (`keyword`, `refine_multiturn`, `cross_languages`) with the turn or the trace. Only
matters when those flags are on; for the current assistants they are off, so this baseline is
unaffected.

One hook, H1, would remove three of the “CONTROLLED_VARIANT” rows above. H2 is the only one that
cannot be emulated from outside the request.

---

## 6. The benchmark corpus, as it exists in the live index

The benchmark names standards as `Q/GDW 73285-2026` and `Q/GDW 73286.2/.3-2026`. The knowledge
base holds them as **six documents**, each carrying an injected prefix of the form
`[标准号: Q/GDW 73286.2 | 文档: … | 电压: 220kV | 芯数: 单芯 | … | 章节: 4 标准技术参数表]`:

| doc_id | designation | document | chunks |
|---|---|---|---|
| `12392ceebc0311f1ba16b1bb8ee1529c` | Q/GDW 73285.1—2026 | 110kV 海缆采购标准 第1部分：通用技术规范 | 53 |
| `124dcd52bc0311f1ba16b1bb8ee1529c` | Q/GDW 73285.2—2026 | 110kV 海缆采购标准 第2部分：110kV 单芯专用技术规范 | 53 |
| `10dda10ebc0311f1ba16b1bb8ee1529c` | Q/GDW 73285.3—2026 | 110kV 海缆采购标准 第3部分：110kV 三芯专用技术规范 | 53 |
| `a2fa1c74b97511f1938f2592e9bc6fe4` | Q/GDW 73286.1—2026 | 220kV 海缆采购标准 第1部分：通用技术规范 | 50 |
| `28668474ba1b11f1be9555eabe501d5b` | Q/GDW 73286.2—2026 | 220kV 海缆采购标准 第2部分：220kV 单芯专用技术规范 | 54 |
| `f18db09cba1211f18bee33eac9b39c66` | Q/GDW 73286.3—2026 | 220kV 海缆采购标准 第3部分：220kV 三芯专用技术规范 | 51 |

Knowledge base `9463d93eb97511f1938f2592e9bc6fe4`, tenant `a9e28731ab7011f19b833887d563fb04`,
`doc_num=6`, `chunk_num=315`, `parser_id=naive`, embedding `f79e37e5ab7611f18ecb3887d563fb04`.

Every benchmark QA maps onto this set:

- QA-001 → 73286.2 (单芯) + 73286.3 (三芯), 表 1
- QA-002 → 73285.1 / .2 / .3 — the series structure
- QA-003 → the 2026 texts, which state `代替 Q/GDW 13286.x—2019`
- QA-004 → 附件（终端/接头）clauses in the series
- QA-005 → 110kV, i.e. the 73285.x documents

Note one trap for reading results: the 110kV 第1部分 document **also contains 2019-era designation
strings** (`Q/GDW 13285.1-2019` appears in its text), so a trace that greps for a designation in
the raw content can attribute a passage to the wrong revision. The tool reads the designation from
the injected prefix instead.

---

## 7. The tool

`tools/scripts/rag_qa_baseline_trace.py` — read-only, one file, no dependency added.

Delivered by `docker cp` into the container's `/tmp` and run with its output redirected to a file
inside the container, then copied back. The image carries no bind mount of this repository and
rebuilding it is out of scope, so the script has to travel; `/tmp` is the container's own writable
layer, not the image and not production code.

```powershell
docker cp tools/scripts/rag_qa_baseline_trace.py wenruo-rag-cpu:/tmp/rag_qa_baseline_trace.py
docker exec wenruo-rag-cpu sh -c "cd /ragflow && python /tmp/rag_qa_baseline_trace.py > /tmp/qa_baseline.md 2> /tmp/qa_baseline.err"
docker cp wenruo-rag-cpu:/tmp/qa_baseline.md docs/evaluation/rag_qa_baseline_fullbuild.md
```

**Do not pipe the script in over stdin** (`docker exec -i ... python - < script`). It was tried and
it silently corrupted the source: the container's Python decoded the piped bytes as GBK, so
`根据` arrived as `鏍规嵁` and the script died with `SyntaxError: unterminated string literal`, while
the host printed the Chinese back correctly. The failure is encoding-dependent and does not
reproduce on a small ASCII-only test, which makes it a trap rather than an obvious error. The
`docker cp` route is byte-exact and verifiable with `sha256sum` on both sides.

The capture can be re-scored without re-running it, which matters because a re-run re-invokes the
LLM decomposition stage and can produce a different baseline:

```bash
# re-render the stored capture with a corrected evidence probe: no retrieval, no model call
TRACE_RENDER_FROM=/tmp/rag_qa_baseline_trace.json python /tmp/rag_qa_baseline_trace.py
```

What it does, per QA:

1. one **PRODUCTION** call to `rag.retrieval.retrieve_multi_route` with the assistant row's own
   values, read from MySQL at run time (`similarity_threshold`, `vector_similarity_weight`,
   `top_n`, `top_k`, `rerank_candidates_count`, `rerank_id`, `meta_data_filter`, `prompt_config`);
2. the **CONTROLLED_VARIANT** legs at `vector_similarity_weight` 0.0 / 1.0 / configured;
3. the retrieval-level keyword extraction recomputed from the deployed tokenizer;
4. the final context through the deployed `rag.prompts.generator.kb_prompt` with the deployed
   token budget;
5. the answer through the deployed chat model and the assistant's own system prompt;
6. a deterministic evidence probe against the frozen `Expected facts`, reported as
   `EXPLORATORY_JUDGMENT` and explicitly not a Gold Set.

Every row in the output carries its evidence class, and the coverage table of §4 is embedded in the
report itself so a reader of the baseline sees which numbers are observations of production and
which are re-asks.

It writes only the report. No index write, no MySQL write, no Docker build, no deploy, no assistant
created, modified or reused: the assistant row is read, never written.

### Trace parameters it resolves (verified by resolving them in the container)

| parameter | value | source |
|---|---|---|
| assistant | `5c8c249eb8e411f180e20bf412cbc55e` | the only assistant bound to the benchmark KB whose `meta_data_filter` is `{}`, so no document scope is derived |
| `similarity_threshold` | 0.55 | `dialog` row = `cable_defaults.SIMILARITY_THRESHOLD` |
| `vector_similarity_weight` | 0.5 | `dialog` row = `cable_defaults.VECTOR_SIMILARITY_WEIGHT` |
| `final_top_n` | 12 | `dialog.top_n` = `cable_defaults.TOP_N` |
| `knn_top_k` | 1024 | `dialog.top_k` |
| `rerank_candidates_count` | 30 | `dialog.rerank_candidates_count` = `cable_defaults.RERANK_CANDIDATES_COUNT` |
| `routes_top_k` | 12 | pipeline default, adapted in memory by `query_router.route_question` |
| `max_sub_queries` | 4 | pipeline default |
| `allow_dense_fallback` | True | pipeline default |
| `doc_ids` | None | `meta_data_filter = {}` derives no scope |
| `rank_feature` | `None` | `label_question()` returns None unless the KB sets `tag_kb_ids` |
| rerank | **ON** — workspace default `BAAI/bge-reranker-v2-m3` (`tenant_model` `26ecabceafdd11f1b5363887d563fb04`, SILICONFLOW) | `dialog.rerank_id` is empty, so `resolve_rerank_mdl` falls to level 2 |
| answer model | `deepseek-v4-flash`, `max_tokens` 1000000 | tenant default CHAT model |

Two of these deserve emphasis because they are easy to get wrong:

- **Reranking is on even though the assistant binds no reranker.** `resolve_rerank_mdl`
  (`dialog_service.py:1859`) falls back to the workspace default. A baseline run without the
  reranker is a *different* system.
- **`similarity_threshold=0.55` is high**, and `multi_route.py:303` retries a route that returns
  nothing at `RECALL_FLOOR=0.2`. A trace that reports only the returned window cannot show whether
  a route was rescued; the tool flags the degraded/route-execution fields when they appear.
