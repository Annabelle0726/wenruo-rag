"""Reproduce a session row that never leaves its loading state.

Seeds an assistant with two sessions, then makes the session-detail request fail in
two ways the app has to survive — a rejected request and a response that arrives
after the route's query string changed mid-flight — and reports whether the row
hands its actions back and the transcript stops showing its loading screen.

  python audit_stuck_session.py
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

PROBE_CHAT = "会话卡死探针（可删）"
PROBE_SESSIONS = ["热稳定性试验追溯", "PVC/E 绝缘规范"]

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

STATE_JS = """
() => {
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
        li?.querySelector('[data-testid="chat-detail-session-loading"]')
      ),
    };
  });
  return {
    skeleton: Boolean(
      document.querySelector('[data-testid="chat-messages-loading"]')
    ),
    rows,
  };
}
"""


def report(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}  {detail}")


def main() -> int:
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

        chat_id = None
        try:
            existing = page.evaluate(
                MUTATE_JS,
                {"path": "/api/v1/chats?page=1&page_size=50", "method": "GET"},
            )
            data = existing.get("data")
            rows = data.get("chats") if isinstance(data, dict) else []
            stale = [r["id"] for r in (rows or []) if "探针" in str(r.get("name") or "")]
            if stale:
                page.evaluate(
                    MUTATE_JS,
                    {"path": "/api/v1/chats", "method": "DELETE", "body": {"ids": stale}},
                )

            chat = page.evaluate(
                MUTATE_JS,
                {"path": "/api/v1/chats", "method": "POST", "body": {"name": PROBE_CHAT}},
            )
            chat_id = (chat.get("data") or {}).get("id")
            if not chat_id:
                print("could not create the probe assistant:", chat)
                return 1

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

            session_pattern = re.compile(r"/api/v1/chats/[^/]+/sessions/[^/]+$")

            # Every session-detail request the page makes, so a retry is asserted by
            # the request it fires rather than by catching a transient spinner.
            attempted = []
            page.on(
                "request",
                lambda r: attempted.append(r.url) if session_pattern.search(r.url) else None,
            )

            def by_name(state):
                return {row["name"]: row for row in state["rows"]}

            # --- A rejected session request must not strand the row.
            def abort_route(route):
                route.abort("failed")

            page.route(session_pattern, abort_route)
            page.goto(f"{BASE}/chat/{chat_id}", wait_until="networkidle")
            page.wait_for_timeout(4000)
            state = page.evaluate(STATE_JS)
            print("after a failed request:", json.dumps(state, ensure_ascii=False))
            row = state["rows"][0] if state["rows"] else {}
            report(
                "a failed fetch releases the transcript loading screen",
                not state["skeleton"],
            )
            report(
                "a failed fetch hands the row its actions back",
                not row.get("spinner") and not row.get("disabled") and not row.get("busy"),
                json.dumps(row, ensure_ascii=False),
            )

            # --- Clicking the failed row again retries it, and this time it loads.
            page.unroute_all(behavior="ignoreErrors")
            target = PROBE_SESSIONS[1]
            before_retry = len(attempted)
            page.locator("[data-testid='chat-detail-session-item']", has_text=target).first.click()
            page.wait_for_timeout(2000)
            report(
                "clicking the failed row fires exactly one more attempt",
                len(attempted) == before_retry + 1,
                f"{before_retry} -> {len(attempted)}",
            )
            healed = page.evaluate(STATE_JS)
            healed_row = by_name(healed).get(target, {})
            report(
                "the retry settles and clears the loading state",
                not healed["skeleton"] and healed_row.get("spinner") is False and healed_row.get("disabled") is False,
                json.dumps(healed_row, ensure_ascii=False),
            )

            # --- A response that lands after the query string moved is not dropped.
            def slow_then_continue(route):
                page.wait_for_timeout(2500)
                route.continue_()

            page.route(session_pattern, slow_then_continue)
            page.goto(f"{BASE}/chat/{chat_id}", wait_until="networkidle")
            page.wait_for_timeout(400)
            # Move the query string while the fetch is in flight, the way the send
            # flow does when it flips `isNew`.
            page.locator("[data-testid='chat-detail-session-item']", has_text=target).first.click()
            page.wait_for_timeout(400)
            page.evaluate("() => { const u = new URL(location.href); u.searchParams.set('isNew', ''); " "history.replaceState(null, '', u); window.dispatchEvent(new PopStateEvent('popstate')); }")
            page.wait_for_timeout(5000)
            landed = page.evaluate(STATE_JS)
            print("after a mid-flight param change:", json.dumps(landed, ensure_ascii=False))
            landed_row = by_name(landed).get(target, {})
            report(
                "a response that outlives a param change still clears the row",
                not landed["skeleton"] and not landed_row.get("spinner") and landed_row.get("selected") is True,
                json.dumps(landed_row, ensure_ascii=False),
            )
        finally:
            page.unroute_all(behavior="ignoreErrors")
            if chat_id:
                page.evaluate(
                    MUTATE_JS,
                    {"path": "/api/v1/chats", "method": "DELETE", "body": {"ids": [chat_id]}},
                )
                print("deleted probe chat:", chat_id)
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
