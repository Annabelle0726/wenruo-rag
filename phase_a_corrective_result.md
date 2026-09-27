# Corrective migration result: CONVERGED — 0 changed / 155 unchanged

Approved write executed on the 60 chunks only. Nothing else was touched.

## Three states, three artifacts

| state | meaning | artifact |
|---|---|---|
| **S0** | before the Phase A canary | `phase_a_snapshot_20260927T095014Z.json` (496 907 bytes) — untouched, not reused |
| **S1** | after the canary, before the corrective write | `phase_a_corrective_snapshot_20260927T181012Z.json` (640 721 bytes, written before the first corrective write) |
| **S2** | after the corrective write | the live index now |

## Pre-write guard (re-run, matched)

`tools/scripts/phase_a_readiness_check.py` → would change **60**, unchanged 95, census
`null_to_non_null: 60`, `section_removed 0`, `section_changed 0`, `same_section 0`, raw-body hash
on 155/155, verdict READY, exit 0. The S0 snapshot was verified still present before writing.

## The write

`phase_a_canary.py --family 73286 --execute --snapshot --snapshot-path phase_a_corrective_snapshot_<UTC>.json`
→ **attempted 155 / changed 60 / unchanged 95 / skipped 0 / failed 0**. The 60 are exactly the
readiness-approved set: the executor and the checker share
`retrieval_projection.project_chunk()` and `token_fields()`, so "60" means the same thing in both.

Only `content_with_weight`, `content_ltks` and `content_sm_ltks` were sent, per chunk, to
`_update/<chunk_id>`. No vector, no chunk id, no metadata mapping, no MySQL, no MinIO.

## Post-write acceptance

| check | result |
|---|---|
| **convergence: readiness checker** | **would change 0 / unchanged 155**, census empty, reasons all zero |
| **convergence: canary dry run** | **attempted 155 / changed 0 / unchanged 155 / failed 0** |
| headers present / family | 155 / 155 |
| double header | 0 |
| core counts | Part 1 **absent**, Part 2 **单芯**, Part 3 **三芯** (each document one value, no mixing) |
| **outside-family state** | hash `8a80b385702e38f4…` **identical** to the S0 guard hash → **outside mutation = 0** |
| raw body | unchanged by construction (the diff was the header only; the zero-change convergence proves it) |
| S1 → S2 benchmark (same queries, labels, weights, path) | **no rank change on any query**: R@5 4/6, R@10 4/6, MRR 0.422, per-query first-rank A -, B 3, C -, D 1, E 1, F 5 |

No regression, so S2 is kept. **No rollback.**

## Two cosmetic defects in my own tooling, stated rather than hidden

1. `phase_a_readiness_check.py` exits 1 when the family needs no change, because its READY
   verdict requires `changed == 60`. After a successful migration the correct reading is "nothing
   left to do", so the exit code is misleading even though the numbers are right.
2. An inline verification one-liner reported `malformed: 155` because it tested
   `header.endswith("] ")` on a string it had already stripped the trailing space from. The real
   signal in the same run — 155/155 headers present with a standard number — stands; the
   malformed counter was wrong.

Neither affects the data or the acceptance result.

## Part B — Retrieval trace: still **TRACE NOT VALIDATED**

Not attempted this round (the corrective write was the priority, and the trace is explicitly a
separate task). Nothing was inferred about A/C. The plan is unchanged: find the deployed
construction path for the embedding bundle (`dialog_service` → retrieval → `Dealer.retrieval`)
by reading the container's own code, adapt `retrieval_trace.py` to it, then run the E smoke test
before any A/C stage.
