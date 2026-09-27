# Production retrieval baseline capture - Query E (单芯 220kV 海缆)

Read-only capture from the DEPLOYED container (wenruo-rag-cpu). Nothing was patched, mounted
or written; this document records what the deployed code actually does.

## Entry point

* deployed import: `from rag.retrieval import retrieve_multi_route` (`dialog_service.py:53`)
* deployed signature (inspected at runtime, not assumed):
  `retrieve_multi_route(*, retriever, question, tenant_ids, kb_ids, chat_mdl=None, embd_mdl=None, rerank_mdl=None, similarity_threshold=0.2, vector_similarity_weight=0.6, routes_top_k=12, final_top_n=8, knn_top_k=1024, rerank_candidates_count=None, doc_ids=None, rank_feature=None, must_not=None, max_sub_queries=4, allow_dense_fallback=True)`
* the deployed `Dealer.retrieval()` takes NO `top` kwarg - the host tree's does, and assuming it was my error.

## Effective Query: the question CAN be rewritten before retrieval

`dialog_service.py:873-874` (deployed):

    if prompt_config.get("keyword", False):
        questions[-1] = questions[-1] + "," + await keyword_extraction(chat_mdl, questions[-1])

So the string retrieval receives is NOT always the user's question: when the assistant has
`prompt_config["keyword"]` on, extracted keywords are appended. `NOT OBSERVABLE` in this
capture: whether the assistant that owns the canary knowledge base has `keyword` enabled -
no assistant in the live index is bound to KB `9463d93eb97511f1938f2592e9bc6fe4`, which is
why the replay has to construct the dialog explicitly and record that choice.

## Model resolution (verified working end to end)

    KnowledgebaseService.get_by_id(KB) -> kb.embd_id (= f79e37e5ab7611f18ecb3887d563fb04)
    -> resolve_model_config(owner_tenant, LLMType.EMBEDDING, kb.embd_id)   # returns a DICT
    -> LLMBundle(owner_tenant, config)                                    # the deployed shape

Passing the KB id where the model id belongs was my earlier error
(`TenantModel id=9463d93e... not found`).

## The call site as deployed

``
        if embd_mdl:             # Multi-route retrieval (rag/retrieval/): a question that asks for             # several parameters at once is decomposed into atomic sub-queries,             # each route is retrieved hybrid and concurrently, the routes are             # merged by chunk_id, and the merged pool is reranked against the             # ORIGINAL question before the answer model sees it. A question with             # one information need still takes exactly one route, so it keeps the             # retrieval behaviour it had before this pipeline existed. Reranking             # happens once, over the union - the routes pass no rerank model of             # their own. `dialog.top_n` still decides how many passages the answer             # gets; the per-route recall window is the pipeline's own 12-passage             # default, inside the recommended 10-15 band.             kbinfos = await retrieve_multi_route(                 retriever=retriever,                 question=" ".join(questions),                 chat_mdl=chat_mdl,                 embd_mdl=embd_mdl,                 rerank_mdl=rerank_mdl,                 tenant_ids=tenant_ids,                 kb_ids=dialog.kb_ids,                 similarity_threshold=dialog.similarity_threshold,
``

## Still NOT OBSERVABLE in this capture

* the assistant-level values of `similarity_threshold`, `vector_similarity_weight`,
  `top_n`/`final_top_n`, `top_k` and `rerank_id` for the canary knowledge base;
* whether the embedding model above matches the model that produced the stored `q_3072_vec`
  (the index maps 3072 dims and nothing in the repository creates that mapping);
* the assistant's `meta_data_filter` and the resulting `doc_ids` scope.

## Consequence for the smoke test

The previous construction returned 0 chunks from `retrieve_multi_route` while the same query
through `Dealer.retrieval` errored on the unsupported `top` kwarg. Both are now explained as
construction defects rather than retrieval defects, and neither is remedied yet. Verdict stays
**TRACE NOT VALIDATED**: no A/C stage was run and no root cause is asserted.
