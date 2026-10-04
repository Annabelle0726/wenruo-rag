# Terminology synonym coverage — Phase 0

Implements the domain terminology mapping identified in
`docs/evaluation/rag_terminology_coverage.md`. **One resource file was added. No retrieval logic,
no embedding, no rerank, no score parameter, no chunking and no metadata schema was touched.**

---

## 1. The synonym loading mechanism (investigated before implementing)

### 1.1 `rag/res/synonym.json` (`rag/nlp/synonym.py:39-47`)

```python
path = os.path.join(get_project_base_directory(), "rag/res", "synonym.json")
with open(path, "r") as f:                 # NOTE: no encoding= argument
    self.dictionary = json.load(f)
self.dictionary = {(k.lower() if isinstance(k, str) else k): v for k, v in self.dictionary.items()}
```

| property | value |
|---|---|
| shape | one JSON **object** at the top level |
| key | a token or phrase; **lowercased at load** by the loader |
| value | `str` **or** `list[str]` — `lookup` normalises a bare string into a one-element list (`:87-88`) |
| path | `<project>/rag/res/synonym.json` |

### 1.2 Redis `kevin_synonyms` (`synonym.py:57-76`)

```python
d = self.redis.get("kevin_synonyms")
if not d: return
d = json.loads(d)
self.dictionary = d                      # full REPLACEMENT, not a merge
```

| property | value |
|---|---|
| shape | a single Redis **string** holding the same JSON object |
| keys | **NOT lowercased** on this path — they must already be lowercase |
| refresh | only when `lookup_num >= 100` **and** ≥3600 s since the last load, and only from inside `lookup()` |
| precedence | **Redis wins and the file is ignored** — `load()` runs in `__init__` and replaces the dictionary wholesale |
| channel state today | Redis reachable (`REDIS_CONN.is_alive() == True`, dealer constructed with a live handle) but the key was **absent** |

Two defects found while investigating, neither of which requires a code change to work around:

1. **`open()` has no `encoding=`.** The platform default applies: UTF-8 on Linux, **cp936 on this
   Windows host**, where a UTF-8 file raises `UnicodeDecodeError: 'gbk' codec can't decode byte 0xae`
   and is silently swallowed into `logging.warning("Missing synonym.json")`. The resource is
   therefore written as **pure-ASCII JSON** (`\uXXXX` escapes), which `json.load` decodes to exactly
   the same strings under any codec. Verified: the file round-trips identically under
   ascii / utf-8 / cp936 / latin-1.
2. `logging.warning("Fail to load synonym")` is emitted **before** `load()` runs (`:51-55`), so a
   Redis-served deployment always logs it even when the dictionary is fully populated. Cosmetic.

### 1.3 `lookup` input/output (`synonym.py:78-100`)

| | |
|---|---|
| input | one string, whitespace-collapsed (`re.sub(r"[ \t]+", " ", tk.strip())`); **lookup does not lowercase** — callers are already lowercase because `FulltextQueryer.question()` lowercases the query text first |
| output | `list[str]`, truncated to `topn=8` (default) |
| fallback | **WordNet**, only when `re.fullmatch(r"[a-z]+", tk)` matches and the dictionary missed — so a pure-ASCII key such as `xlpe` short-circuits a WordNet lookup by being present |

Where the output goes (both matter, and both were already wired):

- `keywords.extend(syns)` (`query.py:112`, `:135`) → the `keywords` list feeds
  `token_similarity` → **`term_similarity`**;
- the lexical expression: `(tk OR (syn)^0.2)` (`:146`) and `(tms)^5 OR (syns)^0.7` (`:159`).

---

## 2. The dictionary v0

### 2.1 Files changed

| file | change |
|---|---|
| `rag/res/synonym.json` | **added** (new file, 6 entries) |

Nothing else. No code file, no config, no schema, no index, no row.

### 2.2 Diff

```diff
--- /dev/null
+++ b/rag/res/synonym.json
@@ -0,0 +1,20 @@
+{
+  "\u8bbe\u8ba1\u4f7f\u7528\u5bff\u547d": [
+    "\u8bbe\u8ba1\u4f7f\u7528\u5e74\u9650"
+  ],
+  "\u4f7f\u7528\u5bff\u547d": [
+    "\u4f7f\u7528\u5e74\u9650"
+  ],
+  "\u7535\u7f06\u63a5\u5934": [
+    "\u63a5\u5934"
+  ],
+  "\u6d77\u7f06": [
+    "\u6d77\u5e95\u7535\u529b\u7535\u7f06"
+  ],
+  "\u6d77\u5e95\u7535\u7f06": [
+    "\u6d77\u5e95\u7535\u529b\u7535\u7f06"
+  ],
+  "xlpe": [
+    "\u4ea4\u8054\u805a\u4e59\u70ef"
+  ]
+}
```

Decoded, with the corpus evidence behind each entry (`chunks containing the term / 317`):

| key (user term) | value (corpus term) | user | corpus |
|---|---|---|---|
| 设计使用寿命 | 设计使用年限 | 0 | 20 |
| 使用寿命 | 使用年限 | 0 | 20 |
| 电缆接头 | 接头 | 0 | 76 |
| 海缆 | 海底电力电缆 | 36 | 295 |
| 海底电缆 | 海底电力电缆 | 45 | 295 |
| xlpe | 交联聚乙烯 | 5 | 23 |

### 2.3 Design rules honoured

- **Phrase-level only.** Every key is a multi-character phrase; no single token is mapped.
- **`寿命 → 年限` is deliberately absent.** Verified in both states: `lookup("寿命")` → `[]`,
  `lookup("年限")` → `[]`. `寿命` occurs in 26 chunks including clauses unrelated to attachment
  design life, so a token-level entry would broaden unrelated questions.
- **Targets are the corpus's own words**, each with a measured zero-or-skewed coverage gap.
- Keys are lowercase (`xlpe`, not `XLPE`) because the Redis path does not lowercase; verified that
  the query path lowercases before tokenising, so `XLPE` in a question still resolves.

### 2.4 Which entries actually fire (measured)

| key | fires on the tested inputs? |
|---|---|
| `使用寿命` | **yes** — this is the one that fires inside a sentence; `tw.split` yields it as its own token |
| `设计使用寿命` | fires when the phrase stands alone (`tw.split("设计使用寿命") == ["设计使用寿命"]`); inside a sentence the merged token is longer, so `使用寿命` carries it |
| `xlpe` | **yes** |
| `海缆` | fires (keywords gained `海底电力电缆`) but produced **no window change** (Jaccard 1.0) |
| `海底电缆` | not exercised by these probes |
| `电缆接头` | **never fired** — the tokenizer split the phrase into `电缆` + `接头` |

So 3 of 6 entries are load-bearing, 2 are inert-but-harmless, 1 is untested. The inert entries are
retained deliberately: they cost nothing, and they cover phrasings the tokenizer emits differently.
This is stated rather than presented as full coverage.

---

## 3. A/B on the deployed retrieval path

The image has no bind mount, and no rebuild/deploy was permitted, so the table was loaded through
the **channel the deployed loader already reads** — Redis `kevin_synonyms`, carrying byte-identical
JSON to the file. Each run is a fresh process, so `synonym.Dealer.__init__` picks the state up.

| | before | after |
|---|---|---|
| `synonym.dictionary` size | 0 | **6** |
| `lookup(设计使用寿命)` | `[]` | `['设计使用年限']` |
| `lookup(使用寿命)` | `[]` | `['使用年限']` |
| `lookup(寿命)` | `[]` | `[]` *(unchanged, by design)* |

### 3.1 Per-query window (production entry, assistant's own parameters)

`n` / design-life passages / structure passages, and the Jaccard of the returned chunk-id sets:

| query | role | before | after | Jaccard |
|---|---|---|---|---|
| **QA004_user_term** (the reported failure) | target | 9 / **0** / 4 | 7 / **0** / 4 | 0.778 |
| QA004_life_only (user's wording, life only) | target | 10 / **0** / 4 | 12 / **2** / 4 | 0.833 |
| QA004_std_term (already-working wording) | target-control | 12 / 5 / 4 | 12 / 5 / 4 | 1.000 |
| QA004_struct_only | target-control | 12 / 0 / 4 | 12 / 0 / 4 | 1.000 |
| QA001 | control | 12 / 0 / 0 | 12 / 0 / 0 | 1.000 |
| QA002 | control | 12 / 0 / 0 | 12 / 0 / 0 | 1.000 |
| QA003 | control | 12 / 0 / 0 | 12 / 0 / 0 | 1.000 |
| QA005 | control | 12 / 0 / 0 | 12 / 0 / 0 | 1.000 |
| MAP_seacable | probe | 12 / 0 / 2 | 12 / 0 / 2 | 1.000 |
| MAP_xlpe | probe | 12 / 0 / 0 | 12 / 0 / 0 | 0.600 |
| MAP_connector | probe | 12 / 0 / 4 | 12 / 0 / 4 | 1.000 |
| UNC_armour | control | 12 / 0 / 0 | 12 / 0 / 0 | 1.000 |
| UNC_pumping | control | 12 / 0 / 0 | 12 / 0 / 0 | 1.000 |
| UNC_numeric | control | 12 / 0 / 0 | 12 / 0 / 0 | 1.000 |

**No expansion of irrelevant recall:** all **7 control queries** returned an identical window
(Jaccard **1.000**) and a **0-character** context delta. The only windows that moved are the two
target queries and the `xlpe` probe.

### 3.2 The synonym reaches the query tokens

```
QA004_user_term   keywords before: [… '的设计使用寿命与结构有何要求', '使用寿命', '使用', '寿命', '设计', …]
QA004_user_term   keywords after:  [… '的设计使用寿命与结构有何要求', '使用寿命', '使用', '寿命', '使用年限', '设计', …]
MAP_seacable      keywords after:  [… '海缆', '海底电力电缆', '厚度', '铅套', …]
MAP_xlpe          keywords after:  [… 'xlpe', '交联聚乙烯', 'xlpe', '交联聚乙烯', …]
```

`使用年限` — the corpus's own token — is now in the query, which is the mechanism the QA-004
diagnosis called for.

### 3.3 Stage-level effect

| stage | before | after |
|---|---|---|
| route `标准对电缆附件（终端与接头）的设计使用寿命有何要求` | 10 / **0** / 4 | 8 / **0** / 4 |
| route `标准对电缆附件终端的设计使用寿命有何要求` | 12 / **2** / 4 | 12 / **3** / 4 |
| route `…的结构有何要求` | 12 / 0 / 4 | 12 / 0 / 4 |
| **merged pool** | 15 / **2** / 4 | 16 / **3** / 4 |
| **after deployed rerank + cut** | 12 / **2** / 3 | 12 / **3** / 3 |

The synonym adds **one more design-life passage** to the narrow route (+50 %), and it survives the
reranker and the 12-slot cut.

### 3.4 Acceptance criterion — and its limit

| | |
|---|---|
| `before` | life recall **0** |
| `after` — on the design-life question in the user's own wording (`QA004_life_only`) | life evidence **appears** (0 → 2) ✅ |
| `after` — at route level (`life_route_narrow_terminal`, merged pool) | 2 → 3 ✅ |
| `after` — on the exact composite question `QA004_user_term` | **still 0** ❌ |

**The resource does not by itself fix the reported question.** The reason is structural and was
already measured in the QA-004 report: the composite route returns `life = 0` **in both states**
(0 → 0), and in the failing session the deployed LLM decomposer emitted *only* composite routes.
The synonym moves the narrow route, which is a route the decomposer does not always create.

Why the composite route is immune: it carries both `终端` and `接头` intent, and `接头` material is
abundant in this corpus (76 chunks against 50 for `终端`), so the composite route's 12-passage
window is filled before the design-life tables are reached. *This last sentence is an inference
from the corpus statistics, not a measurement* — the per-candidate pre-threshold trace that would
confirm it does not exist on this build (hook H1 in `rag_qa_trace_capability.md`).

---

## 4. Implementation channel: file vs Redis

| | A — `rag/res/synonym.json` | B — Redis `kevin_synonyms` |
|---|---|---|
| version control | ✅ a normal tracked file, reviewable in a PR, diffable, shipped in the image | ❌ out-of-band state; not in the repo, not in the image, no history |
| reproducibility | ✅ a given image always behaves identically | ❌ behaviour depends on live Redis content |
| rollback | ✅ revert the commit | ⚠️ delete the key; silent if forgotten |
| secret/credential surface | none | needs Redis write access |
| load timing | at process start | at process start, then ≤1 h throttle, and **replaces** the file dictionary |
| encoding risk | ⚠️ the loader passes no `encoding=` — mitigated by the ASCII-only file | ✅ JSON string has no file encoding |
| multi-instance consistency | ✅ every replica reads the same file from the image | ⚠️ all replicas share one key; a bad write affects all at once |
| production version control verdict | **the right home for the canonical table** | useful as a hot-fix/rollout channel only |

**Recommendation: A is the production artifact.** B was used here solely because it is the only
channel that takes effect without a rebuild — which this task forbids. After verification the key
was **deleted**, leaving the deployment exactly as found:

```
kevin_synonyms present: False
```

---

## 5. Release recommendation

**Ship the resource; do not claim QA-004 is fixed.**

Ship it, because every measurement points one way:

- **No regression.** 7/7 control queries produced a byte-identical window and a 0-character context
  delta; the 4 other frozen benchmark questions are untouched; the already-working wording
  (`QA004_std_term`, 5 life passages) is unchanged.
- **The intended mechanism demonstrably works.** The corpus token `使用年限` now enters the query;
  the narrow design-life route gains a passage (2 → 3) and it survives to the final cut.
- **Encoding-safe** by construction (ASCII-only), which the UTF-8 form would not have been given the
  loader's missing `encoding=`.
- **Zero blast radius.** It is one new data file; nothing loads it but the existing synonym path, and
  an unknown key is simply not found.

Do **not** ship a claim that QA-004 is resolved, because it is not:

- the exact reported question still returns **0** design-life passages;
- the deletion of `寿命 → 年限` (correctly avoided) means the change is, by design, narrower than the
  semantic gap;
- the remaining blocker is the **composite route**, which the synonym does not move, and which is
  reachable only when the LLM decomposer happens to emit narrow routes — the session-level
  bistability documented in `rag_qa_004_instability.md`.

What Phase 0 therefore is: a **verified, non-regressive foundation** that closes the lexical half of
the terminology gap. What it is not: the completion of QA-004. The composite-route behaviour sits in
the routing/ranking layer, which this Phase was explicitly scoped out of, and it should be the
subject of the next Phase rather than being papered over here.

Suggested Phase-0 exit criteria, all met: resource loads via the deployed loader; the intended
targets resolve; `寿命`/`年限` remain unmapped; no control query changes; the artifact is
committable and encoding-independent.

---

## 6. Verification artifacts

| file | purpose |
|---|---|
| `tools/scripts/terminology_synonym_ab.py` | 14-query before/after harness on the deployed production entry; prints the active dictionary state so a run cannot be misattributed |
| `tools/scripts/terminology_synonym_stages.py` | per-stage composition (route → merged pool → after rerank+cut) to locate where a synonym's benefit stops |

The deployment was left in its original state: no image change, no build, no deploy, no production
file modified, and the Redis alias key removed after verification.
