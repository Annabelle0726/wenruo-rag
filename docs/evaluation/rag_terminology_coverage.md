# RAG terminology coverage — investigation (read-only)

Follow-up to `docs/evaluation/rag_qa_004_instability.md`, which localised the QA-004 failure to a
vocabulary mismatch: the question says **设计使用寿命**, the corpus says **设计使用年限**, and the
corpus contains `设计使用寿命` exactly **0** times in all 317 chunks.

This document audits what terminology machinery already exists, what is inert, and which layer a
Retrieval Improvement Phase should change. Nothing was written to any index, row, config or file.

---

## 1. Inventory of existing alias / terminology machinery

| # | mechanism | exists in code | wired into the query path | active on this corpus |
|---|---|---|---|---|
| 1 | **synonym expansion** — `rag/nlp/synonym.py` (file + Redis) | yes | yes: `FulltextQueryer.question()` calls `self.syn.lookup()` for the **Chinese** branch too (`query.py:110`, `:132`) and injects the results into **both** the lexical expression (`(tk OR (syn)^0.2)`, `query.py:146`; `(tms)^5 OR (syns)^0.7`, `:159`) **and** the `keywords` list that feeds `term_similarity` (`:112`, `:135`) | ❌ **dictionary is EMPTY** |
| 2 | **keyword alias at ingest** — `auto_keywords` → `important_kwd^30` / `important_tks^20`; `auto_questions` → `question_tks^20` | yes | yes: those are the **highest-weighted** fields in `FulltextQueryer.query_fields` (`query.py:32-40`) | ❌ `auto_keywords=0`, `auto_questions=0` → `important_kwd=[]`, `question_tks=[]` on every chunk |
| 3 | **terminology mapping (domain field vocabulary)** — `rag/nlp/retrieval_projection.py` `PROFILES` | yes: a `power_cable` profile declares `电压 / 芯数 / 线缆类别 / 敷设环境` | yes: rendered into the `[标准号: … | 章节: …]` header, which **is** the indexed `content_with_weight` for both legs | ⚠️ **active, but field-VALUE only** — it canonicalises `voltage_level=220kV`; it holds no synonym for a *question* term |
| 4 | **query rewrite** | yes, several | partially | ⚠️ see §2.4 |
| 5 | **metadata alias / matcher** — `rag/nlp/auto_metadata.py` + `doc_meta` index + `gen_meta_filter` + `meta_data_filter` | yes | yes: `apply_meta_data_filter` (`dialog_service.py:794`) → `scoped_doc_ids` → `doc_ids` | ⚠️ **populated and available**, but the traced assistant has `meta_data_filter = {}` |
| 6 | **KG / entity alias** — `KGSearch.query_rewrite` (LLM extracts `entities_from_query` + `answer_type_keywords`) | yes | only reachable via `prompt_config.use_kg` → `settings.kg_retriever` (`dialog_service.py:925`) | ❌ `use_kg` is NULL; no KG index for this corpus |
| 7 | **designation normalisation / aliasing** — `normalize_designation` / `display_designation` / `designation_key` + `_QUALIFIER_SPELLING` (`retrieval_projection.py:164-219`); `standard_designations` / `designation_parts` / `generic_sibling_designation` (`chunk_profile.py`) | yes | yes: used for header rendering and for ranking | ✅ **ACTIVE — the only working alias layer, scoped to standard numbers** |
| 8 | **prompt-level terminology conversion** | ❌ none | — | ❌ a grep of `rag/prompts/` for 同义词/近义/别名/术语/归一化 finds only unrelated `normalize` hits (TOC levels, `max_length`) |

---

## 2. Detail on the checked items

### 2.1 `synonym.json` — the file does not exist anywhere

`rag/nlp/synonym.py:39` looks for `<project>/rag/res/synonym.json`. The repository's `rag/res/`
contains **no JSON files at all**, and neither does the image:

```
$ docker exec wenruo-rag-cpu ls /ragflow/rag/res/*.json
ls: cannot access '/ragflow/rag/res/*.json': No such file or directory
```

Every process start therefore logs `Missing synonym.json` → `self.dictionary = {}` → `Fail to load
synonym`. Runtime state, read inside the container:

```
synonym dict size: 0     redis attached: True
  lookup 设计使用寿命 -> []   lookup 寿命 -> []   lookup 海缆 -> []   lookup 终端 -> []   lookup 接头 -> []
```

**The Redis channel is live.** `synonym.Dealer.__init__` calls `load()`, and `load()` reads the
Redis key `kevin_synonyms` (refreshed at most hourly, `synonym.py:57-76`). `REDIS_CONN.is_alive()`
is `True` in the deployment, so the dealer is constructed **with** a Redis handle — and the key is
simply absent:

```
redis alive: True
kevin_synonyms present: False  len: 0
```

This matters for the recommendation: a glossary loaded through `kevin_synonyms` becomes effective
**without touching retrieval code, without a rebuild, and without a deploy**.

### 2.2 Term weighting is also degraded

`term_weight.Dealer` (`rag/nlp/term_weight.py:114-127`) loads `rag/res/ner.json` (a domain entity
list) and `rag/res/term.freq`; both are missing, exactly like `synonym.json`:

```
term_weight ne entries: 0   df entries: 0
```

So the *weights* applied to query tokens lose their domain component as well as their synonym
component.

### 2.3 What the two legs actually see

The indexed tokens of the clause (read from `content_ltks`), and the tokens the query produces:

```
index:  接头 设计 使用 年限 … 年 … 不少 于 30
query 设计使用寿命 -> ['设计使用寿命', '使用寿命', '使用', '寿命', '设计']
query 设计使用年限 -> ['设计使用年限', '设计', '年限', '使用']
```

Shared tokens: `设计`, `使用` (weights 0.41 / 0.19). The discriminator is `年限` (corpus) versus
`寿命` (query) — **zero overlap**, and no synonym bridges them.

The highest-weighted lexical fields that could have bridged it are empty, because ingest-time
keyword generation is off for this knowledge base:

```
auto_keywords: 0   auto_questions: 0   topn_tags: 3   enable_metadata: false
important_kwd: []  question_tks: []  title_tks: [populated]
```

### 2.4 Query rewrite inventory

| rewrite point | state | evidence |
|---|---|---|
| `decompose_question()` (retrieval decomposition) | **ON** | 12/12 samples stable within a session, but the route **count** differs between sessions (2 vs 4) — the bistability documented in the QA-004 report |
| app-level `keyword_extraction()` | **OFF** | `prompt_config.keyword = false` (`dialog_service.py:873`) |
| `full_question()` (multi-turn rewrite) | **OFF** | `prompt_config.refine_multiturn = false` |
| `cross_languages()` | not configured | `prompt_config.cross_languages` NULL |
| KG `query_rewrite()` | unreachable | `use_kg` NULL |
| ingest `keyword_extraction()` / `question_proposal()` | **OFF** | `auto_keywords = 0`, `auto_questions = 0` |
| linguistic normalisation inside decomposition (`strip_section_references`, `question_values`, `_normalize_with_map`, `clause_route`, `comparative_routes`) | **ON** | normalises **numbers, section references and clause intent only** — nothing about terminology |

### 2.5 Metadata alias surface — available and already populated

`doc_meta` (12 documents) carries extracted fields, and for the six benchmark documents they are
correct:

| doc_id | standard_no | voltage_level | doc_type | year | cable_type |
|---|---|---|---|---|---|
| `a2fa1c74…` | Q/GDW 73286.1-2026 | 220kV | 通用技术规范 | 2026 | — |
| `28668474…` | Q/GDW 73286.2-2026 | 220kV | 专用技术规范 | 2026 | 海底电力电缆 |
| `12392cee…` | Q/GDW **13285.1-2019** | **110kV** | 通用技术规范 | **2019** | — |
| `10dda10e…` | Q/GDW 73285.3-2026 | 110kV | 专用技术规范 | 2026 | 海底电力电缆 |

Note `12392cee…`: the 110kV general part in this corpus **is the 2019 edition**, and the metadata
says so. This is a genuine, working, query-time-usable scope surface (`standard_no`,
`voltage_level`, `doc_type`, `year`, `cable_type`).

### 2.6 The dense leg already equates the two terms

Measured cosine between the query embedding and the two competing chunk vectors (3072-d):

| query | cos(life chunk) | cos(structure chunk) |
|---|---|---|
| `设计使用寿命` | **0.7857** | 0.7643 |
| `设计使用年限` | **0.7929** | 0.7632 |
| `设计寿命` | 0.7757 | 0.7625 |
| `设计年限` | 0.7832 | 0.7584 |
| `寿命` | 0.7483 | 0.7217 |
| `年限` | 0.7593 | 0.7213 |
| the full composite question | **0.8460** | **0.8315** |

Two conclusions:

1. **The embedding is already synonym-aware for this pair** — swapping 寿命 for 年限 moves the
   cosine against the life chunk by **0.0072** (0.7857 → 0.7929). The dense leg is not what fails.
2. **The dense leg barely discriminates at all on this corpus** — the full question scores 0.8460
   against the life table and 0.8315 against a structure table, a separation of **0.0145**. The
   lexical leg is the only real discriminator here, and that is precisely the leg the terminology
   gap disables.

---

## 3. Minimal terminology coverage table (recommendation only — nothing written)

Counts are `chunks containing the term / 317`, measured over the benchmark knowledge base.

### 3.1 Hard gaps — the user's phrase occurs **zero** times in the corpus

| user wording | corpus wording | user | corpus | note |
|---|---|---|---|---|
| 设计使用寿命 | **设计使用年限** | 0 | 20 | the QA-004 failure exactly |
| 使用寿命 | **使用年限** | 0 | 20 | same clause, shorter form |
| 电缆接头 | **接头** | **0** | 76 | the corpus never writes the 电缆- prefixed form |
| — | 绝缘平均厚度 | — | — | (QA-003 fact; note the corpus has no `绝缘平均厚度` chunk either, consistent with that clause having been *deleted* in 2026) |

### 3.2 Soft variants — both spellings exist, but usage is heavily skewed

| variant A | count | variant B | count | note |
|---|---|---|---|---|
| 海底电缆 | 45 | **海底电力电缆** | **295** | the document titles use B; the prefix header matches on the title |
| 海缆 | 36 | 海底电力电缆 | 295 | 海缆 is *not* a gap — it is present, but never in the standard numbers or titles |
| 金属护套 | 9 | **金属套** | **42** | |
| 铅套 | 9 | 金属套 | 42 | not synonyms — 铅套 is a *type of* 金属套; map only in one direction and only where the clause means the sheath |
| XLPE | 5 | **交联聚乙烯** | **23** | |
| 截面 | 40 | **标称截面** | **4** | the benchmark's own wording; the corpus overwhelmingly writes bare 截面 |
| 防水 | 11 | 阻水 | 24 | |
| 电缆终端 | 9 | **终端** | **50** | |
| 年限 | 20 | 寿命 | **26** | ⚠️ **not** a safe blanket pair — see below |

### 3.3 Two cautions the table has to carry

1. **`寿命` is not a synonym of `年限`.** `寿命` occurs in 26 chunks, including clauses that have
   nothing to do with the attachment's design life (e.g. 过载时间不影响海缆寿命). A blanket
   `寿命 → 年限` entry would expand unrelated questions into the life tables and damage precision.
   The mapping must be **phrase-scoped** (`设计使用寿命 → 设计使用年限`,
   `使用寿命 → 使用年限`), not token-scoped.
2. **`synonym.Dealer.lookup` is token-keyed and direction-agnostic** (`synonym.py:85-90` strips
   whitespace and lowercases, then does a flat `dict.get`). It applies an expansion at **query**
   time only, so it cannot corrupt the index — but it also cannot express "corpus writes A, users
   write B", because it is fed question tokens, never chunk tokens. The key `设计使用寿命` works
   because that whole string is one entry of `self.tw.split()` output; the key `寿命` would fire on
   every occurrence of 寿命 in any question. Phrase keys are the safe form.

---

## 4. Best fix layer

### A. Embedding adjustment — **not needed**

The measured Δ of **0.0072** shows the embedding already treats 设计使用寿命 and 设计使用年限 as the
same concept, and the composite question already scores the life table *higher* than the structure
table (0.8460 > 0.8315). Replacing the model would not fix a lexical token gap, and the flat
0.0145 separation between the two competing halves would remain.

### B. Synonym dictionary — **the layer to change** (highest leverage, infrastructure already present)

This is the only layer that closes the actual gap: the lexical leg's discriminator (`年限` vs
`寿命`) has **zero** token overlap, and the two fields that could have bridged it
(`important_kwd^30`, `question_tks^20`) are structurally empty. Everything needed is already
wired — `lookup()` is called for Chinese queries, its output enters both the lexical expression and
the `keywords`/`term_similarity` path — so the Phase is **data, not code**.

Two delivery channels already exist, and one of them needs no deploy at all:

| channel | location | cost to activate | persistence |
|---|---|---|---|
| Redis `kevin_synonyms` | read by `synonym.Dealer.load()` every ≤1h | write one key | runtime only; lost on Redis flush |
| `rag/res/synonym.json` | read at `synonym.Dealer.__init__` | add the file + rebuild image | durable, versioned |

**Caveat to carry into the Phase:** a token-level table is a blunt instrument — see §3.3. Scope
entries to phrases, and prefer the pair 使用寿命/使用年限 over 寿命/年限.
The same file format also feeds `term_weight`'s missing `ner.json`, so domain term weighting and
synonymy can be addressed together.

### C. Query rewrite — **needed as the carrier, not as the fix by itself**

The rewrite surface exists and one part of it is already ON (`decompose_question`), but it is an
LLM call whose **route count differs between sessions** — that is the bistability the QA-004 report
documented, so it is not a reliable place to hide a correctness guarantee. The deterministic rewrite
points (`strip_section_references`, `question_values`, `_normalize_with_map`) already normalise
*numbers and clause references*; **terminology normalisation is the missing sibling**, and it belongs
at that deterministic level: normalise the question's terms to the corpus's canonical terms before
both legs see them.

Note also that `retrieval_projection.PROFILES` is the architecturally correct home: it already
declares, per domain, "what it calls its fields, and which of them retrieval indexes", and the
rendered header is demonstrably what both legs index. Extending that pattern from *field labels*
(`电压`) to *field-value synonyms* is the smallest structural step, and it keeps the vocabulary
with the domain rather than in a global NLTK-oriented file.

### D. Metadata filtering — **available but does not address this failure**

The surface is real and already populated (§2.5), and it is the right tool for a *different*
problem (voltage/edition scoping: the corpus mixes 110kV 2019, 110kV 2026 and 220kV 2026). But the
QA-004 measurement already showed that scoping flips *which half* of the answer survives and never
restores both: 110kV → 4 design-life / 0 structure, 220kV → 1 / 0, unscoped → 0 / 4, while
`设计使用年限` with no voltage expression at all returns 12/12 life passages. Metadata filtering is
orthogonal, not corrective, for terminology.

### E. Chunking — **a structural condition, not the trigger**

No chunk contains both clauses; the design-life clause occupies 20 chunks across 4 documents while
the structure clause occupies exactly 4 chunks (one per dedicated document). Chunking therefore sets
up the competition for the 12-slot window, but a window holding both halves is demonstrably
achievable (6 life + 2 structure) once the wording matches. Re-chunking would not have made
`设计使用寿命` reach the clause.

---

## 5. Conclusion for the Retrieval Improvement Phase

**The layer to change is terminology coverage — layer B — delivered through the existing
deterministic rewrite/normalisation path (C) and, where domain-specific, through the
`retrieval_projection` domain profile.**

Concretely, the Phase needs no change to embedding, no change to chunking, and no change to the
ranking parameters. It needs a **phrase-scoped, corpus-anchored glossary** for the power-cable
domain, plus a place to apply it that is deterministic rather than LLM-dependent.

Supporting reasons, all measured on the deployed system:

1. the embedding already equates the failing pair (Δ 0.0072) and barely separates the two halves
   (Δ 0.0145), so the dense leg cannot be the fix;
2. the lexical leg is the only real discriminator, and its discriminator token has zero overlap
   between question and corpus;
3. the synonym mechanism, its Chinese-query wiring and its `term_similarity` contribution all
   already exist and are switched on — only the **dictionary** is missing, and its Redis channel is
   live;
4. the two other zero-coverage user phrases (`使用寿命`, `电缆接头`) are the same class of defect,
   so the fix generalises beyond QA-004;
5. metadata filtering and chunking, the two layers that look superficially attractive, are both
   measured not to touch this failure.

The one thing the Phase must not do is rely on the LLM decomposer: it is the component that
currently makes the outcome vary between sessions, and QA-004's two different answers came from its
granularity, not from retrieval noise.
