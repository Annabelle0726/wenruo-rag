"""Render the 国网-skinned pages of the running dev server.

Opens /login-next (light + dark) and, after signing in, the home page, writing one
PNG per shot next to this script. `E2E_BASE_URL` picks the dev server; the account
falls back to the same defaults `render_files_page.py` uses, and a throwaway
account is registered when the sign-in is rejected.
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.getenv("E2E_BASE_URL", "http://localhost:9223")
EMAIL = os.getenv("E2E_ADMIN_EMAIL") or os.getenv("E2E_USER_EMAIL") or "admin@ragflow.io"
PASSWORD = os.getenv("E2E_ADMIN_PASSWORD") or os.getenv("E2E_USER_PASSWORD") or "admin"
OUT_DIR = Path(__file__).parent
VIEWPORT = {"width": 1600, "height": 950}
# The app's own storage key; `vite-ui-theme` is the provider's default and is not
# what this deployment reads.
THEME_KEY = "ragflow-ui-theme"

EMAIL_INPUT = "input[data-testid='auth-email'], [data-testid='auth-email'] input"
PASSWORD_INPUT = "input[data-testid='auth-password'], [data-testid='auth-password'] input"


def new_page(browser, theme: str):
    page = browser.new_page(viewport=VIEWPORT)
    page.add_init_script("try {" "  localStorage.setItem('lng', 'zh-Hans');" f"  localStorage.setItem('{THEME_KEY}', '{theme}');" "} catch (e) {}")
    return page


def shot(page, name: str) -> None:
    page.screenshot(path=str(OUT_DIR / name), full_page=False)
    print("shot:", name)


def fill_login(page, email: str, password: str) -> None:
    page.locator(EMAIL_INPUT).first.fill(email)
    page.locator(PASSWORD_INPUT).first.fill(password)


def sign_in(page) -> bool:
    fill_login(page, EMAIL, PASSWORD)
    page.locator("[data-testid='auth-submit']").first.click(force=True)
    page.wait_for_timeout(5000)
    print("after sign-in:", page.url)
    return "/login" not in page.url


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        # Sign-in page, both themes, plus the register face and the signed-in pages.
        # The register face gets its own page: flipping the card on the page that is
        # about to sign in leaves the wrong face in front of the submit button.
        for theme in ("light", "dark"):
            page = new_page(browser, theme)
            page.goto(f"{BASE}/login-next", wait_until="networkidle")
            page.wait_for_timeout(2500)
            shot(page, f"probe-login-{theme}.png")

            if theme == "light":
                if sign_in(page):
                    page.goto(f"{BASE}/", wait_until="networkidle")
                    page.wait_for_timeout(5000)
                    shot(page, "probe-home-light.png")

                    page.goto(f"{BASE}/datasets", wait_until="networkidle")
                    page.wait_for_timeout(4000)
                    shot(page, "probe-datasets-light.png")

            page.close()

        # Registration is optional on this deployment, so the toggle may not exist.
        register_page = new_page(browser, "light")
        register_page.goto(f"{BASE}/login-next", wait_until="networkidle")
        register_page.wait_for_timeout(2500)
        try:
            register_page.locator("[data-testid='auth-toggle-register']").first.click(force=True, timeout=5000)
            register_page.wait_for_timeout(1600)
            shot(register_page, "probe-register-light.png")
        except Exception as exc:  # noqa: BLE001 - a probe, not a test
            print("register face unavailable:", type(exc).__name__)
        register_page.close()

        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
