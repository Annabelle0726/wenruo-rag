# Phase B — Numeric Rev 3.1: Intent Binding Repair ONLY

**Scope.** Intent binding only. `decomposition.py` was NOT touched this window (sha256 `ee2a060d…`, identical
to the Rev-3 commit), so the original-offset contract, the normalization mapping and the projection are
provably unchanged rather than merely still green. `chunk_profile.py` is the only changed product file.
`METADATA_PROVENANCE_CONTRACT = BLOCKED` and nothing metadata-side, consumer-side, P0-side or planner-side
was modified.

## 1. Red first

`deploy/repair_gates/test_qv_revision31_gate.py` was written before any product change and run against
`e211bea5c`: **21 failed / 14 passed** (35 cases). All six kill-audit counterexamples failed, as did every
I1 separator, I2 coordination, I3 copula, two I4 cases, the same-literal stress gate and - the point of the
exercise - both architecture tests including the success condition.

## 2. `INTENT_BINDING_ARCHITECTURE_BEFORE`

```
attribute cue found ANYWHERE in the sentence
    -> promote EVERY occurrence of that attribute
        -> a locator rule subtracts some of them again
```

`_asked_starts` scanned the whole question: `for attribute, cue in _ASKED_ATTRIBUTE_CUES.items(): if
cue.search(text): asked.update(every occurrence with that attribute)`. Everything R1-R6 reports follows from
that: a question about one object's edition promoted another object's edition, a question about one model
code promoted the model code in the clause before it, and a standard named in one clause was promoted by a
question asked about a different object in the next clause. The locator rule ran *afterwards*, which is why
it could not save the cases where no locator cue happened to be present (R4) and why its own whitespace bug
(`any(char in _CLAUSE_EDGE_CHARS for char in gap)` rejected `" Q/GDW "`) left R1/R3/R6 to the global path.

## 3. `INTENT_BINDING_ARCHITECTURE_AFTER`

```
local semantic span (clause, and inside it the questioned target's scope)
    -> local predicate / question target (cue, comparison connective, list interrogative, locator)
        -> bind ONLY the eligible occurrence(s) in that span
```

* `_clause_spans` splits on question punctuation (`.` deliberately excluded - it is the decimal point of
  `12706.2`), and `_is_interrogative` marks a clause by a marker or by the question mark closing it.
* `_cue_bound_starts` binds a cue's attribute occurrences **only inside the cue's own clause**, **only when
  that clause is interrogative**, and **only from the clause's target scope onwards** - the scope beginning
  after its last subject-shift word (`待选`/`待审`/`询问`/…), which is what separates "known context" from
  "the object being asked about".
* `_locator_bound_starts` requires a clause edge, rejects a cue whose complement is the copula
  (`_locator_is_preposition`), tolerates any whitespace inside the object phrase, and binds **every**
  coordinated object of the same attribute (`_coordinated_objects`).
* `_compared_starts` is unchanged in spirit: a connective binds the two figures it compares; a list
  interrogative binds the list in front of it (a list is one constituent, so that span may cross the comma
  that separates it from its interrogative - stated explicitly, because the clause-locality invariant is
  about CUE binding).

No path remains that promotes an occurrence because a cue exists somewhere in the sentence.

## 4. The six counterexamples, measured across three code versions

`question_value_revision31_parent_regression.json` (PARENT = the deployed build's QV layer, Rev 3 =
`e211bea5c`, Rev 3.1 = this revision):

| case | PARENT | REV 3 | REV 3.1 |
|---|---|---|---|
| R1 | `['2026','2025']` | `['2026','2025']` | **`['2025']`** |
| R2 | `['123','800','456']` | `['123','800','456']` | **`['800','456']`** |
| R3 | `['2026','2025','800','2024']` | `['2025','800','2024']` | **`['800','2024']`** |
| R4 | `['73286.2','2026','800']` | `['73286.2','2026','800']` | **`['800']`** |
| R5 | `['123','1.8','2.0']` | `['123','1.8','2.0']` | **`['1.8','2.0']`** |
| R6 | `['2026','2025','1.8']` | `['2025','1.8']` | **`['2026','2025','1.8']`** |

**R6 parent-vs-Rev3 regression, explicitly recorded:** the PARENT returned `['2026','2025','1.8']`; Rev 3
returned `['2025','1.8']`, having read the questioned subject `依据` as a preposition and demoted the first
answer; Rev 3.1 returns `['2026','2025','1.8']` again - the same answer set, now with the correct
attribution (`2026`/`2025` are `IDENTITY_VALUE_EXPLICITLY_ASKED_BY_USER`, not bare figures).

## 5. Gates

| run | result |
|---|---|
| Rev 3.1 gate, Rev 3 arm | **29 failed / 13 passed** (2 gate files failed) |
| Rev 3.1 gate + mutation arm, Rev 3.1 arm | **42 passed / 0 failed** |
| whole suite (Rev-1 gates, Rev-2 gate, Rev-2 occurrence gate, Rev-2 mutation arm, Rev-3 gate, Rev-3 mutation arm, Rev-3.1 gate, Rev-3.1 mutation arm, repository unit tests) | **307 passed / 0 failed** |
| closed regressions | 29 |

Negative arm: five mutants, each caught - global same-attribute promotion, a locator that stops at ordinary
whitespace, only the first coordinated object protected, the locator noun beating choice intent, and a
declarative `型号为` treated as interrogative.

## 6. Persistence of the Rev-3 PASS areas (explicit regression report)

* **Original offsets**: unchanged. `decomposition.py` is byte-identical to Rev 3, and every Rev-3 round-trip
  test still passes inside the 307-pass suite.
* **Normalization mapping**: unchanged, same file.
* **Supported unit classification**: unchanged (`_match_unit`, `_unit_patterns`, `_unit_boundary_ok` were not
  edited this window); the whitespace-spelling tests still pass.
* **Pool independence**: unchanged and still asserted on signature and name tables.
* Same-literal preservation and the occurrence record model: unchanged, and extended by the new four-role
  stress gate (`根据 2026版 与 AB2026CD 的 2026mm² 数据，待选型号为 EF2026GH 吗？` - one literal, four
  occurrences, four verdicts, distinct offsets).

No semantic delta exists outside intent binding: `git status` for this window lists `chunk_profile.py` and
nothing else.

## 7. Artifacts

`rag/retrieval/chunk_profile.py`; `deploy/repair_gates/test_qv_revision31_gate.py`,
`test_qv_revision31_mutation_arm.py`, `qv_revision31_run.py`, `qv_revision31_parent_regression.py`,
`question_value_revision31_result.json`, `question_value_revision31_parent_regression.json`; this report;
`AGENTS.md`.

## 8. Production

Unmutated: `wenruo-rag-cpu` runs `sha256:6e926b5d8ef6…`, 0 restarts, `my-wenruorag:latest` still
`6e926b5d8ef6`, rollback anchor `c50436820cb9`. No deploy, no candidate build, no retag, no parameter change.
G4 remains `BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY`; P1-2 remains PAUSED; QGDW recovery remains
`NOT_ESTABLISHED`.
