"""Live browser smoke for the V-01 operator review desk."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import re

from playwright.sync_api import Page, sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the live V-01 browser smoke.")
    parser.add_argument("--frontend-url", default="http://localhost:13004")
    parser.add_argument("--fixture", default=str(Path(__file__).with_name("browser_fixture.txt")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    requests: list[tuple[str, str, dict[str, str]]] = []
    console_errors: list[str] = []
    http_failures: list[str] = []
    page_errors: list[str] = []
    email = f"v01-browser-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}@example.invalid"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page: Page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("response", lambda response: http_failures.append(f"{response.status} {response.url}") if response.status >= 400 else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "request",
            lambda request: requests.append((request.method, request.url, request.headers))
            if "/api/reviews" in request.url
            else None,
        )
        try:
            page.goto(args.frontend_url, wait_until="networkidle")
            if page.get_by_role("button", name="Sign out").count():
                page.get_by_role("button", name="Sign out").click()
            page.get_by_label("Email for local operator identity").fill(email)
            page.get_by_role("button", name="Start local session").click()
            page.get_by_role("button", name="Sign out").wait_for()
            page.get_by_role("heading", name="Review desk").wait_for()
            requests.clear()
            page.get_by_role("button", name="Refresh").click()
            page.get_by_text("No open review tasks.").wait_for()
            page.locator("#new-vendor").fill("Browser V01 Vendor LLC")
            page.get_by_role("button", name="Add vendor").click()
            page.get_by_role("button", name=re.compile("Browser V01 Vendor LLC")).wait_for()
            page.locator("input[type=file]").set_input_files(args.fixture)
            page.get_by_role("button", name="Upload COI").click()
            page.get_by_role("button", name="Verify").click()
            page.get_by_text("1 open task").wait_for()
            queue_button = page.locator("button.review-queue-row-main", has_text="Browser V01 Vendor LLC")
            queue_button.focus()
            page.keyboard.press("Tab")
            queue_button.focus()
            started = perf_counter()
            page.keyboard.press("Enter")
            page.get_by_label("Correction for certificate_holder").wait_for()
            page.keyboard.press("e")
            page.get_by_label("Correction for certificate_holder").fill("Northwind Construction LLC")
            page.get_by_label("Reason code for certificate_holder").select_option("SOURCE_TEXT_CORRECTION")
            page.get_by_role("button", name="Re-check").click()
            page.get_by_text("Correction accepted. Vendor is now compliant.").wait_for()
            elapsed = perf_counter() - started
            if elapsed >= 20:
                raise AssertionError(f"representative review completion took {elapsed:.2f}s; expected under 20s")
            page.keyboard.press("r")
            page.get_by_text("No open review tasks.").wait_for()
            page.keyboard.press("?")
            page.get_by_text("Keyboard").wait_for()
            if not requests:
                raise AssertionError("the authenticated review desk made no live review API requests")
            if not all("authorization" in headers and "x-workspace-id" in headers for _, _, headers in requests):
                raise AssertionError("a review desk request lacked bearer or workspace context")
            unexpected_http = [failure for failure in http_failures if not (failure.startswith("404 ") and "/api/vendors/" in failure and failure.endswith("/status"))]
            if page_errors or unexpected_http:
                raise AssertionError(f"browser runtime errors: {page_errors}; unexpected HTTP failures: {unexpected_http}; console: {console_errors}")
            print("V-01 browser PASS: authenticated review desk, truthful empty state, keyboard help, and scoped API headers verified.")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
