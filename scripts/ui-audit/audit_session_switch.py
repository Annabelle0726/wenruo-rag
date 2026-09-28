"""Verify the chat session switch responds on the click, not on the response.

Seeds a throwaway assistant with three named sessions, then delays the session
detail request in the browser so the loading window can be measured:

  1. the clicked row is marked selected and busy in the same beat as the click
  2. the transcript shows its loading screen while the request is held
  3. re-clicking the row that is already open fires no further request
  4. once the response lands, the loading screen is gone and the transcript is back

Prints one line per check. `E2E_BASE_URL` picks the dev server.
"""

import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

BASE = os.getenv("E2E_BASE_URL", "http://localhost:9223")
EMAIL = os.getenv("E2E_ADMIN_EMAIL") or "admin@ragflow.io"
PASSWORD = os.getenv("E2E_ADMIN_PASSWORD") or "admin"

EMAIL_INPUT = "input[data-testid='auth-email'], [data-testid='auth-email'] input"
PASSWORD_INPUT = "input[data-testid='auth-password'], [data-testid='auth-password'] input"

PROBE_CHAT = "会话切换探针（可删）"
PROBE_SESSIONS = ["电力电缆绝缘线芯识别标志", "GB/T 标准解析会话", "质检规则问答"]

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

# What the rail and the transcript look like at one instant.
STATE_JS = """
() => {
  const loading = document.querySelector('[data-testid="chat-messages-loading"]');
  const rows = Array.from(
    document.querySelectorAll('[data-testid="chat-detail-session-item"]'),
  ).map((button) => {
    const li = button.closest('li');
    return {
      name: (button.textContent || '').trim(),
      selected: li?.getAttribute('aria-selected') === 'true',
      busy: li?.getAttribute('aria-busy') === 'true',
      disabled: button.disabled,
      spinner: Boolean(
        li?.querySelector('[data-testid="chat-detail-session-loading"]'),
      ),
    };
  });
  const transcript = document.querySelector('[data-testid="chat-detail"]');
  return {
    skeletonVisible: Boolean(loading),
    rows,
    transcriptText: (transcript?.innerText || '').replace(/\\s+/g, ' ').slice(-90),
  };
}
"""


def report(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}  {detail}")


def main() -> int:
    cleanup = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
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
            # A probe left behind by an interrupted run collides with the name, so
            # the sweep comes first and makes this script re-runnable.
            existing = page.evaluate(
                MUTATE_JS,
                {
                    "path": "/api/v1/chats?page=1&page_size=50",
                    "method": "GET",
                },
            )
            stale = [row["id"] for row in ((existing.get("data") or {}).get("chats") if isinstance(existing.get("data"), dict) else []) or [] if "探针" in str(row.get("name") or "")]
            if stale:
                page.evaluate(
                    MUTATE_JS,
                    {
                        "path": "/api/v1/chats",
                        "method": "DELETE",
                        "body": {"ids": stale},
                    },
                )
                print("swept stale probes:", len(stale))

            chat = page.evaluate(
                MUTATE_JS,
                {"path": "/api/v1/chats", "method": "POST", "body": {"name": PROBE_CHAT}},
            )
            chat_id = (chat.get("data") or {}).get("id")
            if not chat_id:
                print("could not create the probe assistant:", chat)
                return 1
            cleanup.append(("chat", chat_id))

            session_ids = []
            for name in PROBE_SESSIONS:
                created = page.evaluate(
                    MUTATE_JS,
                    {
                        "path": f"/api/v1/chats/{chat_id}/sessions",
                        "method": "POST",
                        "body": {"name": name},
                    },
                )
                session_id = (created.get("data") or {}).get("id")
                if session_id:
                    session_ids.append(session_id)
            print("seeded sessions:", len(session_ids))
            if len(session_ids) < 2:
                print("need two sessions to switch between")
                return 1

            # Hold the session detail request so the loading window is observable.
            requests = []

            def hold(route):
                requests.append(route.request.url)
                page.wait_for_timeout(1500)
                route.continue_()

            page.route(re.compile(r"/api/v1/chats/[^/]+/sessions/[^/]+$"), hold)

            page.goto(f"{BASE}/chat/{chat_id}", wait_until="networkidle")
            page.wait_for_timeout(2500)

            # The page auto-opens the newest session, so the first wait is for that
            # one to settle: the checks below switch between two others.
            page.wait_for_function("() => !document.querySelector('[data-testid=\"chat-messages-loading\"]')")
            print("after entry:", page.evaluate(STATE_JS)["rows"])

            def rows_by_name(state):
                return {row["name"]: row for row in state["rows"]}

            def click_session(name):
                page.locator(
                    "[data-testid='chat-detail-session-item']",
                    has_text=name,
                ).first.click()

            first, second = PROBE_SESSIONS[0], PROBE_SESSIONS[1]

            # --- 1 + 2: the click paints selection and the loading screen at once.
            requests.clear()
            click_session(second)
            page.wait_for_timeout(250)
            during = page.evaluate(STATE_JS)
            row = rows_by_name(during).get(second, {})
            report(
                "highlight + skeleton appear with the click",
                during["skeletonVisible"] and row.get("selected") is True,
                json.dumps(row, ensure_ascii=False),
            )
            report(
                "the loading row reports busy and swaps in a spinner",
                row.get("busy") is True and row.get("spinner") is True,
            )
            report(
                "the loading row refuses a second click",
                row.get("disabled") is True,
            )

            # --- 4: the loading screen clears when the response lands.
            page.wait_for_timeout(2500)
            after = page.evaluate(STATE_JS)
            settled_row = rows_by_name(after).get(second, {})
            report(
                "loading screen clears once the session arrives",
                not after["skeletonVisible"] and settled_row.get("selected") is True and settled_row.get("spinner") is False,
                after["transcriptText"][:50],
            )

            # --- 3: the already-open session is not fetched again.
            requests.clear()
            click_session(second)
            page.wait_for_timeout(1000)
            recomputed = page.evaluate(STATE_JS)
            report(
                "re-clicking the open session fires no request",
                len(requests) == 0 and not recomputed["skeletonVisible"],
                f"requests={len(requests)}",
            )

            # --- A real switch to the first session still loads it, once.
            requests.clear()
            click_session(first)
            page.wait_for_timeout(250)
            switched = page.evaluate(STATE_JS)
            switched_row = rows_by_name(switched).get(first, {})
            report(
                "switching to another session loads it",
                switched["skeletonVisible"] and switched_row.get("selected") is True and len(requests) == 1,
                f"requests={len(requests)}",
            )
            page.wait_for_timeout(2500)
            landed = page.evaluate(STATE_JS)
            landed_row = rows_by_name(landed).get(first, {})
            report(
                "the switched session settles clean",
                not landed["skeletonVisible"] and landed_row.get("selected") is True,
            )
        finally:
            page.unroute_all(behavior="ignoreErrors")
            for kind, entity_id in cleanup:
                page.evaluate(
                    MUTATE_JS,
                    {
                        "path": "/api/v1/chats",
                        "method": "DELETE",
                        "body": {"ids": [entity_id]},
                    },
                )
                print("deleted probe chat:", entity_id)
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
