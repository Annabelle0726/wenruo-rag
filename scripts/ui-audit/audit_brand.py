"""Verify the brand swap on the rendered pages.

Signs in and reports, per route, every brand image with its natural size (proving
the asset resolved rather than 404'd), its rendered box (proving it is not
squashed), the product name text, and the document title / favicon.
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

BRAND_JS = """
() => {
  const imgs = Array.from(document.querySelectorAll('img')).filter((el) =>
    /brand-(mark|lockup|poster)/.test(el.getAttribute('src') || ''),
  );
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return `${Math.round(r.width)}x${Math.round(r.height)}`;
  };
  return {
    title: document.title,
    favicon: document.querySelector('link[rel="icon"]')?.getAttribute('href'),
    brandText: Array.from(document.querySelectorAll('span, p, h1'))
      .map((el) => (el.textContent || '').trim())
      .filter((x) => x === '文若RAG' || x === 'Wenruo RAG')
      .slice(0, 4),
    logos: imgs.map((el) => ({
      src: (el.getAttribute('src') || '').split('/').pop(),
      natural: `${el.naturalWidth}x${el.naturalHeight}`,
      rendered: box(el),
      loaded: el.complete && el.naturalWidth > 0,
      alt: el.getAttribute('alt'),
    })),
  };
}
"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        page.add_init_script("try {" "  localStorage.setItem('lng', 'zh-Hans');" "  localStorage.setItem('ragflow-ui-theme', 'light');" "} catch (e) {}")

        page.goto(f"{BASE}/login-next", wait_until="networkidle")
        page.wait_for_timeout(2500)
        print("=== /login-next (signed out) ===")
        print(json.dumps(page.evaluate(BRAND_JS), indent=2, ensure_ascii=False))

        page.locator(EMAIL_INPUT).first.fill(EMAIL)
        page.locator(PASSWORD_INPUT).first.fill(PASSWORD)
        page.locator("[data-testid='auth-submit']").first.click(force=True)
        page.wait_for_timeout(5000)
        print("signed in ->", page.url)

        for route in ("/", "/searches"):
            page.goto(f"{BASE}{route}", wait_until="networkidle")
            page.wait_for_timeout(3000)
            print(f"\n=== {route} ===")
            print(json.dumps(page.evaluate(BRAND_JS), indent=2, ensure_ascii=False))

        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
