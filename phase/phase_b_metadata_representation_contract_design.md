# Metadata Representation Contract — Design Only

**This window designed a contract and changed no behaviour.** No production change, no ES mapping change, no
backfill, no re-index, no build/deploy/retag, no edit to `_verified_header_end`, none to Numeric Rev 3.1, and
none to retrieval/rerank/merge/context selection. The design below is the deliverable; the recommended option
is NOT implemented.

The problem is stated as the audit stated it: a consumer cannot tell (A) an ingest-injected
`[标准号: … | 文档: …]` from (B) a byte-identical sequence that the PDF's own text contains. That is a
**representation defect**, not a regex defect, and it is confirmed below at the information-theoretic level
rather than argued from examples.

## 1. Current representation and the exact point where provenance is lost

### 1.1 What is stored, and how it is typed

The chunk index (`ragflow_<tenant_id>`) is created from `conf/mapping.json` (Elasticsearch) or
`conf/os_mapping.json` (OpenSearch). Neither file declares the chunk fields: both have **no explicit property
list** (only `lat_lon`) and type every field through **name-suffix dynamic templates**:

| template | match | mapping |
|---|---|---|
| `int` | `*_int` | `integer`, `store: true` |
| `long` / `ulong` / `short` | `*_long` / `*_ulong` / `*_short` | numeric, `store: true` |
| `kwd` | `^(.*_(kwd\|id\|ids\|uid\|uids)\|uid)$` | `keyword`, `similarity: boolean` |
| `ltks` | `*_ltks` | `text`, `analyzer: whitespace`, `store: true` |
| `tks` | `*_tks` | `text`, `analyzer: whitespace`, `similarity: scripted_sim`, `store: true` |
| `string` | `^.*_(with_weight\|list)$` | `text`, `index: false`, `store: true` |
| `dt` | `^.*(_dt\|_time\|_at)$` | `date` |
| `dense_vector` | `*_<dim>_vec` | `dense_vector`/`knn_vector`, cosine |
| others | `*_nst`, `*_obj`, `*_fea(s)`, `*_bin`, `*_flt` | nested / object / rank_feature / binary / float |

So `content_with_weight` is `text, index: false, store: true`: the **stored payload**, never searched
directly. The searched fields are `content_ltks` and `content_sm_ltks` (both `*_ltks` → whitespace-analyzed
text) and the vector field `q_<dim>_vec`. A live read of the index confirms the whole field set:
`content_with_weight, content_ltks, content_sm_ltks, docnm_kwd, title_tks, title_sm_tks, doc_id, kb_id, id,
img_id, page_num_int, position_int, available_int, top_int, create_time, create_timestamp_flt,
deleted_doc_id, compile_kwd, knowledge_graph_kwd, lat_lon, q_3072_vec`.

**Consequence for the design:** a new field whose name ends in `_int` or `_kwd` is auto-mapped, stored, and
requires **no mapping change**. A field named `retrieval_header` (no recognised suffix) would be dynamically
mapped as analysed text - the wrong type for a boundary - so the field NAMES are part of the contract.

### 1.2 Producer → storage → consumer, per path

Every path that can produce or rewrite the header's carrier, with the header-relevant step marked:

| # | path | raw parser content | header generation | `content_with_weight` | token fields | ES | consumer |
|---|---|---|---|---|---|---|---|
| P1 | **normal ingest** `rag/svr/task_executor.py` | chunker output (`ck["content_with_weight"]` / `ck["text"]`) | `doc_context.apply_document_context` at **:473** (chunking stage) | `render_document_context(...) + body` (doc_context:154) | `_prepend_tokens` prepends the prefix's `content_ltks`/`content_sm_ltks` | chunk written with `id = xxhash(content_with_weight + doc_id)` (**task_executor:527**) | retrieval reads `content_with_weight` |
| P2 | **ingest safety net** `task_executor.py:513` | same chunks | the SAME call again, because the chunk id is frozen a few lines later | no-op when the string prefix is already there | - | - | - |
| P3 | **refactor ingest** `rag/svr/task_executor_refactor/chunk_service.py` | same | `apply_document_context` at **:195** and again at **:275** | same | same | same id derivation (`chunk_service.py:292`) | same |
| P4 | **Phase A projection / backfill** `rag/nlp/retrieval_projection.py` + `tools/scripts/phase_a_*.py`, `backfill_prefix_preview.py` | stored body | `render_retrieval_header(metadata, profile)`; `project_chunk` → `retrieval_text` | `header + raw_chunk`, idempotent by `split_retrieval_header` | `token_fields` = header tokens + re-tokenized body | the LIVE richer headers on the 220kV documents came from here | same |
| P5 | **tokenizer stage** `rag/nlp/__init__.py`, `rag/flow/tokenizer/tokenizer.py` | - | - | rewrites it (QA `question\tanswer`, table combining, `combined`) | `content_ltks`/`content_sm_ltks` built here | `q_<dim>_vec` computed from this text | same |
| P6 | **RAPTOR / parent chunks** `task_executor.py:1273,1436`, `raptor_service.py:446,640`, `chunk_service.py:414` | generated summary | none | new chunk content, no header | fresh tokens | new ids | same |
| P7 | **TOC/outline chunks** `task_executor.py:817`, `task_handler.py:934` | outline | none | `json.dumps(toc)` | fresh tokens | new ids | same |
| P8 | **GraphRAG/wiki/structure artifacts** `rag/graphrag/*`, `rag/advanced_rag/*` | graph payloads | none | `json.dumps(payload)` | fresh tokens | `knowledge_graph_kwd` chunk kinds | graph legs only |
| P9 | **manual chunk edit** `api/apps/restful_apis/chunk_api.py:1244,1391` | user text | none | user content verbatim | `rag_tokenizer.tokenize(content)` | `update(...)` in place | same |
| P10 | **dataflow / harness rewrites** `task_executor_refactor/dataflow_service.py:340`, `advanced_rag/harness/tools/text_processing.py:500` | stage text | none | overwrites | downstream | in place | same |

**`PROVENANCE_INFORMATION_LOST_AT`**: `rag/nlp/doc_context.py:154` -
`ck["content_with_weight"] = render_document_context(standard_id, title, sections[index]) + body` - and its
twin `retrieval_projection.retrieval_text`. Immediately before that line the header and the body are two
separate values; immediately after it they are one string, and the boundary survives only as text. Everything
downstream (P5-P10) then treats it as opaque content, and the only traces left are the text itself, the
prepended header TOKENS (a derived signal, not an extent), and the chunk id - which is `xxhash(header + body
+ doc_id)`, a checksum of the whole injected text that proves nothing about where the header ends and would
itself change under any representation change.

Two further audit findings that bear on the contract:

* **The producer's own idempotency check is a string check** (`doc_context.py:152`:
  `if body.lstrip().startswith(CONTEXT_PREFIX_OPEN): continue`). A document whose own first characters are
  `[标准号: ` is therefore **left un-prefixed**: the producer skips injection and stores a body that looks
  exactly like a header. The producer thus manufactures ambiguity case (B) rather than merely being defeated
  by it.
* **The chunk id is derived from `content_with_weight`** (P1:527, P3:292). Any contract that changes those
  bytes changes every chunk id, and chunk ids are referenced by conversation citations, evaluation fixtures
  and internal links (`source_chunk_ids` in the wiki compiler, RAPTOR parent links). This is the single
  strongest technical argument against writing the body into `content_with_weight`.

### 1.3 Unused provenance information currently available

Searched for and found: **none that is authoritatively about the boundary.** `docnm_kwd` is a real structured
field and is what the current cross-check uses, but it describes the document, not the injection.
`content_ltks`/`content_sm_ltks` contain the header's tokens because the producer prepended them - an
independent *echo* of the header, usable as a corroborating signal in a *checker*, but it cannot yield an
extent and it is rebuilt by P5. The chunk id can only prove "this exact concatenation existed". No
`producer`, `header_extent`, `prefix_kind` or timestamp-of-injection field exists anywhere in the chunk
document, the mapping, or the ingest task record.

## 2. `INFORMATION_THEORETIC_AMBIGUITY_CONFIRMED`

For a chunk `c` with stored name `n`, consider two worlds:

* **W1** - the producer ran and injected `H = render_document_context(s, document_title(n), sec)` at position 0.
* **W2** - the producer's own skip-check fired (or no injection path ran at all) and the PDF's own text
  begins with exactly `H`.

In both worlds the stored `content_with_weight` is byte-identical, `docnm_kwd` is identical, `content_ltks`
is identical, and the chunk id is identical. **No function `f(content, docnm_kwd, content_ltks, id)` can
separate W1 from W2**, because the two worlds are the same observation. The ambiguity is therefore a
property of the representation, not of any pattern: strengthening `_verified_header_end` cannot remove it,
and the current filename cross-check must not be promoted to authoritative provenance (it is a *narrowing*
of W2, not an elimination). This is the reason the window's verdict is a contract defect.

## 3. Options compared

### Option A - `header_len_int` (extent only)

Store the character extent of the injected prefix; the consumer slices `content[extent:]`.

* Solves: exactness (G1), collision immunity (G2), hostile filenames (G3) - the extent is about what the
  producer WROTE, not about re-parsing it.
* Costs: 1 field; no mapping change (`*_int`); `content_with_weight` unchanged, so **no chunk-id churn**.
* Gaps: cannot say WHAT was injected (no grammar/version), so a future header change is invisible; cannot
  detect drift (a manual edit that deleted part of the prefix leaves the extent pointing into the body);
  `none` and "0" are the only legacy signalling.

### Option B - separate field, body-only content (`retrieval_header` + `content_body`)

The header moves out of the searchable/stored text entirely; `content_with_weight` becomes the body.

* Solves: everything Option A solves, plus makes body-vs-metadata a first-class fact rather than an offset.
* Costs, and they are severe: **`content_with_weight` bytes change for every chunk**, and the chunk id is
  `xxhash(content_with_weight + doc_id)` → a NEW ID FOR EVERY CHUNK. Conversation citations, evaluation
  fixtures, RAPTOR parent/child links and `source_chunk_ids` all reference ids, so this is a full
  re-ingest with an id-remap, not a backfill. It also changes the **lexical** and **dense** inputs: today
  `content_ltks` and `q_<dim>_vec` are built from header+body, so the contract would have to state whether
  the header keeps contributing to tokens and to the embedding - and any change there moves similarity scores
  and therefore ranks, which is a retrieval change, not a representation change. The "new body field" is also
  unnecessary: a body field is only needed if the full text must remain available, and it does (display and
  citation read the header).
* Verdict: best semantics, worst blast radius, and it cannot be done without also re-deciding the ranking
  inputs. Rejected for this corpus.

### Option C - structured provenance descriptor

`content_prefix_kind_kwd` + `content_prefix_version_int` + `content_prefix_chars_int` (+ optional hash).

* Solves: A's exactness plus versioning (a future grammar is `version: 2`), plus explicitness (`kind: none`
  for legacy/never-injected) plus verifiability when a hash is included.
* Costs: 3-4 fields; all names follow existing templates (`*_kwd`, `*_int`) → no mapping change;
  `content_with_weight` unchanged → **no chunk-id churn**, no embedding/token churn.
* Gaps without a hash: the extent is asserted, not verified, so drift is undetectable.

### Option D (recommended) - Option C **with a prefix checksum**, and no body field

Add `content_prefix_hash_kwd` = hash of the exact characters the producer prepended, and
`content_prefix_body_hash_kwd` = hash of the body-only text. The consumer slices and **verifies**:

```
body = content[extent:]  when kind != none AND hash(content[:extent]) == stored_prefix_hash
body = content           otherwise (fail closed)
```

* Solves: G1 exactly; G2 (a body that equals the header has `kind: none` or a hash mismatch → kept whole);
  G3 (hostile filename characters are inside the hashed prefix, so they cannot shift the boundary); G5
  (idempotency: the producer recomputes prefix and hash and writes them together, so a second pass cannot
  drift); G7 (an old image ignores the new fields; a new image on old chunks fails closed).
* Costs: 4 small fields per chunk; the body hash is optional and can be dropped to 3.
* Rejected alternative within D: storing the prefix TEXT in its own field. It duplicates the bytes (index
  bloat), and the hash already gives verification without the duplication.

## 4. `RECOMMENDED_CONTRACT`

Per-chunk provenance, written by the PRODUCER at the moment it injects, never recovered by re-parsing:

| field | type (via template) | meaning |
|---|---|---|
| `content_prefix_kind_kwd` | `keyword` (`*_kwd`) | `none` \| `identity_legacy` \| `identity_profile:<profile>` |
| `content_prefix_version_int` | `integer` (`*_int`) | grammar version written by the producer (1 for the legacy 3-field shape, 2 for the profile shape) |
| `content_prefix_chars_int` | `integer` (`*_int`) | code-point extent of the injected prefix; `0` when `kind = none` |
| `content_prefix_hash_kwd` | `keyword` (`*_kwd`) | hash (xxhash64, hex) of exactly `content[:extent]` as written |
| `content_prefix_body_hash_kwd` | `keyword` (`*_kwd`) | optional: hash of `content[extent:]`, so a checker can prove `content == prefix + body` |

Contract statements that make it a contract rather than a convention:

1. **`content_with_weight` is not redefined.** It keeps exactly today's bytes (header + body), so chunk ids,
   `content_ltks`/`content_sm_ltks`, `q_<dim>_vec` and display/citation are untouched. This is what keeps the
   migration an application change instead of a re-index.
2. **The extent is original-write provenance.** It is written by the producer from the string it just built;
   no consumer, migration or checker may compute it by matching text.
3. **The hash binds the extent to the bytes.** A consumer that cannot verify fails closed; an extent without
   a matching hash is not evidence of anything.
4. **`kind = none` is meaningful and is the legacy value.** Absence of the field means the same thing as
   `none`, so old chunks are well-formed under the new contract.
5. **The producer records the boundary at the single place it creates it** (`doc_context.py:154` and
   `retrieval_projection.retrieval_text`), and the skip path records `none` explicitly (because a skipped
   injection means there is no header, however much the text looks like one).

## 5. `LEGACY_CHUNK_POLICY`

| option | verdict |
|---|---|
| **fail closed (no strip)** | **chosen as the default.** A chunk without provenance carries no boundary, so its whole text is evidence. Cost: header contamination persists for those chunks, which the value rules must tolerate (they already tolerate it today via identity classification). Safety: it can never delete a document's own text. |
| re-ingest | available and authoritative, but expensive: it regenerates chunk ids, so it is only justified per document where contamination actually changes an answer. It is the ONLY way to obtain authoritative provenance for existing chunks. |
| deterministic backfill by prefix matching | **forbidden.** Re-deriving an extent by matching the stored text against a recomputed header is exactly the inference the audit rejected; it would launder the current heuristic into a field named `provenance`. A backfill may write `kind: none` (a truthful statement that no producer recorded anything) and nothing else. |
| transitional dual representation | **accepted, and the reason the field-absence convention exists**: old chunks are `none`, new and re-ingested chunks carry real provenance, and both are valid. |

The current filename cross-check stays a **diagnostic**: it may order a review queue, and it must not be
promoted to authoritative provenance, nor used to write an extent.

## 6. `CONSUMER_CONTRACT`

Target shape, replacing `body = regex_guess(content)`:

```
kind   = chunk.get("content_prefix_kind_kwd")
extent = chunk.get("content_prefix_chars_int")
digest = chunk.get("content_prefix_hash_kwd")

if kind in (None, "none", "") or not isinstance(extent, int) or extent <= 0:
    body = content                      # no provenance: everything is evidence (fail closed)
elif digest is None or hash(content[:extent]) != digest:
    body = content                      # unverifiable or drifted: fail closed
else:
    body = content[extent:]             # the only path that drops anything
```

Per consumer, unchanged in behaviour this round and only DEFINED here:

| consumer | reads | why |
|---|---|---|
| value rules / `carries_value` / `paired_values` | **body** | a figure that lives only in the injected header is metadata, not evidence |
| table/prose classification (`is_table_chunk`, `is_hollow_table`) | **body** (markup location unchanged) | the header carries no markup today, but the contract makes it explicit |
| ranking features (`similarity`, `rank_score`) | unchanged: the fused score is computed from the indexed fields at query time | the contract does not touch scoring |
| lexical tokenization | **header + body**, exactly as today | the standard number must stay retrievable; the contract forbids changing this silently |
| embedding input | **header + body**, exactly as today (computed at ingest from `content_with_weight`) | changing it would move every similarity, i.e. a ranking change |
| display / citation | **content** (header included) | the reader sees which standard a passage comes from |
| normalization inside the consumer | normalize the BODY, never the string before slicing | slicing must happen on the stored bytes; normalizing first would shift the extent |

## 7. Migration blast radius

**Application changes (no schema change):**
* `rag/nlp/doc_context.py` - write the four fields next to the concatenation; write `kind: none` on the skip path.
* `rag/nlp/retrieval_projection.py` - same for `project_chunk`/`retrieval_text`.
* `rag/svr/task_executor.py`, `rag/svr/task_executor_refactor/chunk_service.py` - carry the fields into the
  chunk dict that is uploaded (they are dict keys, so this is a pass-through, plus the `:527`/`:292` id
  derivation must stay based on `content_with_weight` unchanged).
* `api/apps/restful_apis/chunk_api.py` - a manual edit rewrites `content_with_weight`: it must set
  `kind: none` (the edit destroys any boundary the producer recorded).
* retrieval field projection (`rag/nlp/search.py` / the `Dealer.retrieval` field lists) - the new fields must
  be requested, or the consumer will always fail closed.
* `chunk_profile._values_text` - the slicing consumer (this window does NOT change it).

**Schema / index:**
* ES/OpenSearch: **no mapping change required** - `*_int` and `*_kwd` templates already store and type these
  names, and the index has no explicit property list. An explicit `put_mapping` entry is optional and,
  unlike a field addition, is applied without re-index.
* Other stores (`conf/infinity_mapping.json`, `ob`, `gaussdb`, `serenedb`): each declares its own schema, so
  the four columns must be added there. That is a schema change for those stores, and it is the only place
  where the answer to "is this a schema change?" is yes.

**Data / migration:**
* No backfill that writes extents (forbidden, §5). Optional re-ingest per document for authoritative
  provenance. Existing chunks remain valid as `kind: none`.

**Tests:** the G1-G7 gates of §8, plus the existing QV/Numeric gates re-run unchanged.

**Rollback compatibility:**
* Old image + new chunks: the new fields are simply unread; behaviour is exactly today's. Safe.
* New image + old chunks: `kind` is absent → fail closed → whole text is evidence. Safe (more conservative).
* New image + new chunks: the intended behaviour.
* The only incompatible direction would be Option B (body moved out of `content_with_weight`), which is why
  it is rejected: rolling back would show passages without their header and would change ids.

## 8. `GATE_DESIGN`

| gate | design | mechanism |
|---|---|---|
| **G1 provenance exactness** | producer injects a prefix of `N` code points; consumer excludes exactly those `N` and nothing else; over a fixture matrix of prefix shapes (legacy, profile, empty body, body that begins with `[`) | assert `body == content[N:]` and `content[:N] == injected` |
| **G2 body collision** | a body that contains, BYTE-IDENTICALLY, the same string the producer would inject - at position 0 and mid-body - must be preserved whole when `kind = none`, and must be preserved as BODY when a real prefix precedes it | assert `body` contains the collision text; assert the count of removed characters equals the recorded extent |
| **G3 hostile filename** | names containing `]`, `[`, `|`, `:`, full-width punctuation, double spaces, newlines, mixed Unicode; the header is built from them | assert the consumer never depends on parsing the header (extent from the producer), so no character can shift the boundary; assert `hash` verification still passes |
| **G4 legacy coexistence** | one pool mixing `kind: none` chunks and provenance chunks, same document | assert per-chunk determinism and that the failure mode is fail-closed; assert no cross-chunk state |
| **G5 idempotency** | run the producer twice, and run a projection twice, on the same chunk | assert extent, hash, kind and version are unchanged, and that `content_with_weight` is unchanged after the second pass (today's guarantee: the skip check makes it a no-op) |
| **G6 token/embedding consistency** | for a migrated chunk, assert which fields MUST change and which must not: `content_ltks`/`content_sm_ltks`/`q_<dim>_vec`/`id` unchanged (only the four provenance fields are added) | field-level before/after comparison |
| **G7 rollback** | old-consumer read of new chunks, new-consumer read of old chunks, and (for the rejected Option B) the id/similarity delta that makes it incompatible | behavioural assertions + a documented deployment order |

## 9. `DEPLOYMENT_SEQUENCE_PROPOSAL` (proposal only; nothing was deployed)

1. **Producer first** (writes the fields; consumers ignore them) - safe, additive, no re-index, no id churn.
   Chunks written in this window carry provenance; everything else is `none`.
2. **Retrieval field projection** - request the new fields (still read-only behaviour).
3. **Consumer last** (slices when verifiable, fails closed otherwise) - safe against old chunks by design.
4. **Optional, per document**: re-ingest where header contamination demonstrably changes an answer.
5. Rollback at any step is a redeploy of the previous image; the only loss is the added fields.

## 10. What this window did not do

No implementation of any option, no mapping edit, no backfill, no re-index, no deploy, no change to
`_verified_header_end` or to Numeric Rev 3.1, no retrieval/rerank/merge/context-selection change, no P1-2
work, and no QGDW measurement whatsoever - this is a representation contract design, not a retrieval quality
repair.
