"""Does a conversation actually get titled while the session list is open?

Seeds an assistant (whose prologue gives the new session an assistant message, which
is the gate the titler waits on) and a session named after a question, opens it with
the sessions rail visible — the default — and reports whether the page asks the
backend to title it.

  python audit_title_trigger.py            # against the dev server
  E2E_BASE_URL=http://localhost python audit_title_trigger.py   # against the container
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

# The titler waits for the first question AND an answer, so the probe session needs
# both. A completion would produce them, but that needs a working model; writing the
# same two rows through the app's own DAO is the fixture without the LLM call.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.db.services.conversation_service import ConversationService  # noqa: E402

BASE = os.getenv("E2E_BASE_URL", "http://localhost:9223")
EMAIL = os.getenv("E2E_ADMIN_EMAIL") or "admin@ragflow.io"
PASSWORD = os.getenv("E2E_ADMIN_PASSWORD") or "admin"

PROBE_CHAT = "标题触发探针（可删）"
QUESTION = "电缆缆芯的绞合节距和最外层绞向有什么具体要求"

EMAIL_INPUT = "input[data-testid='auth-email'], [data-testid='auth-email'] input"
PASSWORD_INPUT = "input[data-testid='auth-password'], [data-testid='auth-password'] input"

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
    titles = []
    responses = []
    chat_id = None

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.add_init_script("try {" "  localStorage.setItem('lng', 'zh-Hans');" "  localStorage.setItem('ragflow-ui-theme', 'light');" "} catch (e) {}")

        def on_request(request):
            if request.url.endswith("/api/v1/chat/title") and request.method == "POST":
                titles.append(request.post_data or "")

        page.on("request", on_request)

        def on_response(response):
            if response.url.endswith("/api/v1/chat/title"):
                try:
                    responses.append(response.text()[:400])
                except Exception:
                    responses.append("<unreadable>")

        page.on("response", on_response)

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

        print("base:", BASE)

        try:
            existing = page.evaluate(MUTATE_JS, {"path": "/api/v1/chats?page=1&page_size=50", "method": "GET"})
            data = existing.get("data")
            rows = data.get("chats") if isinstance(data, dict) else []
            stale = [r["id"] for r in (rows or []) if "探针" in str(r.get("name") or "")]
            if stale:
                page.evaluate(
                    MUTATE_JS,
                    {"path": "/api/v1/chats", "method": "DELETE", "body": {"ids": stale}},
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

            session = page.evaluate(
                MUTATE_JS,
                {
                    "path": f"/api/v1/chats/{chat_id}/sessions",
                    "method": "POST",
                    "body": {"name": QUESTION},
                },
            )
            session_id = (session.get("data") or {}).get("id")
            print("session:", session_id)

            # What the page actually hydrates from: the detail endpoint, not the
            # create response.
            detail = page.evaluate(
                MUTATE_JS,
                {
                    "path": f"/api/v1/chats/{chat_id}/sessions/{session_id}",
                    "method": "GET",
                },
            )
            detail_data = detail.get("data") or {}
            messages = detail_data.get("message") or detail_data.get("messages")
            print(
                "detail messages:",
                json.dumps(messages, ensure_ascii=False)[:240] if messages else messages,
            )

            # Seed the first question and its answer, the two rows the titler waits
            # for. Same shape a completion persists.
            ok, conversation = ConversationService.get_by_id(session_id)
            if not ok:
                print("could not read the probe session back")
                return 1
            seeded = list(conversation.message or [])
            seeded.append({"role": "user", "content": QUESTION})
            seeded.append(
                {
                    "role": "assistant",
                    "content": "绞合节距不大于成缆外径的 25 倍，最外层绞向为右向。",
                }
            )
            ConversationService.update_by_id(session_id, {"message": seeded})
            print("seeded messages:", len(seeded))

            page.goto(
                f"{BASE}/chat/{chat_id}?conversationId={session_id}",
                wait_until="networkidle",
            )
            # The titler waits for an answer to arrive, so give hydration and the
            # effect a moment before deciding it never asked.
            page.wait_for_timeout(12000)

            rail_visible = page.evaluate("() => Boolean(document.querySelector(\"[data-testid='chat-detail-sessions']\"))")
            header_mounted = page.evaluate("() => Boolean(document.querySelector(\"[data-testid='chat-detail-header-toggle']\"))")
            print("sessions rail visible:", rail_visible, "| header mounted:", header_mounted)

            print(f"\ntitle requests: {len(titles)}")
            for body in titles:
                print("  body:", body[:200])
            for body in responses:
                print("  response:", body)

            if not titles:
                print("\n=> the page never asked the backend to title the conversation")
            else:
                print("\n=> the page asked, so the titler runs with the rail open")
        finally:
            if chat_id:
                page.evaluate(
                    MUTATE_JS,
                    {"path": "/api/v1/chats", "method": "DELETE", "body": {"ids": [chat_id]}},
                )
                print("deleted probe assistant:", chat_id)
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
