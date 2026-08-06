"""Live browser smoke for the X-01 staging-sandbox stack."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the X-01 browser smoke.")
    parser.add_argument("--frontend-url", default=os.environ.get("X01_FRONTEND_URL", "http://localhost:3000"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    console_errors: list[str] = []
    api_requests: list[tuple[str, str, dict[str, str]]] = []
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
        try:
            page.goto(args.frontend_url, wait_until="networkidle")
            if page.get_by_role("button", name="Sign out").count():
                page.get_by_role("button", name="Sign out").click()
            email = "x01-browser-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f") + "@example.invalid"
            page.get_by_label("Email for local operator identity").fill(email)
            page.get_by_role("button", name="Start local session").click()
            page.get_by_text("Start with one vendor").wait_for()
            if not any("/api/auth/session" in url or "/api/auth/context" in url for _, url, _ in api_requests):
                raise AssertionError("the staging-sandbox browser made no authenticated context request")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                raise AssertionError("the live staging-sandbox UI has horizontal overflow")
            if console_errors:
                raise AssertionError(f"browser console errors: {console_errors}")
            print("X-01 browser PASS: live frontend, local session, authenticated context, and layout smoke verified.")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
