"""Live browser smoke for the W-01 workflow designer contract.

The smoke uses a fresh Playwright context and a synthetic local-development
identity. It verifies the form-driven editor, read-only graph marker, publish
failure visibility, and bearer/workspace headers on workflow requests. It never
reads credentials or response bodies. The tracked UI markers are
``data-read-only=true``, ``draggable``, and the ``Publish workflow`` action.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the live W-01 browser smoke.")
    parser.add_argument("--frontend-url", default="http://localhost:13002")
    parser.add_argument(
        "--contract",
        default=str(Path(__file__).with_name("contract.json")),
    )
    return parser.parse_args()


def wait_for_login(page: Page) -> None:
    email_field = page.get_by_label("Email for local operator identity")
    email_field.wait_for()
    email = f"w01-browser-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}@example.invalid"
    email_field.fill(email)
    page.get_by_role("button", name="Start local session").click()
    page.get_by_text("Local dev auth").wait_for()


def require_form_label(page: Page, label: str) -> None:
    if page.get_by_label(label, exact=True).count() < 1:
        raise AssertionError(f"W-01 browser contract missing form label: {label}")


def main() -> None:
    args = parse_args()
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    ui = contract["ui"]
    api_requests: list[tuple[str, str, dict[str, str]]] = []
    console_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "request",
            lambda request: api_requests.append(
                (request.method, request.url, request.headers)
            )
            if "/api/" in request.url
            else None,
        )

        try:
            page.goto(args.frontend_url + ui["path"], wait_until="networkidle")
            if page.get_by_role("button", name="Sign out").count():
                page.get_by_role("button", name="Sign out").click()
                page.get_by_label("Email for local operator identity").wait_for()
                api_requests.clear()

            wait_for_login(page)
            page.get_by_role("button", name=ui["navigation_name"]).click()
            page.get_by_role("heading", name=ui["heading"]).wait_for()

            for label in ui["required_form_labels"][:3]:
                require_form_label(page, label)

            page.get_by_label("Workflow name", exact=True).fill(
                "W-01 browser synthetic workflow"
            )
            page.get_by_label("Workflow key", exact=True).fill("w01-browser-synthetic")
            page.get_by_label("Description", exact=True).fill(
                "Form-driven W-01 browser contract"
            )
            page.get_by_role("button", name=ui["create_button_name"]).click()

            for label in ui["required_form_labels"][3:]:
                require_form_label(page, label)

            graph = page.locator(ui["graph_selector"])
            graph.wait_for()
            if graph.get_attribute(ui["graph_read_only_attribute"]) != ui[
                "graph_read_only_value"
            ]:
                raise AssertionError("W-01 graph is not marked read-only")
            if graph.locator("[draggable='true']").count() != 0:
                raise AssertionError("W-01 graph exposed a draggable mutation surface")

            page.get_by_role("button", name=ui["save_button_name"]).click()
            page.get_by_role("button", name=ui["publish_button_name"]).click()
            failure = page.get_by_role(ui["evaluation_failure_role"])
            failure.wait_for()
            if ui["evaluation_failure_text"].lower() not in failure.inner_text().lower():
                raise AssertionError(
                    "W-01 publish denial did not expose evaluation failure guidance"
                )

            workflow_requests = [
                (method, url, headers)
                for method, url, headers in api_requests
                if "/api/workflows" in url or "/api/workflow-versions" in url
            ]
            if not workflow_requests:
                raise AssertionError("the browser made no live W-01 API requests")
            if not all(
                "authorization" in headers and "x-workspace-id" in headers
                for _, _, headers in workflow_requests
            ):
                raise AssertionError(
                    "a live W-01 request lacked bearer or workspace context"
                )
            if console_errors:
                raise AssertionError(f"browser console errors: {console_errors}")

            print(
                "W-01 browser PASS: authenticated form editor, persisted draft path, "
                "read-only graph, evaluation-gated publish guidance, and scoped API "
                "headers verified."
            )
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
