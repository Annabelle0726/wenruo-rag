# Phase A Canary Readiness Report

Scope: `Q/GDW 73286` family (Part 1 / Part 2 / Part 3) of the live index
`ragflow_a9e28731ab7011f19b833887d563fb04`. **Nothing was written**: every number below
comes from read-only queries and from the offline projection. Awaiting explicit approval
before `--execute`.

## 1. Standard number: display vs comparison

`CanonicalMetadata.document_standard_no` holds the DISPLAY form (`Q/GDW 73286.3-2026`),
`standard_no_key` the comparison form (`q_gdw_73286_3_2026`), and only the display form
can reach a header. Normalization touches separators only (spaces, `_`, `/`, fullwidth
`／`), keeps the number's dots and the year's hyphen, and converts an `_` BETWEEN DIGITS
into the year hyphen. Seven spellings of the three parts normalize to the same key
(`Q/GDW`, `Q_GDW `, `Q_GDW_…_`, `Q／GDW`, padded/lowercase), asserted by test.

**Ambiguity reported, not invented**: Part 3's own text writes `Q/GDW 73286.3` with NO
year. The display value borrows `-2026` from the family and the candidate's evidence says
so (`inferred as part 3 of QGDW73286`); a document whose year nothing states keeps no
year (`Q/GDW 73286.3`).

## 2. Section extraction

Source: `rag/nlp/doc_context.py::document_sections` → `_heading_of`. Defect: the heading's
tail took the whole line, so 20 of 57 stored values ran to the 40-char cap with clause
prose (`4.5.2 完成合同设备安装后，买方和卖方应检查和确认安装工作…`). Deterministic boundary
now: the tail is cut at the first sentence terminator and DROPPED when longer than
`SECTION_TAIL_CHAR_LIMIT` (16) — `4.5.2` alone is the honest answer for a prose line —
and a bare clause number is accepted as a section when it has two dotted levels.
Regression tests cover the prose case, the title case and the budget.

## 3. Final projection per document

| document | projection |
|---|---|
| Part 1 | `[标准号: Q/GDW 73286.1 \| 文档: …第1部分：通用技术规范.pdf \| 电压: 220kV \| 敷设环境: 海底] ` (no core count — it is the general part) |
| Part 2 | `[标准号: Q/GDW 73286.2 \| 文档: …第2部分：220kV单芯… \| 电压: 220kV \| 芯数: 单芯 \| 线缆类别: 海底电力电缆 \| 敷设环境: 海底] ` |
| Part 3 | `[标准号: Q/GDW 73286.3 \| 文档: …第3部分：220kV三芯… \| 电压: 220kV \| 芯数: 三芯 \| 线缆类别: 海底电力电缆 \| 敷设环境: 海底] ` |

Section is appended per chunk (a passage property, not a domain one). Field order is
identity → title → domain attributes → section; a missing field is omitted entirely (no
`-`, no `None`, no empty label), asserted by test.

## 4. Header length (over the 155 canary chunks, section included)

**P50 = 123 · P95 = 143 · MAX = 143** characters. The longest is Part 3 (its file name is
the longest). Nothing exceeds the 143-char budget the report asked to check for bloat.

## 5. Canary scope

**155 chunks / 3 documents** (Part 1: 50, Part 2: 54, Part 3: 51) — verified equal to the
per-document chunk counts measured independently.

## 6. Prefix distribution inside the canary

**legacy 58** (Part 1: 27, Part 2: 31) · **current 0** · **no_prefix 97** (Part 1: 23,
Part 2: 23, Part 3: 51). Zero chunks carry two headers. `--execute` would rewrite all 155
(the 58 legacy headers are REPLACED, never appended to).

## 7. Family relation (dry run)

| part | role | related_common_spec |
|---|---|---|
| Part 1 | `common_spec` | — |
| Part 2 | `specific_spec` | Part 1 |
| Part 3 | `specific_spec` | Part 1 |

## 8. Blank templates

Detection is `is_blank_response_template` (fill-in marker + cell fill ratio). Live markers
per part: **Part 1: 0 · Part 2: 58 · Part 3: 54** occurrences of 项目单位填写/投标人填写/
项目单位提供/投标人提供. The per-chunk counts are printed by
`tools/scripts/backfill_prefix_preview.py`; the detector is frozen and no fallback agent
was built.

## 9. Before benchmark

`../scripts/audit/retrieval_benchmark_before.md`, 6 query classes, lexical leg over `content_ltks` (the only
leg Phase A can move):

**Recall@5 = 3/6 · Recall@10 = 3/6 · MRR = 0.333**

| query | class | first expected passage | R@5 | R@10 |
|---|---|---|---|---|
| A | exact standard number | not found | 0 | 0 |
| B | natural language, no number | rank 2 | 1 | 1 |
| C | three-core | not found | 0 | 0 |
| D | generic part | rank 2 | 1 | 1 |
| E | disambiguation | rank 1 | 1 | 1 |
| F | blank template | not found | 0 | 0 |

Two findings from writing it: a raw question string matches NOTHING in `content_ltks` (the
stored field holds the ingest's own tokens, so the benchmark tokenizes the question the
same way — this is the tokenizer defect the audit reported, visible here as 0 hits); and
this is the LEXICAL leg alone, so it under-reports the production hybrid. A, C and F are
the canary's targets.

## 10. Execution script and rollback

`tools/scripts/phase_a_canary.py`:

* `--dry-run` is the default; `--execute` is required to write anything;
* `--family` is a whitelist resolved in TWO phases (token match, then the name family that
  match belongs to) — a single-phase token filter silently EXCLUDED Part 3, whose file
  name carries no number and whose chunks carry no header at all;
* `--snapshot` writes `chunk_id -> content_with_weight / content_ltks / content_sm_ltks`
  to `phase_a_snapshot_<UTC>.json` BEFORE the first write; `--restore <file>` puts it back;
* counters: `attempted / changed / unchanged / skipped / failed`, and a failed chunk is
  printed and counted, never swallowed (exit code 1 if any failed);
* idempotent by construction (`split_retrieval_header` + `retrieval_text`: a second run
  finds `unchanged` for every chunk it wrote);
* the re-tokenization drops the OLD header's tokens and prepends the new header's, so the
  stored lexical fields stay consistent with the text they represent.

## 11. Tests

`test/unit_test/rag/nlp`: **169 passed** (up from 148), including 21 projection cases and
the new section regression cases. `ruff check` clean on every touched file.

## 12. Exactly what `--execute` would modify

**155 ES documents in the index** (one per chunk, `_update/<chunk_id>`), each rewritten in
three fields: `content_with_weight` (header replaced), `content_ltks`,
`content_sm_ltks`. Restricted to the three documents named in §5; **0 mutations outside
the family**, enforced before any candidate is built. Vectors (`q_3072_vec` and friends),
MySQL, MinIO, the index mapping and the chunk `_id` are untouched. The exact 155 chunk ids
are listed in `phase_a_canary_report.md` under "Chunks that would change".

## Stopping here

No `_update_by_query`, no ES mutation, no MySQL write, no embedding, no re-parse, no
mapping change, no `vector_similarity_weight` change, no reranker change, no fallback
agent. Waiting for explicit approval to run `--execute`.
