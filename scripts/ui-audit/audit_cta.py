"""Measure every list-toolbar CTA: height, radius, font and the rail it shares.

Signs in, walks each list page, and reports the primary create/new CTA's computed
box next to the search field's, so "the CTA is 32px on the same rail as the field"
can be read as text. Seeds one knowledge base to reach its documents toolbar.
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

CREATE_DATASET_JS = """
async (name) => {
  const auth = localStorage.getItem('Authorization');
  const res = await fetch('/api/v1/datasets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: auth },
    body: JSON.stringify({ name }),
  });
  return res.json();
}
"""

DELETE_DATASET_JS = """
async (id) => {
  const auth = localStorage.getItem('Authorization');
  const res = await fetch('/api/v1/datasets/' + id, {
    method: 'DELETE',
    headers: { Authorization: auth },
  });
  return res.json();
}
"""

BOX_JS = """
(el) => {
  const cs = (prop) => getComputedStyle(el).getPropertyValue(prop);
  return {
    h: Math.round(el.getBoundingClientRect().height),
    radius: cs('border-top-left-radius'),
    fontSize: cs('font-size'),
    fontWeight: cs('font-weight'),
    padding: cs('padding-left') + ' / ' + cs('padding-right'),
    gap: cs('gap'),
    background: cs('background-color'),
  };
}
"""

# (label, route, CTA locator, search-field locator)
PAGES = [
    ("datasets", "/datasets", "button:has-text('创建知识库')", None),
    ("files", "/files", "button:has-text('新增文件')", "input[role='searchbox']"),
    ("chats", "/chats", "[data-testid='create-chat']", "input[role='searchbox']"),
    ("agents", "/agents", "[data-testid='create-agent']", "input[role='searchbox']"),
    ("searches", "/searches", "[data-testid='create-search']", None),
    ("memories", "/memories", "button:has-text('创建')", None),
    ("skills", "/files/skills", "button:has-text('创建 Skills 空间')", None),
    ("team", "/user-setting/team", "button:has-text('邀请')", "input[role='searchbox']"),
]


def measure(page, label, route, cta, field) -> list:
    problems = []
    page.goto(f"{BASE}{route}", wait_until="domcontentloaded")
    page.wait_for_timeout(4500)

    locator = page.locator(cta).first
    print(f"\n=== {label} ({route})")
    if locator.count() == 0:
        print(f"  CTA NOT FOUND: {cta}")
        return [f"{label}: CTA not found"]

    cta_box = locator.evaluate(BOX_JS)
    print("  cta  :", json.dumps(cta_box, ensure_ascii=False))

    if cta_box["h"] != 32:
        problems.append(f"{label}: height {cta_box['h']} != 32")
    if cta_box["radius"] != "2px":
        problems.append(f"{label}: radius {cta_box['radius']} != 2px")

    if field:
        field_locator = page.locator(field).first
        if field_locator.count():
            field_box = field_locator.evaluate(BOX_JS)
            print("  field:", json.dumps(field_box, ensure_ascii=False))
            if field_box["h"] != cta_box["h"]:
                problems.append(f"{label}: CTA {cta_box['h']}px beside a {field_box['h']}px field")
        else:
            print(f"  no field for {field}")

    return problems


def main() -> int:
    problems = []
    dataset_id = None

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        page.add_init_script("try {" "  localStorage.setItem('lng', 'zh-Hans');" "  localStorage.setItem('ragflow-ui-theme', 'light');" "} catch (e) {}")

        page.goto(f"{BASE}/login-next", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        page.locator(EMAIL_INPUT).first.fill(EMAIL)
        page.locator(PASSWORD_INPUT).first.fill(PASSWORD)
        page.locator("[data-testid='auth-submit']").first.click(force=True)
        page.wait_for_timeout(5000)
        if "/login" in page.url:
            print("could not sign in; aborting")
            browser.close()
            return 1

        try:
            created = page.evaluate(CREATE_DATASET_JS, "CTA 探针（可删）")
            dataset_id = (created.get("data") or {}).get("id")

            for label, route, cta, field in PAGES:
                problems += measure(page, label, route, cta, field)

            # The knowledge base's own documents toolbar: the same "add file" CTA
            # the file manager has, on a page that needs an entity to exist.
            if dataset_id:
                problems += measure(
                    page,
                    "kb documents",
                    f"/dataset/files/{dataset_id}",
                    "button:has-text('新增文件')",
                    "input[role='searchbox']",
                )
            else:
                print("\nkb documents: skipped (no probe knowledge base)")
        finally:
            if dataset_id:
                removed = page.evaluate(DELETE_DATASET_JS, dataset_id)
                print(
                    "\ndeleted probe:",
                    json.dumps(removed, ensure_ascii=False)[:100],
                )
            browser.close()

    print("\n=== RESULT ===")
    print("problems:", problems or "none")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
