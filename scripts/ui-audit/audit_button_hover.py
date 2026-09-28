"""Report which buttons paint an ink background on hover.

Signs in, walks the list pages, and for every button whose class list carries the
ink fill (`bg-text-primary`) prints the computed background at rest and while
hovered — so the Filter button's hover problem, and its blast radius, can be read
as text rather than guessed.
"""

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.getenv("E2E_BASE_URL", "http://localhost:9223")
EMAIL = os.getenv("E2E_ADMIN_EMAIL") or "admin@ragflow.io"
PASSWORD = os.getenv("E2E_ADMIN_PASSWORD") or "admin"

EMAIL_INPUT = "input[data-testid='auth-email'], [data-testid='auth-email'] input"
PASSWORD_INPUT = "input[data-testid='auth-password'], [data-testid='auth-password'] input"

ROUTES = ["/datasets", "/chats", "/memories", "/files", "/agents", "/searches"]

INSPECT_JS = """
() => {
  const buttons = Array.from(document.querySelectorAll('button, a[role="button"]'));
  return buttons
    .map((el, index) => ({
      index,
      cls: (el.className || '').toString(),
      text: (el.textContent || '').trim().slice(0, 24),
      testid: el.getAttribute('data-testid'),
    }))
    .filter((x) => /(^|\\s)bg-text-primary(\\s|$)/.test(x.cls));
}
"""

# The flat hairline controls, which is what the Filter button is built from.
FLAT_JS = """
() => {
  const buttons = Array.from(document.querySelectorAll('button, a[role="button"]'));
  return buttons
    .map((el, index) => ({
      index,
      cls: (el.className || '').toString(),
      text: (el.textContent || '').trim().slice(0, 24),
      testid: el.getAttribute('data-testid'),
    }))
    .filter((x) => /(^|\\s)ceramic-relief(\\s|$)/.test(x.cls));
}
"""


def report(page, label, js, limit=6):
    found = page.evaluate(js)
    print(f"  {label}: {len(found)}")

    for item in found[:limit]:
        handle = page.query_selector_all('button, a[role="button"]')[item["index"]]
        rest = handle.evaluate("el => getComputedStyle(el).backgroundColor")
        handle.hover()
        page.wait_for_timeout(250)
        hovered = handle.evaluate("el => getComputedStyle(el).backgroundColor")
        ink = "hover:bg-text-primary/90" in item["cls"]
        print(f"    {'[ink class present]' if ink else '[no ink class]    '} " f"rest={rest} hover={hovered} text={item['text']!r} testid={item['testid']}")


def main() -> int:
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

        for route in ROUTES:
            page.goto(f"{BASE}{route}", wait_until="networkidle")
            page.wait_for_timeout(3000)
            print(f"\n=== {route} ===")
            report(page, "ink-filled controls", INSPECT_JS)
            report(page, "flat hairline (ceramic-relief) controls", FLAT_JS)

        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
