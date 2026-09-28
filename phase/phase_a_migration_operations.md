# Migration artifacts and operations record

The two rollback artifacts are deliberately NOT in Git: they are large, they carry a
compressed copy of the corpus they protect, and a version control system is the wrong place
for a restore point. They stay in the workspace, are never moved or deleted by tooling, and
are recorded here by hash so their identity can be checked at any time.

| artifact | semantic meaning | size (bytes) | SHA-256 | created (UTC) | ES index | git commit at creation |
|---|---|---|---|---|---|---|
| `phase_a_snapshot_20260927T095014Z.json` | **S0** — the state before the Phase A canary touched anything (the 155 family chunks) | 496 907 | `7FE6861AA2453F003C14084640E31382A12F184F8B6E9F84F01A2C29212D9694` | 2026-09-27T09:50:14Z | `ragflow_a9e28731ab7011f19b833887d563fb04` | `eb11fbe1ad9a5e629c6a8e466386a2b9c6d5637a` |
| `phase_a_corrective_snapshot_20260927T181012Z.json` | **S1** — after the canary, immediately before the corrective write | 640 721 | `30355F3C7A2B68513643844104322F16D9CC105B497E20A0DD520BF6F004642A` | 2026-09-27T18:10:12Z | `ragflow_a9e28731ab7011f19b833887d563fb04` | `5736aeaf8` (the commit the corrective write was executed from) |

**S2** is the live index as it stands now: `CONVERGED`, i.e. `0 changed / 155 unchanged` and no
validator finding, verified by `tools/scripts/phase_a_readiness_check.py` (exit 0).

Each snapshot holds, for every chunk it covers, `content_with_weight`, `content_ltks` and
`content_sm_ltks` — the three fields a Phase A migration may change, and nothing else. Restoring
one is `phase_a_canary.py --restore <file>`.

## Restore order, should it ever be needed

1. `--restore phase_a_corrective_snapshot_20260927T181012Z.json` returns the corpus to S1.
2. `--restore phase_a_snapshot_20260927T095014Z.json` returns it to S0.

They are separate states on purpose: S1 is the state the corrective migration was approved
against, so restoring it undoes only the section fix, while S0 undoes the whole Phase A.

## Suggested future location (not actioned)

If the deployment grows a controlled artifact store, these two files are its first entries.
Nothing was uploaded anywhere this round, per instruction.
