"""Report the global breadcrumb trail on every console route.

Signs in, walks the routes that carry a breadcrumb, and prints each level with its
link target, so a jump chain can be read as text. `E2E_BASE_URL` picks the dev
server.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.getenv("E2E_BASE_URL", "http://localhost:9223")
EMAIL = os.getenv("E2E_ADMIN_EMAIL") or "admin@ragflow.io"
PASSWORD = os.getenv("E2E_ADMIN_PASSWORD") or "admin"

EMAIL_INPUT = "input[data-testid='auth-email'], [data-testid='auth-email'] input"
PASSWORD_INPUT = "input[data-testid='auth-password'], [data-testid='auth-password'] input"

TRAIL_JS = """
() => {
  const nav = document.querySelector('nav[aria-label="breadcrumb"]');
  const levels = nav
    ? Array.from(nav.querySelectorAll('li'))
        .filter((li) => !li.hasAttribute('aria-hidden'))
        .map((li) => {
          const link = li.querySelector('a');
          return {
            text: (li.textContent || '').trim(),
            to: link ? link.getAttribute('href') : null,
            current: Boolean(li.querySelector('[aria-current="page"]')),
          };
        })
    : [];

  return {
    present: Boolean(nav),
    levels,
    hasHeader: Boolean(document.querySelector('.glass-header')),
    // Enough of the page to tell "the shell is missing" from "the page is blank".
    bodyStart: (document.body.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
  };
}
"""

IDENTITY_JS = """
() => {
  const describe = (el) => {
    if (!el) return null;
    return {
      hasSvg: Boolean(el.querySelector('svg')),
      // A letter fallback would put text here; a vector mark leaves it empty.
      text: (el.textContent || '').trim(),
    };
  };

  return {
    account: Array.from(
      document.querySelectorAll('[data-testid="account-identity"]')
    ).map(describe),
    // The agent card's leading slot, and the agent editor's header slot.
    agentCard: describe(
      document.querySelector('[data-testid="agent-card"] span')
    ),
    agentHeader: describe(
      document
        .querySelector('[data-testid="agent-detail-title"]')
        ?.closest('section')
        ?.querySelector('span')
    ),
    // Anything still painting a name initial anywhere on the page.
    letterFallbacks: Array.from(
      document.querySelectorAll('[data-testid="avatar-fallback"]')
    ).map((el) => (el.textContent || '').trim()),
  };
}
"""

# The three states the rail has to keep apart: parent link, current page, separator.
STYLE_JS = """
() => {
  const nav = document.querySelector('nav[aria-label="breadcrumb"]');
  if (!nav) return null;

  const read = (el) => {
    const s = getComputedStyle(el);
    return { color: s.color, weight: s.fontWeight, size: s.fontSize };
  };

  return Array.from(nav.querySelectorAll(':scope > ol > li')).map((li) => {
    const target = li.querySelector('a, span') || li;
    return {
      text: (li.textContent || '').trim(),
      separator: li.getAttribute('aria-hidden') === 'true',
      link: Boolean(li.querySelector('a')),
      current: Boolean(li.querySelector('[aria-current="page"]')),
      style: read(target),
    };
  });
}
"""

# The pointer state of the first parent level, read while the pointer is on it.
HOVER_JS = """
() => {
  const link = document.querySelector('nav[aria-label="breadcrumb"] a');
  return link ? getComputedStyle(link).color : null;
}
"""

# The routes worth reading, with the ids discovered at runtime.
STATIC_ROUTES = [
    "/",
    "/datasets",
    "/chats",
    "/agents",
    "/searches",
    "/memories",
    "/files",
    "/files/skills",
    "/user-setting/profile",
    "/user-setting/model",
    "/user-setting/team",
    "/user-setting/data-source",
]

FIND_IDS_JS = """
() => {
  const ids = {};
  const first = (sel) => document.querySelector(sel)?.getAttribute('data-dataset-id');
  ids.datasetId = first('[data-testid="nav-dataset-item"]');
  return ids;
}
"""

API_JS = """
async (path) => {
  const auth = localStorage.getItem('Authorization');
  const res = await fetch(path, { headers: { Authorization: auth } });
  return res.json();
}
"""

MUTATE_JS = """
async ({ path, method, body }) => {
  const auth = localStorage.getItem('Authorization');
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: auth },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}
"""

PROBE_DATASET = "QC 合规检验规范（面包屑探针）"
PROBE_CHAT = "国家及行业规范助手（面包屑探针）"
PROBE_AGENT = "电缆技术规范助手（面包屑探针）"
PROBE_SEARCH = "全局跨库检索（面包屑探针）"
PROBE_MEMORY = "工艺记忆（面包屑探针）"

# The minimum canvas the agent create endpoint accepts, so a probe agent can be
# rendered as a card and as an editor without building one by hand.
PROBE_DSL = {
    "components": {},
    "graph": {"nodes": [], "edges": []},
    "history": [],
    "retrieval": {},
    "globals": {},
}

# The delete endpoint per probe kind. Search apps and agents are deleted one id at
# a time in the path; the other kinds take a body of ids.
DELETE_PATHS = {
    "dataset": "/api/v1/datasets",
    "chat": "/api/v1/chats",
    "agent": "/api/v1/agents",
    "search": "/api/v1/searches",
    "memory": "/api/v1/memories",
}

# Kinds whose delete endpoint carries the id in the path rather than the body.
PATH_DELETE_KINDS = {"search", "agent"}


def delete_probes(page, kind: str, ids) -> str:
    """Delete probe entities, returning the last response for the log."""

    def call(path, body):
        return page.evaluate(MUTATE_JS, {"path": path, "method": "DELETE", "body": body})

    if kind in PATH_DELETE_KINDS:
        responses = [call(f"{DELETE_PATHS[kind]}/{x}", None) for x in ids]
    else:
        responses = [call(DELETE_PATHS[kind], {"ids": list(ids)})]

    return json.dumps(responses[-1], ensure_ascii=False)[:140]


def main() -> int:
    sweep_only = "--sweep-only" in sys.argv
    cleanup = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        page.add_init_script("try {" "  localStorage.setItem('lng', 'zh-Hans');" "  localStorage.setItem('ragflow-ui-theme', 'light');" "} catch (e) {}")

        page.goto(f"{BASE}/login-next", wait_until="networkidle")
        page.wait_for_timeout(2000)
        page.locator(EMAIL_INPUT).first.fill(EMAIL)
        page.locator(PASSWORD_INPUT).first.fill(PASSWORD)
        page.locator("[data-testid='auth-submit']").first.click(force=True)
        page.wait_for_timeout(5000)
        if "/login" in page.url:
            print("could not sign in; aborting")
            browser.close()
            return 1

        try:
            if sweep_only:
                print("sweep-only: no probe entities created")
                raise SystemExit(0)

            created_dataset = page.evaluate(
                MUTATE_JS,
                {
                    "path": "/api/v1/datasets",
                    "method": "POST",
                    "body": {"name": PROBE_DATASET},
                },
            )
            created_chat = page.evaluate(
                MUTATE_JS,
                {
                    "path": "/api/v1/chats",
                    "method": "POST",
                    "body": {"name": PROBE_CHAT},
                },
            )
            dataset_id = (created_dataset.get("data") or {}).get("id")
            chat_id = (created_chat.get("data") or {}).get("id")
            if dataset_id:
                cleanup.append(("dataset", dataset_id))
            if chat_id:
                cleanup.append(("chat", chat_id))
            print("probe ids:", {"dataset": dataset_id, "chat": chat_id})

            routes = list(STATIC_ROUTES)
            if dataset_id:
                # `/dataset/testing` is the idea, `/dataset/retrieval` the route.
                routes += [
                    f"/dataset/files/{dataset_id}",
                    f"/dataset/retrieval/{dataset_id}",
                    f"/dataset/logs/{dataset_id}",
                    f"/dataset/configuration/{dataset_id}",
                    f"/dataset/compilation/{dataset_id}",
                ]
            if chat_id:
                routes.append(f"/chat/{chat_id}")

            # Entities the tenant may already have, plus what each sub-module's list
            # endpoint says exists, so the shell can be checked without seeding.
            for label, api, suffix, create in (
                (
                    "agent",
                    "/api/v1/agents?page=1&page_size=1",
                    lambda row: f"/agent/{row.get('id')}",
                    ("/api/v1/agents", {"title": PROBE_AGENT, "dsl": PROBE_DSL}),
                ),
                (
                    "search",
                    "/api/v1/searches?page=1&page_size=1",
                    lambda row: f"/search/{row.get('id')}",
                    ("/api/v1/searches", {"name": PROBE_SEARCH}),
                ),
                (
                    "memory",
                    "/api/v1/memories?page=1&page_size=1",
                    lambda row: f"/memory/memory-message/{row.get('id')}",
                    (
                        "/api/v1/memories",
                        {"name": PROBE_MEMORY, "memory_type": ["raw"]},
                    ),
                ),
            ):
                payload = page.evaluate(API_JS, api)
                data = payload.get("data")
                if isinstance(data, dict):
                    data = data.get("items") or data.get("data")
                rows = data if isinstance(data, list) else []

                entity_id = rows[0].get("id") if rows else None
                if not entity_id:
                    created = page.evaluate(
                        MUTATE_JS,
                        {
                            "path": create[0],
                            "method": "POST",
                            "body": create[1],
                        },
                    )
                    print(
                        f"{label} create:",
                        json.dumps(created, ensure_ascii=False)[:160],
                    )
                    created_data = created.get("data")
                    if isinstance(created_data, dict):
                        # Some create endpoints answer with `<kind>_id`.
                        entity_id = created_data.get("id") or created_data.get(f"{label}_id")
                    if entity_id:
                        cleanup.append((label, entity_id))

                print(f"{label} entity:", entity_id)
                if entity_id:
                    routes.append(suffix({"id": entity_id}))
                else:
                    # No entity to open: the shell still has to render, and the
                    # missing name has to fall back rather than blank the rail.
                    routes.append(suffix({"id": "probe-missing-entity"}))

            for route in routes:
                page.goto(f"{BASE}{route}", wait_until="networkidle")
                page.wait_for_timeout(2500)
                print(f"\n=== {route} ===")
                print(json.dumps(page.evaluate(TRAIL_JS), ensure_ascii=False))
                if route.startswith(("/user-setting", "/agents", "/agent/")):
                    print("identity:", json.dumps(page.evaluate(IDENTITY_JS), ensure_ascii=False))

                # The rail's own three states, plus the parent's pointer colour.
                if route.startswith("/dataset/files/"):
                    print("styles:", json.dumps(page.evaluate(STYLE_JS), ensure_ascii=False))
                    parent = page.locator("nav[aria-label='breadcrumb'] a").first
                    before = page.evaluate(HOVER_JS)
                    parent.hover()
                    page.wait_for_timeout(400)
                    print(
                        "parent hover:",
                        json.dumps(
                            {"idle": before, "hovered": page.evaluate(HOVER_JS)},
                            ensure_ascii=False,
                        ),
                    )
            # The rail's own navigation: switching a tab has to move the second
            # crumb without a reload, so the click is exercised rather than only
            # the resulting URL.
            page.goto(f"{BASE}/user-setting/model", wait_until="networkidle")
            page.wait_for_timeout(2500)
            for tab in ("团队", "概要", "模型提供商"):
                page.locator(f"aside nav button:has-text('{tab}')").first.click()
                page.wait_for_timeout(1200)
                trail = page.evaluate(TRAIL_JS)
                print(
                    f"\n=== tab click: {tab} -> {page.url} ===",
                    json.dumps(
                        {"levels": trail["levels"], "present": trail["present"]},
                        ensure_ascii=False,
                    ),
                )

        finally:
            # A detail page can navigate on its own (an agent whose canvas is gone
            # redirects), which destroys the JS context a `fetch` would run in. Park
            # on a stable list page before touching the API.
            try:
                page.goto(f"{BASE}/datasets", wait_until="networkidle")
                page.wait_for_timeout(1500)
            except Exception as exc:  # noqa: BLE001 - a probe, not a test
                print("could not park before cleanup:", type(exc).__name__)

            for kind, entity_id in cleanup:
                try:
                    print(f"deleted {kind}:", delete_probes(page, kind, [entity_id]))
                except Exception as exc:  # noqa: BLE001
                    print(f"delete {kind} failed:", type(exc).__name__)

            # A probe left behind by an earlier run is swept up by name, so the
            # tenant is never left holding one.
            for kind, list_api, name_key in (
                ("dataset", "/api/v1/datasets?page=1&page_size=50", "name"),
                ("chat", "/api/v1/chats?page=1&page_size=50", "name"),
                ("search", "/api/v1/searches?page=1&page_size=50", "name"),
                ("agent", "/api/v1/agents?page=1&page_size=50", "title"),
                ("memory", "/api/v1/memories?page=1&page_size=50", "name"),
            ):
                payload = page.evaluate(API_JS, list_api)
                data = payload.get("data")
                if isinstance(data, dict):
                    data = data.get("chats") or data.get("kbs") or data.get("search_apps") or data.get("canvas") or data.get("memory_list") or data.get("items")
                stale = [row["id"] for row in (data if isinstance(data, list) else []) if isinstance(row, dict) and "探针" in str(row.get(name_key) or "")]
                if stale:
                    try:
                        print(f"swept stale {kind}:", delete_probes(page, kind, stale))
                    except Exception as exc:  # noqa: BLE001
                        print(f"sweep {kind} failed:", type(exc).__name__)

            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
