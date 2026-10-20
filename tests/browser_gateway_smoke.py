"""Exercise the PR-base UI and container gateway in a real headless browser."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


def observe_browser(page: Page) -> tuple[list[str], list[str], list[str]]:
    console_errors: list[str] = []
    failed_requests: list[str] = []
    bad_responses: list[str] = []

    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.on("requestfailed", lambda request: failed_requests.append(request.url))
    page.on(
        "response",
        lambda response: (
            bad_responses.append(f"{response.status} {response.url}")
            if response.status >= 400
            else None
        ),
    )

    return console_errors, failed_requests, bad_responses


def exercise_baseline(page: Page, url: str, *, screenshot_prefix: str) -> None:
    console_errors, failed_requests, bad_responses = observe_browser(page)
    page.goto(url, wait_until="networkidle", timeout=30_000)
    page.get_by_role("heading", name="Three examples. One safe workflow.").wait_for()
    cards = page.locator("#artifacts article")
    assert cards.count() == 3, f"expected 3 baseline cards; found {cards.count()}"
    assert page.locator("#status").inner_text() == "All 3 synthetic examples are ready."
    page.screenshot(path=f"{screenshot_prefix}-before.png", full_page=True)
    cards.nth(0).get_by_role("button", name="Explain this example").click()
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
    page.locator("#facts-content").wait_for(state="visible")
    buttons = page.locator(".record-button")
    assert buttons.count() == 3
    page.screenshot(path=f"{screenshot_prefix}-inspect.png", full_page=True)
    for index in range(3):
        buttons.nth(index).click()
        expect(page.locator("#facts-content")).to_be_visible()
        assert page.locator("#fact-mutation").inner_text() == "No"
        assert page.locator("#fact-explanation").inner_text().strip()
    page.locator('[data-view="proof"]').click()
    page.locator("#proof-content").wait_for(state="visible")
    assert page.locator("#source-size").inner_text() == page.locator("#target-size").inner_text()
    assert "unknown" in page.locator("#proof-time").inner_text()
    page.screenshot(path=f"{screenshot_prefix}-proof.png", full_page=True)
    page.locator('[data-view="ask"]').click()
    assert "no model runs on this page" in page.locator("#ask-view").inner_text()
    assert page.locator("#ask-view textarea").count() == 0
    page.screenshot(path=f"{screenshot_prefix}-ask.png", full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert not console_errors, f"browser console errors: {console_errors}"
    assert not failed_requests, f"failed browser requests: {failed_requests}"
    assert not bad_responses, f"unsuccessful browser responses: {bad_responses}"


def main() -> None:
    gateway_url = os.environ["GATEWAY_URL"]
    compare_baseline = os.environ.get("COMPARE_BASELINE", "true").lower() == "true"
    screenshot_dir = Path(os.environ.get("SCREENSHOT_DIR", "screenshots"))
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        executable = os.environ.get("CHROMIUM_EXECUTABLE")
        browser = playwright.chromium.launch(
            **({"executable_path": executable} if executable else {})
        )
        try:
            screenshot_prefix = "current"
            if compare_baseline:
                exercise_baseline(
                    browser.new_page(),
                    os.environ["BASELINE_URL"],
                    screenshot_prefix=str(screenshot_dir / "before"),
                )
                screenshot_prefix = "after"
            for width in (1440, 1280, 768, 390):
                page = browser.new_page(viewport={"width": width, "height": 900})
                exercise_gateway(
                    page,
                    gateway_url,
                    screenshot_prefix=str(screenshot_dir / f"{screenshot_prefix}-{width}"),
                )
                page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
