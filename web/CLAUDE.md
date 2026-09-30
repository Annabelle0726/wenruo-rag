# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the RAGFlow frontend (`web/`).

## Project Overview

RAGFlow frontend is a React/TypeScript application built with UmiJS:

- **Components**: shadcn/ui
- **Styling**: Tailwind CSS
- **State**: Zustand
- **Data Fetching**: TanStack Query (React Query)
- **i18n**: react-i18next

## Common Commands

```bash
npm install
npm run dev        # Development server
npm run build      # Production build
npm run lint       # oxlint
npm run format     # oxfmt
npm run test       # Jest tests

```

## Development Conventions

### Design System, Theme & Branding

* **Header & Theme Color**: The top header uses State Grid Green (国网绿 `#005c3f`). All header items, icons, and navigation text must maintain high-contrast white text (`text-white` / `text-white/85`) in both Light and Dark modes.
* **Brand Logo & Lockup**: `BrandLockup` uses a transparent logo mark (`brand-mark.png`) paired with white HTML text (`header.brandShort`). **Do not** add white card backgrounds, borders, or hover background rectangles around the logo entrypoint.
* **Supported Languages**: The system strictly supports **ONLY Simplified Chinese (`zh`)** and **English (`en`)**. The language switcher is a single-click button toggling directly between `zh` and `en`. Do not add or propagate keys to other language files.
* **Table Component**: Data tables must support zebra striping (斑马纹) with alternating row background colors for enhanced readability.
* **Dark & Light Modes**: Full dark and light mode support is mandatory across all components. Ensure text visibility and proper contrast against backgrounds in both modes (especially in dark mode where default dark text becomes invisible).
* **Theme Values Live in `web/tailwind.css`**: the light tokens are `:root`, the dark ones are the `.dark` block, and nothing else defines a surface colour (not `src/`, not a component). Retune a theme by changing those variables, never by hardcoding a colour in a component. Keep dark surfaces on ONE neutral ramp with a visible step between page, card and input — the current set is matte Slate (page `#23272f`, card `#2a2e37`, input `#31363f`, border `#3c424e`) — and keep text at comfortable rather than maximum contrast. A value declared as an `hsl()` triple must have an `#hex` sibling that resolves to the same colour. **A variable that an `rgb(var(--x) / <alpha-value>)` consumer reads (`tailwind.config.js`) or that a literal `rgb(var(--x))` reads (`src/`) must hold an RGB channel triple, never an `hsl()` triple** — the browser accepts `rgb(220 14% 16%)` and resolves it channel-wise to `rgb(220, 36, 41)`, so the two spellings are not interchangeable and a mismatch is a silently wrong colour rather than a dropped declaration. Check every consumer before changing one.
* **Dataset Files View**: the file table is an OPEN surface, not a framed card — no `Card` border/shadow, no `border` on the `Table` root class, `px-6 py-4` gutters, and no width floor on the wrapper (a `min-w-[…]` there pushes a page-level horizontal scrollbar onto narrower viewports). Long cell text truncates and the tooltip beside it carries the full value; a free-text column (e.g. a pipeline name) must not set the table's min-content width.
* **LaTeX Math Rendering**: Ensure LaTeX equations are properly rendered in markdown/chat/knowledge base components (e.g., via KaTeX/MathJax). Inline math uses `$ ... $` and display math uses `$$ ... $$`. Ensure LaTeX formulas adjust text and element colors correctly when switching between Light and Dark modes.
* **Card Grids Go Through `CardContainer`**: `src/components/card-container.tsx` owns the column policy — `grid-cols-[repeat(auto-fill,minmax(min(17rem,100%),1fr))]`, `gap-x-6 gap-y-4`, `content-start`, `scrollbar-gutter-stable` and the `data-card-grid` marker. The column count follows the width the page gives the grid, not the window's breakpoints: `lg:grid-cols-3` stopped adding columns at 1024px, so an 11-card list stayed four rows tall on a 1920px screen while a 1366×768 laptop had no room for those four rows. Never reintroduce breakpoint column counts on a card list, never append a spacer row to the grid (a spacer is a real grid row — it costs its own height *plus* a row gap of scroll height), and keep any page-level override above the 17rem floor. `xl:grid-cols-4 2xl:grid-cols-5` survives on the skills/templates/MCP grids because that is those pages' own choice on grids wider than the `page-gutter` column.
* **Page Toolbar & Pagination Rhythm**: use `.page-toolbar` and `.page-list-footer` from `web/tailwind.css` — never the literal `mb-4 … pt-8` / `mt-4 pb-5` pairs they replaced. They sit beside `.page-gutter`, which supplies the horizontal half; the vertical rhythm is defined once so six pages cannot drift apart (one already had, and the 32px gap under a 32px breadcrumb bar is what pushed the first card row down by more than a row is tall).

### Test File Placement

When tests are grouped in a dedicated directory, that directory is always named `__tests__/` — never `tests/`. Example: `src/pages/agent/utils/__tests__/extractor-transform.test.ts` for `src/pages/agent/utils/extractor-transform.ts`. Co-located `foo.test.ts(x)` files next to the source file are also fine. When you find an existing test under a `tests/` directory, move it into `__tests__/` (keep git history via `git mv`) rather than adding new tests there.

### Testing Radix Components, Dialogs and Popups

* **jsdom needs four polyfills before a Radix `Select` can be driven**: `Element.prototype.hasPointerCapture` (otherwise the click throws `TypeError: target.hasPointerCapture is not a function` from Radix itself), `setPointerCapture`, `releasePointerCapture`, and `scrollIntoView`. Use `userEvent`, not `fireEvent.click`: Radix acts on the pointerdown/pointerup sequence, and a bare click skips it.
* **A jsdom test cannot decide an interaction question.** It does not lay out or hit-test, so it PASSES things a browser fails: a popup that renders underneath a modal's overlay, or one whose click the dialog treats as an outside interaction, both look fine there. When the question is "does this dialog close / is this control reachable", drive real Chrome over CDP against the running stack — `Page.navigate`, `Runtime.evaluate` for rects, `Input.dispatchMouseEvent` / `Input.insertText` for real input, and `Runtime.exceptionThrown` + `Log.entryAdded` to catch what the page throws. Log in by minting a token and writing `Authorization` / `token` / `userInfo` into `localStorage` before navigating. To pick the theme, write `ragflow-ui-theme` — `app.tsx` overrides `ThemeProvider`'s default `vite-ui-theme` storage key, so writing the default key silently leaves every probe measuring dark. Mint the token inside the container (`User.get_id()` is `Serializer(settings.get_secret_key()).dumps(str(user.access_token))`) and check it against `/api/v1/datasets` first: an expired one just redirects the SPA to `/login`, and a probe that measures the login page still returns plausible numbers.
* **`.ts` files are loaded with the `tsx` loader by `jest-esbuild-transformer.cjs`**, so a generic arrow type parameter in a `.ts` file (e.g. `<T,>(x: T)`) fails to parse and takes every suite importing that file down with it. Write `.ts` files that avoid that syntax, or fix the loader deliberately.

### Dual-Backend Variant Conventions (Go / Python)

The frontend serves two backends, Go and Python. The active one is detected at runtime by `src/utils/backend-runtime.ts` (`/api/v1/language`, fetched once; `src/main.tsx` gates first render on it, so below the gate the variant never changes for the session lifetime). In dev, `API_PROXY_SCHEME` in `.env.development` selects which backend the dev server proxies to.

All divergence between the two backends is funneled through dispatch points. Business code never branches on backend identity.

1. Never import `@/utils/backend-runtime` anywhere except its two sanctioned boundaries (enforced by oxlint `no-restricted-imports`):
* `src/utils/backend-variant.tsx` — the dispatch primitives;
* `src/main.tsx` — the bootstrap gate.


2. Branch only through the primitives from `@/utils/backend-variant`:
* JSX: `<BackendVariant go={...} python={...} />` inside a dispatcher file (a page `index.tsx` or form dispatcher) — never inline in business components.
* Values (field names, defaults, payload transforms): `pickByBackend({ go, python })` inside an adapter file.
* Hook-level needs (e.g. a query `enabled` flag): `useIsGoBackend()`.


3. Routes never fork per backend: one route, one dispatcher component, with the variant implementations under `go/` and `python/` subdirectories. Reference example: `src/pages/dataset/setting/`.
4. Variant file naming: `Xxx.go.tsx` / `Xxx.python.ts(x)` siblings behind a same-named dispatcher, or `go/` + `python/` subdirectories for whole pages. No temporal names (`Next`, `Legacy`, `New`).
5. Small differences (a field's visibility, a field name) belong in capability-style adapter/config files reached through `pickByBackend`, not scattered inline ternaries in shared components.
6. Runtime detection (`/api/v1/language`) is the ONLY source of backend identity in app code. Never read `API_PROXY_SCHEME` / `__API_PROXY_SCHEME__` or declare that global in `src/`, and never create another backend-detection helper. The env var only configures the dev-server proxy in `vite.config.ts`.

### CSS and Layout Debugging

* **The shell is fixed height and never scrolls**: `html, body, #root` are `100dvh` with `overflow: hidden` (`src/global.less`), and the root layout is a three-row grid (`auto auto 1fr`) whose last row is `<main class="… overflow-hidden">`. The document therefore cannot scroll, so **every page must own its own scroll region** — a list page's card grid (`flex-1 overflow-auto`) is that region. Never put `h-dvh`, `min-h-screen` or `max-h-[94vh]` inside the shell: a viewport-relative height asks for a whole viewport in a region that is already one viewport minus the header and breadcrumb rows, and the excess is silently clipped by `main`'s `overflow: hidden` (that is how the agent-template grid lost its last row). Use `size-full`/`h-full` plus `min-h-0` so a region fills what it is given.
* **One page of a list fits the screen by default, and `50` is a CAP, not a default**: the page size is `effectivePageSize` — `min(viewport capacity, user maximum, 50)` — from `src/utils/list-capacity.ts`, wired in through `useSetPaginationParams`'s `size`. Capacity is measured off the live `[data-list-region]` by `useListCapacity` (columns from the grid's resolved tracks, rows from a complete item's height + the row gap, or a table's complete body rows under its header), and a partial row never counts. **Never snap a capacity to the sizes the pager happens to offer** (a region that fits 12 must ask for 12, not 10) and **never fetch a default number of records to discover the capacity**. A user selection — `?size=` or the per-path remembered value — is a *maximum*, not a mandate: remembered 50 on a 12-card viewport still pages by 12. A size derived from a measurement must never be written to `size` or localStorage; that turns a measurement into a remembered preference and one bad reading then pins the list (this is what once pinned a knowledge base to two rows).
* **The measurement never decides WHETHER a list loads**: a page renders its list region before its data (`CardContainer`/`CardGridPlaceholder` for cards, the marked wrapper for a table), so the size is known in time for the first request — but a list query must **not** be `enabled`-gated on it. A measurement that fails, is delayed or oscillates would turn a non-empty list into a permanently disabled query, and a disabled query renders as a successful empty state ("no documents"). The size follows the region; permission to retrieve the records does not. `useListCapacity` watches both the region's size (resize, zoom, sidebar) and its content (rows and cards arriving do NOT resize a `flex-1` region), and ignores a reading below `MIN_TRUSTWORTHY_CAPACITY` — a region measured mid-layout is not a page size of two.
* **One measurement, the innermost region, and a row pitch that does not move with the width**: every hook on a page shares ONE measurement (`useListCapacity` is a single module-level store; the observers are per region, not per caller — several `ResizeObserver`s publishing several readings for one box is what made a sidebar toggle refetch more than once). When regions are nested, the **innermost** `[data-list-region]` wins: a page shell may mark the box the shell gives the page, and the list inside marks the tighter box it owns, because the outer one also carries the page's header, toolbar and bulk bar. A table region declares its row pitch in `data-list-item-height` (`TABLE_ROW_PITCH_PX`); the declaration is what makes the first request exact, and a rendered row may only RAISE it. **A table row must be the same height at every width** — fixed height, `[&_td]:py-0`, no wrapping cell, fixed widths on every column but the one free-text column — or a narrower region (a collapsed sidebar) silently changes the page size. Every row that is not data (a skeleton, a spinner, an empty state, an error) must carry `data-skeleton`, and a pager living inside the region must carry `data-list-footer` so its height is subtracted rather than counted as row space.
* **Pagination geometry**: the pager is a flex sibling after the list region, so it stays on screen while the region scrolls; the region itself is `overflow-auto` (never `hidden`) and holds exactly one page, so a normal paginated list has no scrollbar of its own. A table must not carry a viewport-relative cap of its own (`max-h-[calc(100vh-…)]`, `max-h-96` on the body): the shell already accounts for the viewport, and a second cap gave six-row tables a scrollbar. `RAGFlowPagination` always includes the effective size among its options so the control can display the size the page is really using.
* **Not every list is paginated**: a list whose items are a READING ORDER (a document's chunks on the file preview) is one continuous scroll region that loads its next block as the reader approaches the end — `useContinuousChunkList`, no page control, no page count and no page size. Pagination is for lists of peers (knowledge bases, files), where one screen holds one page.
* **Dataset detail sidebar**: Keep the name and collapse toggle on one row, with a 32px identity icon and compact metadata below. Use a full-height flex column with a non-shrinking header and a `flex-1 min-h-0 overflow-y-auto` navigation area, 36px menu rows, 4px gaps, and 16px bottom padding. Menu labels must use i18n keys; preserve collapsed icon tooltips. This is local to `pages/dataset/sidebar/`, not a shared sidebar rule.

When fixing CSS/layout issues (especially flex truncation, ellipsis, or element sizing), **always inspect the full parent hierarchy** for `flex-shrink`, `min-width`, and `overflow` constraints before applying fixes like `min-w-0`. Do not repeatedly apply the same fix without verifying the root cause.

* Before editing, explain: (1) the full flex/container hierarchy from the target element up to the nearest non-flex ancestor, (2) what constraint is actually causing the bug, and (3) how the proposed fix addresses that root cause.

### Color Tokens

When writing or modifying styles, **use the project-defined color tokens from `src/tailwind.css**` (e.g., `bg-bg-base`, `text-text-primary`, `text-text-secondary`, `text-text-disabled`, `border-border-button`, `bg-bg-card`). Do not use arbitrary hex/RGB values or Tailwind's default palette colors directly in component class names. These tokens are defined for both light and dark modes and keep the UI consistent with the design system.

### Scope and Boundaries

Respect explicit boundaries from the user. If the user says **"only fix the selected line"** or **"do not touch shared types/files"**, follow that instruction exactly. Do not investigate unrelated errors, modify shared schemas (e.g., `LlmSettingFieldSchema`), or refactor other files without confirmation. If a change outside the described scope seems necessary, ask for permission first.

### Internationalization (i18n)

For translation tasks, add keys **only to `src/locales/zh.ts` and `src/locales/en.ts**`. Do not auto-propagate changes to other language files.

* **Style for `en.ts**`: Sentence case — first word capitalized, rest lowercase (e.g., `referenceAnswer: 'Reference answer'`). Proper nouns remain as-is.

### React Component Refactoring

When refactoring or extracting components, **verify layout behavior after each structural change** (especially `flex-1`, conditional rendering, or flex direction changes). Check that existing buttons, alignment, and responsive behavior remain intact. After extraction, verify: (1) all original props and behavior are preserved, (2) layout in parent contexts is identical, and (3) no syntax or type errors were introduced.

### State Management and Data Fetching

#### Query Key Factory (Mandatory)

**Never write raw `queryKey` arrays inline.** Always use a query key factory object that returns `as const` tuples. Raw arrays duplicated across `useQuery` and `invalidateQueries` are brittle, unreadable, and cause stale-cache bugs when key structures drift.

* Place the factory in the same file as the hooks, named `{Domain}Keys` (e.g., `LlmKeys`, `DatasetKeys`).
* Every `useQuery` and every `invalidateQueries` must reference the same factory function.
* Use `as const` on each factory return value for type-safe readonly tuples.

#### Cache Debugging

For React Query / cache invalidation bugs, **carefully compare query keys across all consuming components and mutation hooks**. Mismatched keys are a common root cause of stale data or duplicate requests.

#### Colocate Queries with the Consuming View

**Fire a query in the component that renders its data — not in a parent page.** When a page switches between mutually exclusive views (tabs, view modes), extract each view into its own component that issues its own requests on mount.

### Network Request Layering

HTTP requests are organized in three layers. **Never import `@/utils/request`, `@/utils/next-request`, or `@/utils/api` directly inside a hook**:

1. `src/hooks/use-xx-request.ts(x)` — React Query hooks; only call the service layer.
2. `src/services/xx-service.ts` — Register endpoints via `registerNextServer`, all going through `@/utils/next-request`.
3. `src/utils/next-request.ts` — The single axios instance; handles token, 401 redirects, and error notifications.

### Shared UI Component Lock

The folder `src/components/ui/` is the project's **shared UI library** — it contains both official shadcn/ui primitives and project-authored common components built on top of shadcn.

* **Do not modify, refactor, restyle, or "improve"** any file under `src/components/ui/` without explicit approval.
* Wrap or compose components outside `src/components/ui/` for custom behaviors.

### React Patterns and Conventions

* **Avoid inline event handlers** on JSX event props.
* **Prefer `requestAnimationFrame` or `useLayoutEffect**` over `setTimeout(..., 0)` for focus or DOM measurement operations.
* **Prefer `useTranslation` from `react-i18next**`.
* Use **PascalCase** for constants and component names.
* **Name things semantically, not generically.**
* **Time/date handling**: Use `dayjs`.
* **Utility hooks**: Prefer `ahooks`.
