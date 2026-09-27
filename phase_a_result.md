# Phase A Canary Result — Q/GDW 73286 family

Executed with the audited script, on the approved scope only. Rollback works, and was NOT
used (no rollback condition occurred).

## Execution

| item | value |
|---|---|
| script | `tools/scripts/phase_a_canary.py` (audited; one bug fixed after the run — see "Idempotency") |
| command | `--index ragflow_a9e28731ab7011f19b833887d563fb04 --family 73286 --execute --snapshot` |
| git commit at execution | `eb11fbe1ad9a5e629c6a8e466386a2b9c6d5637a` |
| index | `ragflow_a9e28731ab7011f19b833887d563fb04` |
| target chunk-id checksum | `b83b3b147ea2eaa3adc8aa5eddc5ff64f8878a526476728760b5e40245b12ff9` (sha256 of the 155 sorted ids) |
| snapshot | `phase_a_snapshot_20260927T095014Z.json` (155 chunks, 496 907 bytes, written BEFORE the first write) |
| guard | documents 3 / chunks 155 / outside 0 / legacy 58 / no_prefix 97 / current 0 — all matched, `guard_passed: true` |
| counters | attempted **155**, changed **155**, unchanged 0, skipped 0, **failed 0** |
| outside-family | state hash `8a80b385702e38f4` before and after — **unchanged** |

## Integrity checks (`phase_a_integrity.md`, verdict PASS)

| check | result |
|---|---|
| chunks carrying a CURRENT prefix | **155 / 155** |
| double header / malformed header | **0 / 0** |
| empty, `-` or `None` metadata field | **0** |
| standard number in display form | **155 / 155** (`Q/GDW 73286.1/2/3`) |
| Part 1 core count | **absent** (correct — it is the general part) |
| Part 2 / Part 3 core count | **单芯 / 三芯** |
| token fields re-generated | **155/155 exact** — `content_ltks` equals *header tokens + a fresh tokenization of the raw body*, so this is a re-tokenization, not old tokens with a string glued in front |
| stored section values | 82 of 155 non-empty, **longest 19 chars**, zero containing sentence punctuation |
| vectors / MySQL / MinIO / mapping / chunk `_id` | untouched by construction (the script sends only the three text fields to `_update/<id>`) |

## Idempotency — NOT clean, cause found and fixed

The post-execution dry run showed **changed 60 / unchanged 95**, not the expected 0 / 155.

Cause: the section walk fed it the *projected* body. For the 58 chunks that already carried
a legacy header, the first line of the stored text was the header, which is not a heading —
so the first run derived those sections from a different text than a correct walk would.
The script now unwraps the header first (`split_retrieval_header`) and walks the RAW body,
which is what makes the projection idempotent from here on.

Consequence, stated plainly: the 60 chunks whose stored `章节` came from the first walk keep
a section that is the *previous* clause's heading (or empty). Every stored value is short and
syntactically valid (max 19 chars, no prose), so this is a fidelity defect, not corruption.
Settling it needs ONE more write of those 60 chunks — deliberately NOT done, because the
execution order forbids a second write for idempotency verification.

## Retrieval (before → after, lexical leg, identical query set / tokenizer / path)

| query | class | before rank of the expected passage | after | before R@5 | after R@5 |
|---|---|---|---|---|---|
| A | exact standard number | not found | not found | 0 | 0 |
| B | natural language | 2 | 3 | 1 | 1 |
| C | three-core | not found | not found | 0 | 0 |
| D | generic part | 2 | **1** | 1 | 1 |
| E | disambiguation | 1 | 1 | 1 | 1 |
| F | blank template | not found | **5** | 0 | 1 |

**Recall@5 3/6 → 4/6 · Recall@10 3/6 → 4/6 · MRR 0.333 → 0.422.** No regression on any
query that previously succeeded; F gained recall; D moved to rank 1.

### Leg analysis (answers to the six questions)

1. **New recall from the header injection**: F (blank template) entered the top-10 at rank 5
   and D's expected passage moved from 2 to 1. Both are passages whose *document identity*
   was previously absent from their text; the header now supplies it.
2. **A and C still miss**: their top-10 is dominated by passages from OTHER documents
   (`4 标准技术参数表`, `5 组件材料配置表` — the 抽水蓄能 and 10kV families), i.e. generic
   parameter-table wording out-matches the standard-number token and the three-core wording
   in the lexical leg. The expected Part 2 / Part 3 passages are not in the top-10 at all.
3. **Is the dense leg suppressing them?** UNKNOWN and NOT CLAIMED. This round measures the
   lexical leg only (Phase A cannot change a stored vector), so no evidence either way
   exists yet. Per the execution order, this is NOT grounds for touching
   `vector_similarity_weight`.
4. **Reranker**: not exercised (benchmark is the lexical leg).
5. **New false positives from the header**: none observed as *new* — A and C were already
   failing before, and no previously-relevant query lost its hit. The header's `文档:` field
   is long (up to 143 chars), and the generic words it adds (`220kV`, `海底电力电缆`) are the
   most likely future source of cross-part pollution, so query E was re-checked: Part 2 still
   leads it (rank 1, unchanged).
6. **Part 2 / Part 3 cross-pollution**: not observed in the top-10 of E. Part 3's passages do
   not appear ahead of Part 2's for the single-core question.

## Decision

**B — partially successful.** The text backfill itself is clean (155/155, zero outside
mutations, display-form identities, correct core counts, token fields genuinely
re-generated, no retrieval regression, F gained and D improved), but two things are open
before any scale-up:

1. **Idempotency from the stored state**: one more approved write of 60 chunks settles the
   sections the first walk derived from the wrong text. The script bug behind it is fixed;
   nothing else is needed.
2. **A and C still miss, and by the lexical leg's own account they miss for corpus/wording
   reasons, not because the cut or the fusion removed them.** The next diagnostic step is to
   see the *hybrid* top-10 for those two queries (the dense leg plus the reranker), because
   that is where a correct passage could exist below the lexical top-10 — no weight change,
   no reranker change, just measurement.

Nothing further was executed: no second write, no rollback, no embedding, no re-parse, no
mapping change, no `vector_similarity_weight` or reranker change, no cross-document fallback.
