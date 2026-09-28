"""Audit the dataset data table with a real row.

Signs in, creates a throwaway knowledge base through the API, then reports the
computed metrics of that row — height, row rule, class tag, file count, status
badge, action links — before deleting it again.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.getenv("E2E_BASE_URL", "http://localhost:9223")
EMAIL = os.getenv("E2E_ADMIN_EMAIL") or "admin@ragflow.io"
PASSWORD = os.getenv("E2E_ADMIN_PASSWORD") or "admin"
PROBE_NAME = "QC 合规检验规范（探针，可删）"

EMAIL_INPUT = "input[data-testid='auth-email'], [data-testid='auth-email'] input"
PASSWORD_INPUT = "input[data-testid='auth-password'], [data-testid='auth-password'] input"

CREATE_JS = """
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

DELETE_JS = """
async (ids) => {
  const auth = localStorage.getItem('Authorization');
  const res = await fetch('/api/v1/datasets', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', Authorization: auth },
    body: JSON.stringify({ ids }),
  });
  return res.json();
}
"""

ROW_JS = """
() => {
  const cs = (el, prop) => el ? getComputedStyle(el).getPropertyValue(prop) : null;
  const pick = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return { selector: sel, missing: true };
    const out = { selector: sel, text: (el.textContent || '').trim().slice(0, 40) };
    props.forEach((p) => { out[p] = cs(el, p); });
    return out;
  };

  return {
    rowCount: document.querySelectorAll('tbody tr').length,
    row: pick('tbody tr', ['height', 'border-bottom-width', 'border-bottom-color', 'background-color']),
    classTag: pick('[data-testid="dataset-row"] span', ['border-radius', 'border-top-width', 'border-top-color', 'color', 'font-size']),
    name: pick('[data-testid="dataset-name"]', ['color', 'font-size']),
    status: pick('[data-testid="dataset-status"]', ['background-color', 'color', 'border-top-color', 'border-radius', 'font-size']),
    details: pick('[data-testid="dataset-view-details"]', ['color', 'font-size']),
  };
}
"""


def main() -> int:
    dataset_id = None
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
            created = page.evaluate(CREATE_JS, PROBE_NAME)
            print("created:", json.dumps(created, ensure_ascii=False)[:200])
            dataset_id = (created.get("data") or {}).get("id")
            if not dataset_id:
                print("create failed; nothing to audit")
                return 1

            for route, label in (("/", "home"), ("/datasets", "datasets")):
                page.goto(f"{BASE}{route}", wait_until="networkidle")
                page.wait_for_timeout(5000)
                print(f"\n===== table row on {label} =====")
                print(json.dumps(page.evaluate(ROW_JS), indent=2, ensure_ascii=False))
        finally:
            if dataset_id:
                removed = page.evaluate(DELETE_JS, [dataset_id])
                print("\nprobe deleted:", json.dumps(removed, ensure_ascii=False)[:160])
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
