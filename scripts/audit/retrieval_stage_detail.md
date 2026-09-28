## 10. Stage capture (instrumentation v2, series A)

Probe v1 recorded decomposition and final windows for both series but could not see the per-route
candidates or the pre-cut pool: the deployed pipeline does **not** route through `Dealer.retrieval`
(`dealer_has_retrieval = True`), and the pool is passed as an
**argument** to the selection step. Version 2 records arguments as well as return values, on the same
frozen configuration. Answer generation still happens nowhere in the probe.

### 10.1 Embedding-quota degradation inside this probe (read before the tables)

- Status: **QUOTA_EXHAUSTED_MID_RUN**
- Last clean progress line: `[stage] U_B6 run 6/10` (query U_B6, run 6)
- Quota error lines: 290, route-failure lines: 139
- Queries measured **before** the failure: S_A1, S_A3, S_B1, S_C3, U_A2, U_A4, U_A5, U_B6
- Queries measured **after** it (degraded: the dense route dropped out): U_C1, K_STD, K_3CORE, K_LAYER
- Provenance: OBSERVED (probe stderr: GeminiEmbed 429 RESOURCE_EXHAUSTED, free-tier limit 1000 embed requests/day)

Probe v1 (both series, all 12 queries, 240 runs) recorded **zero** quota failures, so the stability
result in sections 3-7 stands. Only the stage detail below is affected, and each row says so.

| query | pool sizes | distinct pools | distinct sub-query sets | distinct route sets | distinct windows | first divergence | cutoff flag | min cutoff delta | quota |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S_A1 | [12, 12, 12]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| S_A3 | [20, 20, 20]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| S_B1 | [20, 20, 20]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| S_C3 | [12, 12, 12]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| U_A2 | [13, 13, 13]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| U_A4 | [31, 31, 31]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| U_A5 | [15, 15, 15]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| U_B6 | [19, 19, 19]... | 4 | 1 | 1 | 1 | pool_before_cut | NOT_OBSERVABLE | None | DEGRADED |
| U_C1 | [0, 0, 0]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | DEGRADED |
| K_STD | [0, 0, 0]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | DEGRADED |
| K_3CORE | [0, 0, 0]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | DEGRADED |
| K_LAYER | [0, 0, 0]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | DEGRADED |

### 10.2 Query embedding determinism (10 encodes per query)

| query | convention used | dim | unique sha256 | bit-identical | pairwise cosine min | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| S_A1 | encode_queries:str | 3072 | 1/10 | True | 1.0 | QUERY_EMBEDDING_DETERMINISTIC |
| S_A3 | encode_queries:str | 3072 | 1/10 | True | 1.0 | QUERY_EMBEDDING_DETERMINISTIC |
| S_B1 | encode_queries:str | 3072 | 1/10 | True | 1.0000000000000002 | QUERY_EMBEDDING_DETERMINISTIC |
| S_C3 | encode_queries:str | 3072 | 1/10 | True | 1.0000000000000002 | QUERY_EMBEDDING_DETERMINISTIC |
| U_A2 | encode_queries:str | 3072 | 1/10 | True | 1.0 | QUERY_EMBEDDING_DETERMINISTIC |
| U_A4 | encode_queries:str | 3072 | 1/10 | True | 0.9999999999999998 | QUERY_EMBEDDING_DETERMINISTIC |
| U_A5 | encode_queries:str | 3072 | 1/10 | True | 0.9999999999999999 | QUERY_EMBEDDING_DETERMINISTIC |
| U_B6 | encode_queries:str | 3072 | 1/10 | True | 1.0 | QUERY_EMBEDDING_DETERMINISTIC |
| U_C1 | None | None | None/None | None | None | None |
| K_STD | None | None | None/None | None | None | None |
| K_3CORE | None | None | None/None | None | None | None |
| K_LAYER | None | None | None/None | None | None | None |

### 10.3 Sub-queries actually used (first run of each query)

- **S_A1**: Q/GDW 73286.2-2026 是什么标准
- **S_A3**: NONE
- **S_B1**: NONE
- **S_C3**: NONE
- **U_A2**: 这个标准适用于什么类型的电缆
- **U_A4**: 导体有什么技术要求？ | 内衬层有什么技术要求？ | 铠装层有什么技术要求？
- **U_A5**: 专用技术规范自己规定了哪些要求 | 这些要求都是这个专用技术规范自己规定的吗？ 通用技术规范 正文条款 | 这些要求都是这个专用技术规范自己规定的吗？ 通用技术规范 正文条款
- **U_B6** (degraded): 专用规范对电缆产品的技术要求是什么？ | 通用规范对电缆产品的技术要求是什么？
- **U_C1** (degraded): 220kV 单芯海底电缆的技术要求 | 220kV 三芯海底电缆的技术要求 | 220kV 单芯和三芯海底电缆的技术要求区别 | 单芯 220kV 和 海底电缆的技术要求有什么区别？ | 三芯 220kV 和 海底电缆的技术要求有什么区别？ | 单芯 220kV 和 海底电缆的技术要求有什么区别？ | 三芯 220kV 和 海底电缆的技术要求有什么区别？
- **K_STD** (degraded): NONE
- **K_3CORE** (degraded): 220kV 三芯海底电缆的主要结构是什么 | 220kV 三芯海底电缆铠装层的一般要求是什么
- **K_LAYER** (degraded): 220kV 单芯海底电缆的内衬层有什么技术要求？ | 220kV 单芯海底电缆的铠装层有什么技术要求？

### 10.4 Cutoff detail (first run of each query)

- **S_A1**: pool 12, last included None@None, first excluded 646ab90775aa14a5@0.8402066200644166, delta None, min in-window adjacent delta None, excluded ['646ab90775aa14a5', '255c187f4e228542', '43e96b415797394b', 'ab96130b7a5d5c8f', '3fb0a03b92cc70d7', 'a14eb97907268118', '0b4e3c1a73c1e334', '455737939ddb4a47', '8ebd878ace520649', 'af100b79a9e9734d', '7de0deabdfbdccdc', '9ac2797e006f5b84']
- **S_A3**: pool 20, last included None@None, first excluded b5aaf72bcd33d44a@0.5340928110985942, delta None, min in-window adjacent delta None, excluded ['b5aaf72bcd33d44a', '3fb0a03b92cc70d7', 'd1d75672f2dbc333', 'bac8e77cef90c8cf', '43e96b415797394b', '83d1e77c201be56a', 'ab96130b7a5d5c8f', 'e518c08d493651a2', '0eb621e18881e734', '48f12a5a8ce5eb6c', 'd8277d37a03a2b0a', '5f81fce4a4628ebf', 'cc4443ca2f4783ac', 'bc2a6dfa54206eab', 'c37c0820c0438c3e', 'f96c7773551514ae', 'd415a7ac2958f635', 'af100b79a9e9734d', '69b5a1ff838d3cb0', '53fadbd4012a310c']
- **S_B1**: pool 20, last included None@None, first excluded d1d75672f2dbc333@0.5342719637483971, delta None, min in-window adjacent delta None, excluded ['d1d75672f2dbc333', 'b5aaf72bcd33d44a', '3fb0a03b92cc70d7', '5f81fce4a4628ebf', 'f96c7773551514ae', 'bac8e77cef90c8cf', '43e96b415797394b', 'cc4443ca2f4783ac', 'bc2a6dfa54206eab', '4859566265b332b6', 'ff249ff52cf67152', '8065ad3f4096ca30', 'd79d92725b46b084', '83d1e77c201be56a', 'ab96130b7a5d5c8f', 'e518c08d493651a2', '0eb621e18881e734', 'a03230e9a7559b31', '4238f6f6e9af11af', '322b5cb7a3e64f7b']
- **S_C3**: pool 12, last included None@None, first excluded c3a92b28cfd524d3@0.6112297913067793, delta None, min in-window adjacent delta None, excluded ['c3a92b28cfd524d3', 'ff6344911eb4df75', 'd5f07f5d24ec3cc7', '63e02a0f356894e8', '090dfb645da31bf7', 'cc73de0f16418d16', '8b1911d054c3a036', 'f224470a51f32350', 'db3b79c036360d3c', 'a18b9160c4084d5f', 'd66a18e51bec0e16', '9ea7300f4f6f4219']
- **U_A2**: pool 13, last included None@None, first excluded af100b79a9e9734d@0.6595418391791346, delta None, min in-window adjacent delta None, excluded ['af100b79a9e9734d', 'a2aa88912e75ca47', 'f6bf347f95c33598', '7402cf6c99cbd67e', '6940892bba5934b6', '545e7b340cc0f7c2', '2491aa2ce5eacd8d', 'd1d75672f2dbc333', 'd17f1d620732e24d', 'ab4c98652643c955', '4fb20686f0d2e452', 'ea4a0fbc49651bc5', 'dab0815ca83d0f4b']
- **U_A4**: pool 31, last included None@None, first excluded bac8e77cef90c8cf@0.7479514559714708, delta None, min in-window adjacent delta None, excluded ['bac8e77cef90c8cf', 'af74d2eeaaf2c4a4', 'a0bd8a6bde77b17e', '844f7e6b59d9764e', 'a14eb97907268118', '2491aa2ce5eacd8d', 'fc1c81cbe8032710', 'd1d75672f2dbc333', '5ab5e9b5f2bf95e9', 'b878ee18e84b6356', '322b5cb7a3e64f7b', 'a03230e9a7559b31', '4f291a3c82619d20', 'ab4c98652643c955', 'bf550e46c94ec75b', '14b813dabd06d5fe', 'bc2a6dfa54206eab', 'e356b2ab7a081555', 'ff249ff52cf67152', 'cc4443ca2f4783ac', 'c7347587e61a3532', 'a6989cb86469df8a', '5f81fce4a4628ebf', '663de80696a67296', 'a2aa88912e75ca47', 'acc2f7b2530f0d90', 'f96c7773551514ae', '22ce10ed2fd538bf', '7291b6a1b712f692', '9fa9e164a3e3ca7a', 'd66a18e51bec0e16']
- **U_A5**: pool 15, last included None@None, first excluded f224470a51f32350@0.7190502006458741, delta None, min in-window adjacent delta None, excluded ['f224470a51f32350', 'a18b9160c4084d5f', '48f12a5a8ce5eb6c', '8b1911d054c3a036', 'cc73de0f16418d16', '090dfb645da31bf7', 'ff6344911eb4df75', 'd5f07f5d24ec3cc7', 'c3a92b28cfd524d3', 'd8277d37a03a2b0a', 'd79d92725b46b084', '7de0deabdfbdccdc', 'a0ad87807e53b172', '0b4e3c1a73c1e334', '4859566265b332b6']
- **U_B6**: pool 19, last included None@None, first excluded 48f12a5a8ce5eb6c@0.6926114859555407, delta None, min in-window adjacent delta None, excluded ['48f12a5a8ce5eb6c', 'bac8e77cef90c8cf', 'f224470a51f32350', '91b65c311693d243', '4859566265b332b6', '8b1911d054c3a036', 'a18b9160c4084d5f', 'a0ad87807e53b172', 'ea4a0fbc49651bc5', '2bd4637c7292862b', 'd5f07f5d24ec3cc7', 'ff6344911eb4df75', 'c3a92b28cfd524d3', 'a3e9d12dd321aec1', '127b63ce057208eb', 'd8277d37a03a2b0a', '97ac46b1d738ff00', 'd79d92725b46b084', 'cc73de0f16418d16']
- **U_C1**: pool 0, last included None@None, first excluded None@None, delta None, min in-window adjacent delta None, excluded []
- **K_STD**: pool 0, last included None@None, first excluded None@None, delta None, min in-window adjacent delta None, excluded []
- **K_3CORE**: pool 0, last included None@None, first excluded None@None, delta None, min in-window adjacent delta None, excluded []
- **K_LAYER**: pool 0, last included None@None, first excluded None@None, delta None, min in-window adjacent delta None, excluded []

### 10.5 Instrumented call names

`["RouteResult", "_normalized", "_retrieve_route", "_score", "_sub_query_text", "chunk_key", "clause_route", "comparative_routes", "comparison_sides", "core_document_followup", "decompose_question", "dedupe_chunks", "document_id", "document_key", "empty_kbinfos", "gen_json", "is_comparative_question", "is_prose_chunk", "looks_composite", "merge_route_hits", "multi_route_retrieve", "parse_sub_queries", "rerank_chunks", "resolve_core_documents", "resolve_final_top_n", "resolve_routes_top_k", "retrieve_multi_route", "route_question", "seeks_clause", "strip_section_references"]`

Note: `Dealer.retrieval` never appears in that list, which is why probe v1 produced no per-route data —
the deployed multi-route path reaches the store through its own route helpers.