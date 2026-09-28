"""Check that an entity shows one icon everywhere: card/mark vs detail header.

Two assertions per family:
  1. the icon the list row uses is the icon the detail header uses (same lucide
     name), and
  2. the detail header draws a vector or an image rather than the first character
     of the name.

Seeds a knowledge base, a chat and a search app, and deletes them afterwards.
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

API_JS = """
async ({ path, method, body }) => {
  const auth = localStorage.getItem('Authorization');
  const res = await fetch(path, {
    method: method || 'GET',
    headers: { 'Content-Type': 'application/json', Authorization: auth },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}
"""

# The first mark inside a container: the frame's classes, the lucide name of the
# SVG, and whether an owner image is in use instead.
MARK_JS = """
(selector) => {
  const root = document.querySelector(selector);
  if (!root) return { missing: selector };

  const svg = root.querySelector('svg');
  const img = root.querySelector('img');
  const frame = (svg || img)?.closest('span');

  return {
    lucide: svg
      ? ((svg.getAttribute('class') || '').split(' ').find((c) => c.startsWith('lucide-')) ||
         'svg-without-lucide-class')
      : null,
    img: img ? img.getAttribute('src') : null,
    frame: frame ? (frame.className || '').toString().slice(0, 150) : null,
    // What a text-fallback header would show: a bare initial inside the frame.
    text: frame && !svg && !img ? (frame.textContent || '').trim().slice(0, 8) : null,
  };
}
"""

SEEDS = [
    {
        "label": "dataset",
        "create": ("/api/v1/datasets", {"name": "QC 合规检验规范（图标探针）"}),
        "delete": "/api/v1/datasets",
        "list": "/datasets",
        "row": "table tbody tr",
        "detail": "/dataset/files/{id}",
        # The knowledge base sidebar's header block.
        "header": "aside header",
    },
    {
        "label": "chat",
        "create": ("/api/v1/chats", {"name": "国家及行业规范助手（图标探针）"}),
        "delete": "/api/v1/chats",
        "list": "/chats",
        "row": "article[data-agent-name]",
        "detail": "/chat/{id}",
        "header": "[data-testid='chat-detail-sessions'] header",
        # The same assistant, in the rail the header collapses into.
        "collapse": "[data-testid='chat-detail-sessions-close']",
        "extra": "[data-testid='chat-detail-sessions-open']",
    },
    {
        "label": "agent",
        # The API refuses a create with no canvas in it, so the probe posts the
        # same empty seed the "从空白创建" dialog does.
        "create": (
            "/api/v1/agents",
            {
                "title": "T-Agent（图标探针）",
                "canvas_category": "agent_canvas",
                "dsl": {"graph": {"nodes": [], "edges": []}},
            },
        ),
        "delete": "/api/v1/agents",
        "list": "/agents",
        "row": "[data-testid='agent-card']",
        "detail": "/agent/{id}",
        "header": "[data-testid='agent-detail'] header",
    },
]

# Detail headers whose entity cannot be seeded on this tenant, checked only for
# "no text fallback".
HEADERS_ONLY = [
    {"label": "memory (empty entity)", "url": "/memory/memory-message/no-such-memory"},
]

MEMORY_HEADER = "aside"


def main() -> int:
    created = []
    failures = []

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
            for seed in SEEDS:
                path, body = seed["create"]
                response = page.evaluate(API_JS, {"path": path, "method": "POST", "body": body})
                data = response.get("data")
                entity_id = None
                if isinstance(data, dict):
                    entity_id = data.get("id") or data.get(f"{seed['label']}_id")
                if not entity_id:
                    print(f"\n### {seed['label']}: not seeded — {response}")
                    continue
                created.append((seed["delete"], entity_id))

                page.goto(f"{BASE}{seed['list']}", wait_until="networkidle")
                page.wait_for_timeout(4000)
                row = page.evaluate(MARK_JS, seed["row"])

                page.goto(
                    f"{BASE}{seed['detail'].format(id=entity_id)}",
                    wait_until="networkidle",
                )
                page.wait_for_timeout(4500)
                header = page.evaluate(MARK_JS, seed["header"])

                print(f"\n### {seed['label']} ({entity_id})")
                print("  list row      :", json.dumps(row, ensure_ascii=False))
                print("  detail header :", json.dumps(header, ensure_ascii=False))

                if row.get("lucide") and row["lucide"] == header.get("lucide"):
                    print("  MATCH: same icon")
                elif row.get("img") and row.get("img") == header.get("img"):
                    print("  MATCH: same image")
                else:
                    print("  MISMATCH")
                    failures.append(f"{seed['label']}: icon differs")

                if not (header.get("lucide") or header.get("img")):
                    failures.append(f"{seed['label']}: header has no vector/image")
                    print("  FAIL: header drew no vector or image")

                if seed.get("extra"):
                    # The rail only renders once the conversation list is collapsed.
                    collapse = page.locator(seed["collapse"]).first
                    try:
                        collapse.click(force=True, timeout=5000)
                        page.wait_for_timeout(1500)
                    except Exception as exc:  # noqa: BLE001 - a probe, not a test
                        print("  could not collapse:", type(exc).__name__)
                    rail = page.evaluate(MARK_JS, seed["extra"])
                    print("  collapsed rail:", json.dumps(rail, ensure_ascii=False))
                    if rail.get("text"):
                        failures.append(f"{seed['label']}: rail fell back to text")
                        print("  FAIL: collapsed rail fell back to text")
                    elif rail.get("lucide") == row.get("lucide"):
                        print("  MATCH: rail shows the card's icon")

            for item in HEADERS_ONLY:
                page.goto(f"{BASE}{item['url']}", wait_until="networkidle")
                page.wait_for_timeout(4000)
                header = page.evaluate(MARK_JS, MEMORY_HEADER)
                print(f"\n### {item['label']}")
                print("  header        :", json.dumps(header, ensure_ascii=False))
                if header.get("text"):
                    failures.append(f"{item['label']}: fell back to text")
                    print("  FAIL: text fallback in the header")
                elif header.get("lucide") or header.get("img"):
                    print("  OK: vector/image, no text fallback")
        finally:
            for path, entity_id in created:
                removed = page.evaluate(API_JS, {"path": f"{path}/{entity_id}", "method": "DELETE"})
                if removed.get("code") != 0:
                    removed = page.evaluate(
                        API_JS,
                        {"path": path, "method": "DELETE", "body": {"ids": [entity_id]}},
                    )
                print(
                    f"deleted {entity_id}:",
                    json.dumps(removed, ensure_ascii=False)[:100],
                )
            browser.close()

    print("\n=== RESULT ===")
    print("failures:", failures or "none")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
