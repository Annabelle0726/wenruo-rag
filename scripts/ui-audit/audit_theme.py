"""Audit the rendered 国网 skin in a real browser.

Walks the running dev server and prints the computed styles the skin is supposed
to guarantee — header ink, table metrics, radii, gradients, shadows, footer
placement — so the result can be read as text instead of a screenshot.

`E2E_BASE_URL` picks the dev server. Authenticated routes are only audited when a
session can be established.
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

# Reports, per audited page: the delivered hit list for each skin rule.
AUDIT_JS = """
() => {
  const cs = (el, prop) => el ? getComputedStyle(el).getPropertyValue(prop) : null;
  const pick = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return { selector: sel, missing: true };
    const out = { selector: sel };
    props.forEach((p) => { out[p] = cs(el, p); });
    return out;
  };

  // Any element still painting a gradient or a drop shadow.
  const all = Array.from(document.querySelectorAll('body *'));
  const gradients = all
    .filter((el) => {
      const bg = cs(el, 'background-image') || '';
      return bg.includes('gradient');
    })
    .slice(0, 8)
    .map((el) => el.tagName.toLowerCase() + '.' + (el.className || '').toString().slice(0, 70));
  const shadows = all
    .filter((el) => {
      const s = cs(el, 'box-shadow') || '';
      return s && s !== 'none';
    })
    .slice(0, 8)
    .map((el) => el.tagName.toLowerCase() + '.' + (el.className || '').toString().slice(0, 70));

  // Radii above the 2px ceiling. Rings, avatars and spinners are legitimately
  // round, so they are called out separately rather than hidden.
  const round = all
    .filter((el) => parseFloat(cs(el, 'border-top-left-radius') || '0') > 2)
    .map((el) => {
      const r = cs(el, 'border-top-left-radius');
      const cls = (el.className || '').toString();
      return { r, round: parseFloat(r) >= 40, el: el.tagName.toLowerCase() + '.' + cls.slice(0, 60) };
    });
  const roundNonCircle = round.filter((x) => !x.round).slice(0, 8);
  const roundCircles = round.filter((x) => x.round).slice(0, 6);

  return {
    url: location.pathname,
    body: pick('body', ['background-color', 'font-family', 'font-size']),
    header: pick('header', ['background-color', 'height']),
    headerBar: pick('.glass-header', ['background-color', 'border-bottom-color']),
    navIdle: pick('header nav a:not([aria-current])', ['color']),
    navActive: pick('header nav a[aria-current="page"]', ['color', 'background-color', 'font-weight', 'box-shadow']),
    breadcrumb: pick('nav[aria-label="breadcrumb"]', ['height', 'background-color', 'border-bottom-color', 'font-size', 'color']),
    footer: pick('footer', ['position', 'background-color', 'border-top-color', 'font-size', 'color']),
    footerText: (document.querySelector('footer p') || {}).textContent || null,
    panel: pick('[data-testid="dataset-query-panel"]', ['background-color', 'border-top-color', 'border-top-width']),
    select: pick('[data-testid="dataset-query-category"]', ['height', 'border-radius', 'border-top-color']),
    keyword: pick('[data-testid="dataset-query-keyword"]', ['height', 'border-radius', 'border-top-color']),
    tableHead: pick('table thead th', ['background-color', 'color', 'font-weight', 'height', 'border-bottom-color']),
    tableRow: pick('table tbody tr', ['height', 'border-bottom-color']),
    statusBadge: pick('[data-testid="dataset-status"]', ['background-color', 'color', 'border-top-color', 'border-radius']),
    segmentedIdle: pick('[data-testid^="ceramic-segment-"]:not([aria-pressed="true"])', ['color']),
    segmentedActive: pick('[data-testid^="ceramic-segment-"][aria-pressed="true"]', ['color', 'font-weight']),
    gradients,
    shadows,
    roundNonCircle,
    roundCircles,
  };
}
"""


def audit(page, name):
    data = page.evaluate(AUDIT_JS)
    print(f"\n===== {name} ({data.pop('url')}) =====")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def try_sign_in(page) -> bool:
    page.locator(EMAIL_INPUT).first.fill(EMAIL)
    page.locator(PASSWORD_INPUT).first.fill(PASSWORD)
    page.locator("[data-testid='auth-submit']").first.click(force=True)
    page.wait_for_timeout(5000)
    ok = "/login" not in page.url
    print("signed in:", ok, "->", page.url)
    return ok


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        page.add_init_script("try {" "  localStorage.setItem('lng', 'zh-Hans');" "  localStorage.setItem('ragflow-ui-theme', 'light');" "} catch (e) {}")

        page.goto(f"{BASE}/login-next", wait_until="networkidle")
        page.wait_for_timeout(2500)
        audit(page, "login (light)")

        signed_id = try_sign_in(page)
        if signed_id:
            page.goto(f"{BASE}/", wait_until="networkidle")
            page.wait_for_timeout(5000)
            audit(page, "home (light)")
            page.goto(f"{BASE}/datasets", wait_until="networkidle")
            page.wait_for_timeout(4000)
            audit(page, "datasets (light)")
        else:
            print("\nno credentials: skipped the authenticated routes")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
