"""Render the file-management page of the running dev server.

Signs in with the configured account; when that fails it registers a throwaway
one (registration is enabled on this deployment), then opens /files and writes a
screenshot next to this script. `SHOT_NAME` and `SHOT_THEME` pick the file name
and the colour mode to render.
"""

import os
import sys
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.getenv("E2E_BASE_URL", "http://localhost:9223")
EMAIL = os.getenv("E2E_ADMIN_EMAIL") or os.getenv("E2E_USER_EMAIL") or "qa@infiniflow.org"
PASSWORD = os.getenv("E2E_ADMIN_PASSWORD") or os.getenv("E2E_USER_PASSWORD") or "123"
THEME = os.getenv("SHOT_THEME", "dark")
OUT = Path(__file__).with_name(os.getenv("SHOT_NAME", f"files-page-{THEME}.png"))

EMAIL_INPUT = "input[data-testid='auth-email'], [data-testid='auth-email'] input"
PASSWORD_INPUT = "input[data-testid='auth-password'], [data-testid='auth-password'] input"


def fill_login(page, email: str, password: str) -> None:
    page.locator(EMAIL_INPUT).first.fill(email)
    page.locator(PASSWORD_INPUT).first.fill(password)


def register(page) -> str:
    email = f"qa_{uuid.uuid4().hex[:8]}@infiniflow.org"
    # The login card flips, and the inactive face keeps intercepting pointer
    # events in headless Chrome, so these clicks are forced.
    page.locator("[data-testid='auth-toggle-register']").first.click(force=True)
    page.wait_for_timeout(800)
    page.locator("[data-testid='auth-nickname']").first.fill("qa")
    fill_login(page, email, PASSWORD)
    page.locator("[data-testid='auth-submit']").first.click(force=True)
    page.wait_for_timeout(4000)
    return email


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script("try { localStorage.setItem('lng', 'zh-Hans'); } catch (e) {}")

        page.goto(BASE, wait_until="networkidle")
        print("landed on:", page.url)

        if "/login" in page.url:
            fill_login(page, EMAIL, PASSWORD)
            page.locator("[data-testid='auth-submit']").first.click(force=True)
            page.wait_for_timeout(4000)
            print("after sign-in:", page.url)
            if "/login" in page.url:
                print("sign-in rejected, registering a throwaway account")
                print("registered:", register(page), "->", page.url)

        page.goto(f"{BASE}/files", wait_until="networkidle")
        page.wait_for_timeout(4000)
        print("files page:", page.url)
        print("theme rendered:", THEME)
        page.screenshot(path=str(OUT), full_page=False)
        browser.close()

    print("screenshot:", OUT, OUT.exists())
    return 0 if OUT.exists() else 1


if __name__ == "__main__":
    sys.exit(main())
