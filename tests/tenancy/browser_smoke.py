"""Live browser smoke for the T-01 tenancy boundary.

Run this while the Compose project is up. It intentionally uses a fresh browser
context and a synthetic local-development identity; no credentials are read or
printed.
"""

from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


def main() -> None:
    email = f"browser-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}@example.invalid"
    api_requests: list[tuple[str, str, dict[str, str]]] = []
    console_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on(
            "request",
            lambda request: api_requests.append((request.method, request.url, request.headers))
            if "/api/" in request.url
            else None,
        )

        page.goto("http://localhost:3000", wait_until="networkidle")
        if page.get_by_role("button", name="Sign out").count():
            page.get_by_role("button", name="Sign out").click()
            page.get_by_label("Email for local operator identity").wait_for()
            api_requests.clear()
        page.get_by_label("Email for local operator identity").fill(email)
        page.get_by_role("button", name="Start local session").click()
        page.get_by_text("Local dev auth").wait_for()
        page.get_by_text("Start with one vendor").wait_for()

        protected_requests = [
            (method, url, headers)
            for method, url, headers in api_requests
            if "/api/vendors" in url or "/api/reviews" in url
        ]
        if not protected_requests:
            raise AssertionError("the authenticated F01 UI made no vendor/review API requests")
        if not all("authorization" in headers and "x-workspace-id" in headers for _, _, headers in protected_requests):
            raise AssertionError("an authenticated F01 request lacked bearer or workspace context")

        page.get_by_role("button", name="Field handoff").click()
        page.get_by_role("heading", name="Correction queue").wait_for()
        page.set_viewport_size({"width": 390, "height": 900})
        if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            raise AssertionError("the live T-01 UI has horizontal overflow at mobile width")

        page.reload(wait_until="networkidle")
        page.get_by_text("Local dev auth").wait_for()
        if not page.evaluate("Boolean(sessionStorage.getItem('fieldnote.development-session.v1'))"):
            raise AssertionError("the local session was not restored within the browser tab")
        if console_errors:
            raise AssertionError(f"browser console errors: {console_errors}")

        print("T01 browser PASS: live local auth, bearer/workspace-scoped F01 requests, handoff queue, mobile layout, and session restoration verified.")
        browser.close()


if __name__ == "__main__":
    main()
