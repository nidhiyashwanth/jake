"""Live browser smoke for the C-01 Connections surface."""

from __future__ import annotations

import argparse
import secrets

from playwright.sync_api import Page, sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the live C-01 Connections browser smoke.")
    parser.add_argument("--frontend-url", default="http://localhost:13005")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    requests: list[tuple[str, str, dict[str, str]]] = []
    http_failures: list[str] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    secret = f"browser-synthetic-{secrets.token_urlsafe(12)}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page: Page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("response", lambda response: http_failures.append(f"{response.status} {response.url}") if response.status >= 400 else None)
        page.on(
            "request",
            lambda request: requests.append((request.method, request.url, request.headers))
            if "/api/connectors" in request.url or "/api/mcp" in request.url
            else None,
        )
        try:
            page.goto(args.frontend_url, wait_until="networkidle")
            if page.get_by_role("button", name="Sign out").count():
                page.get_by_role("button", name="Sign out").click()
            page.get_by_label("Email for local operator identity").fill(f"c01-browser-{secrets.token_hex(8)}@example.invalid")
            page.get_by_role("button", name="Start local session").click()
            page.get_by_role("button", name="Sign out").wait_for()
            page.get_by_role("button", name="Connections").click()
            page.get_by_role("heading", name="Connect the work, keep the boundary.").wait_for()
            requests.clear()

            page.get_by_label("New connector name").fill("Browser sandbox connector")
            page.get_by_label("Sandbox endpoint").fill("sandbox://sandbox.local")
            page.get_by_role("button", name="Add connector").click()
            page.get_by_text("Connector configuration saved without accepting a raw secret.").wait_for()
            page.get_by_label("OAuth refresh secret").fill(secret)
            page.get_by_role("button", name="Store encrypted credential").click()
            page.get_by_text("Credential encrypted in the workspace vault.").wait_for()
            page.get_by_role("button", name="Test selected connector").click()
            page.get_by_text("Sandbox health check passed.").wait_for()

            page.get_by_label("Server name").fill("Browser sandbox MCP")
            page.get_by_role("button", name="Pin MCP server").click()
            page.get_by_text("MCP server metadata pinned with an explicit tool and workflow allow-list.").wait_for()
            page.get_by_role("button", name="Call allow-listed tool").click()
            page.get_by_text("MCP call completed through the sandbox gateway; output remains untrusted.").wait_for()

            if not requests:
                raise AssertionError("the authenticated Connections surface made no connector or MCP API requests")
            if not all("authorization" in headers and "x-workspace-id" in headers for _, _, headers in requests):
                raise AssertionError("a Connections request lacked bearer or workspace context")
            if page_errors or http_failures:
                raise AssertionError(f"browser runtime errors: {page_errors}; HTTP failures: {http_failures}; console: {console_errors}")
            print("C-01 browser PASS: authenticated Connections UI, vault-safe credential flow, sandbox health, pinned MCP call, and scoped headers verified.")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
