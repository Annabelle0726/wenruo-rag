# Browser Acceptance Blocker — Classification, C1–C6 Results, and P0 Milestone Matrix

Gate discipline held: **`latest` was NOT retagged, `p0-7-obs-9f3d2c79` was NOT deployed, Phase B P0 is NOT
declared complete, and P1 remains LOCKED.** No product code, no production data, and no configuration was
changed in this round; the investigation was read-only, and the only edits were to the acceptance harness.

---

## 1. Blocker classification: **TEST_HARNESS_STATE_ARTIFACT**

### 1.1 Verdict

`TypeError: N.find is not a function` on the chat page is **not a product defect**. It was caused by the
acceptance harness navigating to the wrong route shape. With the correct route the page renders normally in
real Chrome against the deployed bundle.

### 1.2 Evidence chain (each step measured, not inferred)

| # | observation | method |
| --- | --- | --- |
| 1 | The crash reproduced with **both** userInfo shapes — the one my harness used (`{email,id,avatar,language}`) and the one the app's own login handler writes (`{avatar,name,email}`) | real Chrome, two contexts |
| 2 | The app's login handler writes exactly `userInfo = {avatar, name, email}` (`use-login-request.ts:89-98`) — my earlier shape was wrong, but **not** the cause | source read |
| 3 | No uncaught error, and no non-array `Array.prototype` read: the failing `.find` is read off a **primitive/plain object**, whose property lookup never touches `Array.prototype` | runtime traps on `Array.prototype.{find,forEach,map,...}` |
| 4 | The only `.find` on the chat page's render path is `chat/index.tsx:54/152`: `const { data: dialogList } = useFetchSessionList(); … dialogList.find(...)` | static search (4 hits in `pages/next-chats`) |
| 5 | `useFetchSessionList` returns `data.data` **verbatim** while typing it as `IConversation[]` | source read (`hooks/use-chat-request.ts`) |
| 6 | The app calls `GET /api/v1/chats/{routeParam}/sessions`. With a **conversation** id it answers `{"code":108,"data":false,"message":"no authorization"}` → `dialogList === false` → `false.find` throws exactly this TypeError | direct authenticated API call |
| 7 | With a **chat** id the same endpoint answers `{"code":0,"data":[…]}` (a list) | direct authenticated API call |
| 8 | Navigating to `/chat/<chatId>` renders the page: composer present, **no crash**, and the app itself rewrites the URL to `?conversationId=…` | real Chrome |

### 1.3 Root cause, precisely

The route is `/chat/:id` where `:id` is the **chat (assistant)** id; the conversation is carried in the
`conversationId` query parameter that the app appends itself. The harness navigated to
`/chat/<conversationId>`, so the sessions endpoint refused it with `code:108` and `data:false`, and the page
then called `.find` on `false`.

**Correction applied: harness only** — new route constant plus the login-handler `userInfo` shape. **No
product code was touched**, no database row was modified, and nothing was forced through by changing data
(the earlier temptation to reshape the `conversation.reference` column was not taken).

### 1.4 Honest residual (not a claim of product soundness)

Two observations are recorded rather than acted on, because acting on them would exceed this round's
authorisation:

1. `useFetchSessionList` types its payload as an array and returns `data.data` unvalidated, so **any**
   non-array response (an error frame, a future paginated shape) reaches `dialogList.find` and crashes the
   page into its error boundary. The correct route avoids the trigger; the unguarded call remains.
2. The API answers `code:108 "no authorization"` for a chat id the caller cannot use, and the frontend
   converts that into a render crash rather than a message. This is a robustness gap, **not** the cause of
   this blocker, and it needs an explicit decision before anyone changes frontend code.

### 1.5 Method note (what was deliberately avoided)

No account password was hardcoded. The session was provisioned server-side using the app's own serializer
(`URLSafeTimedSerializer`) and the deployment's own secret from Redis DB1 — i.e. the same material the login
endpoint issues — and then written in the exact format `use-login-request` writes. Repeated login attempts
did **not** mutate any account.

---

## 2. C1–C6 Browser Acceptance: **3 / 5 PASS — NOT ACCEPTED**

Real Chrome, deployed bundle (`bf990b5846f4`), zh UI, real session, only the completion HTTP response stubbed.

| case | expected | observed | result |
| --- | --- | --- | --- |
| C1 `full` | silent | 0 toasts | **PASS** |
| C2 no health signal | silent | 0 toasts | **PASS** |
| C3 `degraded` + quota | exactly 1, exact zh sentence | **0 toasts** | **FAIL** |
| C4 `failed` | exactly 1, exact zh sentence | **0 toasts** | **FAIL** |
| C5 history hydrate | silent | 0 toasts | **PASS** |
| — | removed exaggerated phrase absent, zero leaks | absent; no leaks | **PASS** |

**Why C3/C4 failed, stated as a fact and not a guess.** The negative cases (which assert *absence* of a
toast) pass, and the crash is gone, so the page and session are sound. The two positive cases produced no
toast **and no error**, which means the notice never had a signal to act on: the send did not reach the
intercepted completion request. A request-tracing run was started to prove that directly (log every
`fetch` URL during a send) but its script hit a string-escaping defect of my own and the window's budget
ended before it ran. So the remaining question is precisely:

> Does pressing Enter in the composer actually issue a `/chat/completions` request for this conversation,
> or does the send require a dataset/model selection (the composer may be inert until one is chosen)?

Until that is answered, the C3/C4 failures are **unattributed** — they are equally consistent with
"harness could not drive the send" and with "the notice does not fire". I am not claiming either.

**Consequence, per the agreed promotion order:** C1–C6 have **not** passed, therefore:
* `my-wenruorag:latest` stays at **`858c04e89fdd`** — no retag;
* `my-wenruorag:p0-7-obs-9f3d2c79` (`ea93cd3bb795`) stays **undeployed**;
* the running container stays on the corrected candidate `bf990b5846f4`, and `rollback-pre-p0-20260927`
  still resolves to `c50436820cb9`.

---

## 3. P0 Milestone Matrix

| milestone | status | evidence / blocker |
| --- | --- | --- |
| **P0-A** Health Contract | **PASS** | contract + producer API unchanged in behaviour; 6/6 injection regression |
| **P0-B** Production Wiring | **PASS** | boundary leg facts; healthy-path gate with its negative regression; 5/5 frozen injections on the deployed modules |
| **P0-C** Live Core Acceptance | **PASS** | live healthy path `overall=full`, zero contract violations |
| **P0 CORE RUNTIME** | **PASS** | deployed and re-verified after the silent-revert incident |
| **P0-6** User Disclosure UI | **candidate deployed** (`bf990b5846f4`) | corrected copy live and byte-verified; `latest` not promoted |
| **C1–C6** User-visible Acceptance | **3/5 — NOT ACCEPTED** | C1/C2/C5 PASS; C3/C4 fail unattributed (send did not reach the stubbed completion) |
| **P0-7** Operator Observability | **IMPLEMENTED + GATED, NOT DEPLOYED** | gate PASS (one line, exact 9 fields, zero leaks); frozen injections 5/5 on the modified producer; image `ea93cd3bb795` built |
| **P1** | **LOCKED / NOT ENTERED** | by instruction |

**`Phase B P0 complete` is NOT declared.** Three things stand between here and closure: C3/C4 unattributed,
`latest` unpromoted, P0-7 undeployed.

### Next actions (needed, each gated)

1. **Finish the send diagnostic** for C3/C4 (trace whether a `/chat/completions` request is issued on send;
   if not, drive the composer correctly — dataset/model selection or the send control). *No product change.*
2. Only then: C1–C6 re-run → retag `latest` → deploy `ea93cd3bb795` → log spot-check → promote.
3. Separate decisions, still open: the unguarded `dialogList.find` robustness gap (§1.4); the recommended
   location-restriction reason code (deliberately not added).

---

## 4. State at the end of this round

| item | value |
| --- | --- |
| running image | `my-wenruorag:p0-6-ui-copy-984e7036` = `bf990b5846f4`, 0 restarts |
| `latest` | `858c04e89fdd` (**not** retagged) |
| rollback tag | `c50436820cb9` |
| P0-7 image | `my-wenruorag:p0-7-obs-9f3d2c79` = `ea93cd3bb795` (built, undeployed) |
| credential | KEY_2 `062bcd934443`, unmodified |
| product code / data / config | **unchanged this round** |
| harness state | corrected (route + login-handler userInfo); session material deleted after use |
