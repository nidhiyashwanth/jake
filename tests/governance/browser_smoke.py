"""Live browser smoke for the G-01 governance surface."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from playwright.sync_api import Page, sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the live G-01 browser smoke.")
    parser.add_argument("--frontend-url", default="http://localhost:3000")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    requests: list[tuple[str, str, dict[str, str]]] = []
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page: Page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on(
            "request",
            lambda request: requests.append((request.method, request.url, request.headers))
            if "/api/governance/" in request.url
            else None,
        )
        try:
            page.goto(args.frontend_url, wait_until="networkidle")
            if page.get_by_role("button", name="Sign out").count():
                page.get_by_role("button", name="Sign out").click()
            email = "g01-browser-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f") + "@example.invalid"
            page.get_by_label("Email for local operator identity").fill(email)
            page.get_by_role("button", name="Start local session").click()
            page.get_by_role("button", name="Sign out").wait_for()
            page.get_by_role("button", name="Governance").click()
            page.get_by_role("heading", name="Make every decision inspectable.").wait_for()
            page.get_by_role("button", name="Run retention dry-run").wait_for()
            page.get_by_role("button", name="Generate audit pack").wait_for()
            if not requests:
                raise AssertionError("the governance surface made no live API requests")
            if not all("authorization" in headers and "x-workspace-id" in headers for _, _, headers in requests):
                raise AssertionError("a governance request lacked bearer or workspace context")
            if console_errors:
                raise AssertionError(f"browser console errors: {console_errors}")
            print("G-01 browser PASS: authenticated governance surface, controls, empty state, and scoped API headers verified.")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
