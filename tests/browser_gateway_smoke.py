"""Exercise the PR-base UI and container gateway in a real headless browser."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


def observe_browser(page: Page) -> tuple[list[str], list[str], list[str]]:
    console_errors: list[str] = []
    failed_requests: list[str] = []
    bad_responses: list[str] = []

    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.on("requestfailed", lambda request: failed_requests.append(request.url))
    page.on(
        "response",
        lambda response: bad_responses.append(f"{response.status} {response.url}")
        if response.status >= 400
        else None,
    )

    return console_errors, failed_requests, bad_responses


def exercise_baseline(page: Page, url: str, *, screenshot_prefix: str) -> None:
    console_errors, failed_requests, bad_responses = observe_browser(page)
    page.goto(url, wait_until="networkidle", timeout=30_000)
    page.get_by_role("heading", name="Three examples. One safe workflow.").wait_for()
    cards = page.locator("#artifacts article")
    assert cards.count() == 3, f"expected 3 baseline cards; found {cards.count()}"
    assert "3 synthetic artifacts" in page.locator("#status").inner_text()
    page.screenshot(path=f"{screenshot_prefix}-before.png", full_page=True)
    cards.nth(0).get_by_role("button", name="Inspect").click()
    page.wait_for_function(
        "document.querySelector('#artifacts article .inspection')?.innerText !== 'Not inspected'"
    )
    page.screenshot(path=f"{screenshot_prefix}-after.png", full_page=True)
    assert not console_errors, f"baseline browser console errors: {console_errors}"
    assert not failed_requests, f"baseline failed browser requests: {failed_requests}"
    assert not bad_responses, f"baseline unsuccessful browser responses: {bad_responses}"


def exercise_gateway(page: Page, url: str, *, screenshot_prefix: str) -> None:
    console_errors, failed_requests, bad_responses = observe_browser(page)
    page.goto(url, wait_until="networkidle", timeout=30_000)
    page.get_by_role("heading", name="Choose an example to explore").wait_for()
    cards = page.locator("article.card")
    assert cards.count() == 3, f"expected 3 gateway cards; found {cards.count()}"
    assert page.locator("#status").inner_text() == "All 3 synthetic examples are ready."
    page.screenshot(path=f"{screenshot_prefix}-before.png", full_page=True)

    buttons = page.get_by_role("button", name="Explain this example")
    assert buttons.count() == 3
    for index in range(3):
        buttons.nth(index).click()
        result = cards.nth(index).locator(".result")
        result.get_by_text("What this means", exact=True).wait_for(timeout=10_000)
        explanation = result.locator(".result-copy").inner_text()
        assert explanation.strip()

    page.screenshot(path=f"{screenshot_prefix}-after.png", full_page=True)
    assert not console_errors, f"browser console errors: {console_errors}"
    assert not failed_requests, f"failed browser requests: {failed_requests}"
    assert not bad_responses, f"unsuccessful browser responses: {bad_responses}"


def main() -> None:
    gateway_url = os.environ["GATEWAY_URL"]
    compare_baseline = os.environ.get("COMPARE_BASELINE", "true").lower() == "true"
    screenshot_dir = Path(os.environ.get("SCREENSHOT_DIR", "screenshots"))
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            screenshot_prefix = "current"
            if compare_baseline:
                exercise_baseline(
                    browser.new_page(),
                    os.environ["BASELINE_URL"],
                    screenshot_prefix=str(screenshot_dir / "before"),
                )
                screenshot_prefix = "after"
            exercise_gateway(
                browser.new_page(),
                gateway_url,
                screenshot_prefix=str(screenshot_dir / screenshot_prefix),
            )
        finally:
            browser.close()


if __name__ == "__main__":
    main()
