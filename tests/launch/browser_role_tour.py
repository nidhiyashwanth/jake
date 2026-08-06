"""Live release-candidate browser tour for the customer-facing role paths."""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timezone

from playwright.sync_api import Page, sync_playwright


LIVE_SURFACES = (
    "Review desk",
    "Compliance policy",
    "Confidence lab",
    "Evaluation control",
    "Field handoff",
    "Workflows",
    "Discovery studio",
    "Execution runtime",
    "Connections",
    "Value ledger",
    "Governance",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the live LAUNCH-01 browser role tour.")
    parser.add_argument("--frontend-url", default=os.environ.get("LAUNCH_FRONTEND_URL", "http://localhost:13006"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    console_errors: list[str] = []
    api_requests: list[tuple[str, str, dict[str, str]]] = []
    visited: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page: Page = context.new_page()
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

            email = "launch-owner-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f") + "@example.invalid"
            page.get_by_label("Email for local operator identity").fill(email)
            page.get_by_role("button", name="Start local session").click()
            page.get_by_role("button", name="Sign out").wait_for()
            page.get_by_text(re.compile(r"Owner.*local")).wait_for()

            # Ignore the unauthenticated bootstrap/login requests. Every request
            # made by a live product surface must carry both scope headers.
            api_requests.clear()
            console_errors.clear()

            for surface in LIVE_SURFACES:
                nav = page.locator("button.nav-item").filter(has_text=surface)
                if nav.count() != 1:
                    raise AssertionError(f"expected one navigation item for {surface}, found {nav.count()}")
                nav = nav.first
                nav.wait_for()
                nav.click()
                page.get_by_role("heading", name=surface, exact=True).first.wait_for()
                if nav.get_attribute("aria-current") != "page":
                    raise AssertionError(f"{surface} did not become the active route")
                visited.append(surface)

            # Owner mode can be switched into the customer-operated handoff
            # path and back without changing the workspace boundary.
            page.get_by_role("button", name="Handoff", exact=True).click()
            page.get_by_text("Customer operated").wait_for()
            page.get_by_role("button", name="Delivery", exact=True).click()
            page.get_by_text("Team operated").wait_for()

            if not api_requests:
                raise AssertionError("the role tour made no authenticated API requests")
            if not all("authorization" in headers and "x-workspace-id" in headers for _, _, headers in api_requests):
                raise AssertionError("a role-tour API request lacked bearer or workspace context")
            if console_errors:
                raise AssertionError(f"browser console errors: {console_errors}")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                raise AssertionError("the role-tour UI has horizontal overflow")

            print(
                "LAUNCH-01 browser PASS: owner role toured "
                + str(len(visited))
                + " live surfaces, switched delivery/handoff modes, and preserved scoped API headers."
            )
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
