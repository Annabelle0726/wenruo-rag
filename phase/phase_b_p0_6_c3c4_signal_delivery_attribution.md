# C3/C4 Signal-Delivery Attribution — Final Matrix, First Divergence, Closure Verdict

Gates held throughout: **no product code changed, no database row touched, `latest` NOT retagged,
P0-7 NOT deployed, `Phase B P0 complete` NOT declared, P1 LOCKED.** The only edits were to the
acceptance harness, which is exactly what this round authorised.

---

## 1. Send path — PROVEN (un-stubbed)

| item | observation |
| --- | --- |
| route used | `/chat/ccddcfdeba3a11f1a4910547a12ee1d1?conversationId=8878fd6aba4311f1a14689aca29561bb` |
| landed URL | identical (no redirect, no crash) |
| composer | present |
| **trigger** | a plain `Enter` in the composer |
| **request** | **`POST /api/v1/chat/completions`** via `fetch` (captured by hooking `fetch` **and** `XMLHttpRequest`) |

No stub was in place for this step, so this is a real request against the live backend. No dataset/model
precondition had to be invented — the chat already has a bound dataset and model. **No database,
conversation state, or product code was modified to make the send happen.**

## 2. Chain ladder on the real request (stub replaces ONLY `retrieval_health`)

The observed request is intercepted and answered with the production SSE framing; only the
`retrieval_health` object is substituted.

Framing note that mattered, recorded because it was my harness defect and not an app defect:
`mergeAnswerChunk` **drops a final chunk's own text** when an earlier chunk already produced text, and the
real backend therefore sends the reference on a terminal frame with an **empty** answer. My first stub put
its marker on that terminal frame, which made step 3 look false for a reason that had nothing to do with
the app. Corrected to the production shape: marker on a non-final delta, `{answer:"", reference:{…}, final:true}`.

| # | ladder step | C3 `degraded` | C4 `failed` |
| --- | --- | --- | --- |
| 1 | Completion Request observed (`POST /api/v1/chat/completions`) | **TRUE** | **TRUE** |
| 2 | Response Received (200, `text/event-stream`, 1 intercept, no `requestfailed`) | **TRUE** | **TRUE** |
| 3 | Terminal frame processed by the app (stub marker rendered in the DOM) | **TRUE** | **TRUE** |
| 4 | Exactly one toast in the DOM with the approved copy | **FALSE** | **FALSE** |

DOM evidence at step 4: the sonner container **is** mounted
(`<section aria-label="Notifications alt+T">`) but is **empty** — `{ ol: 3, li: 0 }`, i.e. **no toast
element was ever created**. No console error, no unhandled rejection, zero sensitive markers on screen,
removed phrase absent.

## 3. First Divergence

> **Between "terminal frame processed by the app" (proven TRUE) and "toast present in the sonner container"
> (proven FALSE).**

That is the `chunk.final` branch in the chat stream driver, where `flushAnswer()` (observed working — the
answer rendered) is immediately followed by the notice-mapper call. So the divergence sits in the
**notice mapper → sonner** segment.

**Classification, stated at exactly the strength the evidence supports:**

* It is **not** the send path (proven).
* It is **not** the response transport (proven).
* It is **not** the harness's userInfo or route (both corrected and shown to render).
* It **is** a **P0-6 PRODUCT DEFECT CANDIDATE — First Divergence at the Notice Mapper → Sonner boundary.**

**What I could not narrow further, and why:** the notice module is bundled and not externally observable, so
I cannot yet distinguish "mapper returned `null`" (i.e. `retrieval_health` was not on the object the mapper
received) from "mapper returned a kind but the sonner call produced no element". Establishing which one
requires either a temporary instrumented build of the UI (a build, not a product change) or a jsdom-level
render of the app's real `Sonner` component against the same stub — both are next-round work. I did not
guess, and I did not change product code to make it pass.

Per the agreed rule — *signal entered the mapper path but no DOM toast → confirm P0-6 product defect, stop
and report First Divergence* — **I stopped here.**

## 4. C1–C6 Final Matrix

| case | surface | expected | observed | status |
| --- | --- | --- | --- | --- |
| C1 `full` | real completion path | silent | 0 toasts | **PASS** |
| C2 no signal | real completion path | silent | 0 toasts | **PASS** |
| C3 `degraded` | real completion path, `retrieval_health` substituted | exactly 1, approved zh copy | ladder 1-3 TRUE, **0 toasts** | **FAIL — First Divergence (§3)** |
| C4 `failed` | real completion path, `retrieval_health` substituted | exactly 1, approved zh copy | ladder 1-3 TRUE, **0 toasts** | **FAIL — First Divergence (§3)** |
| C5 history hydrate | reloaded conversation | silent | 0 toasts | **PASS** |
| — | removed exaggerated phrase | absent | absent | **PASS** |
| — | sensitive-material leaks | none | none | **PASS** |

**C1–C6 Browser Acceptance: 3/5 — NOT ACCEPTED.** The two failures are no longer "unattributed": they are
now localised to the mapper→DOM segment on an otherwise proven end-to-end path.

## 5. Final Image / Tag Mapping (unchanged — no promotion)

| artifact | tag | image id | deployed? |
| --- | --- | --- | --- |
| running production | `my-wenruorag:p0-6-ui-copy-984e7036` | `bf990b5846f4` | **yes** (0 restarts) |
| `latest` | `my-wenruorag:latest` | `858c04e89fdd` | **NOT retagged** |
| rollback anchor | `my-wenruorag:rollback-pre-p0-20260927` | `c50436820cb9` | retained |
| P0-7 candidate | `my-wenruorag:p0-7-obs-9f3d2c79` | `ea93cd3bb795` | **NOT deployed** (gate PASS, held) |
| earlier candidates | `p0b-leg-6543f5a3` / `p0b-fix-b72e9540` / `p0b-891572a71` | `8694a5b943dc` / `be80f1b49b45` / `99d0ee210004` | retained |

Credential KEY_2 `062bcd934443` unmodified. Every promotion step in the agreed order remains **blocked at
its first gate** (C1–C6 PASS), so the strict sequence was not entered.

## 6. Backlog (log only — NOT fixed in this window)

**Frontend API Shape Validation Debt** — `useFetchSessionList` types its payload as `IConversation[]`,
declares `initialData: []`, and then returns `data.data` **unvalidated**. Any non-array response reaches
`dialogList.find(...)` in `pages/next-chats/chat/index.tsx:152`, which throws
`TypeError: N.find is not a function` and drops the whole page into its error boundary. Reproduced
deliberately: a chat id the caller cannot use makes the sessions endpoint answer
`{"code":108,"data":false,"message":"no authorization"}`, the receiver becomes `false`, and the page dies
instead of showing a message.

* Not fixed, by instruction. No frontend code was modified.
* Suggested shape of a future fix (for the backlog, not authorised now): validate/normalise the payload at
  the hook boundary (coerce a non-array to `[]` and surface the API's message instead of crashing), and
  treat a `code:108` refusal as a user-facing error rather than a render error.

---

## 7. Phase B P0 Closure Verdict

**NOT CLOSED.** Blocking reasons, in order:

1. **C3/C4 fail** with a First Divergence at the Notice Mapper → Sonner boundary (§3) — an unresolved
   candidate product defect in P0-6, which is the whole point of P0-6.
2. `latest` is therefore **not** promoted to `bf990b5846f4`.
3. The gate-verified P0-7 image `ea93cd3bb795` is therefore **not** deployed, so no live P0-7 log
   acceptance has been run and no operator event has ever been emitted in production.

| milestone | status |
| --- | --- |
| P0-A Health Contract | **PASS** |
| P0-B Production Wiring | **PASS** |
| P0-C Live Core Acceptance | **PASS** |
| **P0 CORE RUNTIME** | **PASS** |
| P0-6 User Disclosure UI | candidate deployed; **C3/C4 defect open** |
| C1–C6 User-visible Acceptance | **3/5 — FAIL** |
| P0-7 Operator Observability | implemented + gated (PASS); **not deployed** |
| P1 | **LOCKED / NOT ENTERED** |

### Next round, to unblock (each needs your go-ahead)

1. **Narrow the First Divergence** with a temporary *diagnostic* UI build (not a product change): instrument
   the notice module to report whether it was invoked and what kind it returned, then re-run C3/C4 against
   that build. That decides between "no `retrieval_health` on the mapper's input" and "mapper ok, sonner
   silent" — and therefore which code owns the fix.
2. Only after C3/C4 pass: retag `latest` → `bf990b5846f4` (or the fixed image) → deploy `ea93cd3bb795`
   (or its successor) → live P0-7 log acceptance (`docker logs`, one line per retrieval, exactly nine
   fields, zero sensitive content) → promote to the production baseline.
3. Backlog item in §6 remains unfixed by instruction.
