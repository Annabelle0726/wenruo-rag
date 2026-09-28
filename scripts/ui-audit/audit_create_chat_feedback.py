"""Watch what the create-chat flow shows while it works.

Clicks 创建聊天 on /chats, names the assistant, submits, then samples the dialog and
the list every 100ms so the answer is the sequence of what was on screen — whether a
busy state appeared on the button, when the dialog closed, when the card showed up.

  python audit_create_chat_feedback.py
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.getenv("E2E_BASE_URL", "http://localhost:9223")
EMAIL = os.getenv("E2E_ADMIN_EMAIL") or "admin@ragflow.io"
PASSWORD = os.getenv("E2E_ADMIN_PASSWORD") or "admin"
PROBE_NAME = "创建反馈探针（可删）"

EMAIL_INPUT = "input[data-testid='auth-email'], [data-testid='auth-email'] input"
PASSWORD_INPUT = "input[data-testid='auth-password'], [data-testid='auth-password'] input"

SAMPLE_JS = """
() => {
  const save = document.querySelector("[data-testid='rename-save']");
  const dialog = document.querySelector("[data-testid='rename-modal']");
  const cards = Array.from(document.querySelectorAll('[data-agent-name]')).map(
    (el) => el.getAttribute('data-agent-name')
  );
  return {
    dialogOpen: Boolean(dialog),
    saveDisabled: save ? save.disabled : null,
    saveSpinning: save ? Boolean(save.querySelector('.animate-spin')) : null,
    cards: cards.length,
    probeCardPresent: cards.includes('创建反馈探针（可删）'),
  };
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


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})

        requests = []
        page.on(
            "request",
            lambda r: requests.append(f"{r.method} {r.url.split('/api/v1')[-1]}") if "/api/v1/chats" in r.url and r.method in ("POST", "DELETE") else None,
        )

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

        # Sweep a probe left by an interrupted run, so the name is free.
        listed = page.evaluate(MUTATE_JS, {"path": "/api/v1/chats?page=1&page_size=50", "method": "GET"})
        data = listed.get("data")
        rows = data.get("chats") if isinstance(data, dict) else []
        stale = [r["id"] for r in (rows or []) if "探针" in str(r.get("name") or "")]
        if stale:
            page.evaluate(
                MUTATE_JS,
                {"path": "/api/v1/chats", "method": "DELETE", "body": {"ids": stale}},
            )

        page.goto(f"{BASE}/chats", wait_until="networkidle")
        page.wait_for_timeout(3000)
        print("before:", json.dumps(page.evaluate(SAMPLE_JS), ensure_ascii=False))

        requests.clear()
        page.locator("[data-testid='create-chat']").first.click()
        page.wait_for_timeout(600)
        print("\nafter clicking 创建聊天:", json.dumps(page.evaluate(SAMPLE_JS), ensure_ascii=False))

        page.locator("[data-testid='rename-name-input']").first.fill(PROBE_NAME)

        # Anything covering the save button is the bug worth naming: a modal overlay
        # left open on top of the dialog swallows the click, which reads as a button
        # that does nothing.
        blocking = page.evaluate(
            """
            () => {
              const save = document.querySelector("[data-testid='rename-save']");
              if (!save) return null;
              const box = save.getBoundingClientRect();
              const top = document.elementFromPoint(
                box.left + box.width / 2,
                box.top + box.height / 2
              );
              if (!top || top === save || save.contains(top)) return null;
              const blocker = top.closest('[data-state="open"]') || top;
              return {
                tag: top.tagName.toLowerCase(),
                cls: (top.className || '').toString().slice(0, 120),
                blockerText: (blocker.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
                blockerCls: (blocker.className || '').toString().slice(0, 120),
              };
            }
            """
        )
        print("\ncovering the save button:", json.dumps(blocking, ensure_ascii=False))

        page.locator("[data-testid='rename-save']").first.click(force=True)

        # Sample the feedback while the create is in flight.
        samples = []
        for _ in range(40):
            page.wait_for_timeout(100)
            samples.append(page.evaluate(SAMPLE_JS))

        first_busy = next((i for i, s in enumerate(samples) if s["saveSpinning"]), None)
        dialog_closed = next((i for i, s in enumerate(samples) if not s["dialogOpen"]), None)
        card_seen = next((i for i, s in enumerate(samples) if s["probeCardPresent"]), None)

        print("\nsamples (index = 100ms ticks):")
        for i in (0, 1, 2, 5, 10, 20, 30, 39):
            print(f"  t+{(i + 1) * 100}ms", json.dumps(samples[i], ensure_ascii=False))

        print("\nverdict:")
        print("  spinner on save button first seen at tick:", first_busy)
        print("  dialog closed at tick:", dialog_closed)
        print("  new card visible at tick:", card_seen)
        print("  create requests:", requests)

        if first_busy is None and dialog_closed is not None and dialog_closed <= 2:
            print("\n=> the create was fast enough that no busy state was ever painted")
        elif first_busy is None:
            print("\n=> NO busy state was shown at any point while creating")

        # Clean up.
        listed = page.evaluate(MUTATE_JS, {"path": "/api/v1/chats?page=1&page_size=50", "method": "GET"})
        data = listed.get("data")
        rows = data.get("chats") if isinstance(data, dict) else []
        mine = [r["id"] for r in (rows or []) if r.get("name") == PROBE_NAME]
        if mine:
            page.evaluate(
                MUTATE_JS,
                {"path": "/api/v1/chats", "method": "DELETE", "body": {"ids": mine}},
            )
            print("deleted probe assistant:", mine)

        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
