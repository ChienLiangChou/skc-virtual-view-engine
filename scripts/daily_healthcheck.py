import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright


APP_URL = os.getenv("APP_URL", "https://skc-virtual-view-engine.streamlit.app")
HEALTHCHECK_CUSTOMER_ID = os.getenv("HEALTHCHECK_CUSTOMER_ID", "system-healthcheck")
HEALTHCHECK_TIMEZONE = os.getenv("HEALTHCHECK_TIMEZONE", "America/Toronto")
EXPECTED_LOCAL_HOUR = int(os.getenv("EXPECTED_LOCAL_HOUR", "9"))
REQUIRE_LOCAL_9AM = os.getenv("REQUIRE_LOCAL_9AM", "1") == "1"
ARTIFACT_DIR = Path(os.getenv("HEALTHCHECK_ARTIFACT_DIR", "healthcheck-artifacts"))

FAILURE_MARKERS = [
    "REQUEST_DENIED",
    "請先在終端機設定 GOOGLE_TILES_API_KEY",
    "這個客戶目前已被暫停",
    "建物辨識街景抓取失敗",
    "方向預覽抓取失敗",
    "俯視比例圖抓取失敗",
    "互動模式載入失敗",
    "糟糕！出了點狀況",
]

MAIN_FRAME_MARKERS = [
    "Kevin Chou/SKC Realty Team",
    "定位成功",
    "建物辨識街景",
    "定位品質",
]

INTERACTIVE_FRAME_MARKERS = [
    "互動街景",
    "互動衛星圖",
    "目前街景相機距建物約",
]


def current_local_hour() -> int:
    return datetime.now(ZoneInfo(HEALTHCHECK_TIMEZONE)).hour


def build_url() -> str:
    separator = "&" if "?" in APP_URL else "?"
    return f"{APP_URL}{separator}customer_id={HEALTHCHECK_CUSTOMER_ID}"


def write_summary(status: str, message: str) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = ARTIFACT_DIR / "summary.md"
    summary_path.write_text(
        f"# Daily health check\n\n"
        f"- status: `{status}`\n"
        f"- app_url: `{build_url()}`\n"
        f"- checked_at_utc: `{datetime.now(UTC).isoformat()}`\n\n"
        f"{message}\n",
        encoding="utf-8",
    )


def fail(message: str) -> None:
    write_summary("failed", message)
    print(message)
    sys.exit(1)


def success(message: str) -> None:
    write_summary("healthy", message)
    print(message)
    sys.exit(0)


def maybe_skip_for_timezone() -> None:
    if not REQUIRE_LOCAL_9AM:
        return

    hour = current_local_hour()
    if hour != EXPECTED_LOCAL_HOUR:
        success(
            f"Skipped run because current local hour in {HEALTHCHECK_TIMEZONE} is {hour}, "
            f"not {EXPECTED_LOCAL_HOUR}. This is expected when the workflow runs twice to handle DST."
        )


def main() -> None:
    maybe_skip_for_timezone()

    target_url = build_url()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = ARTIFACT_DIR / "app.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1600})
        page.goto(target_url, wait_until="domcontentloaded", timeout=120000)

        deadline = time.time() + 90
        while time.time() < deadline:
            if len(page.frames) < 4:
                page.wait_for_timeout(2000)
                continue

            main_frame = page.frames[2]
            interactive_frame = page.frames[3]
            main_text = main_frame.locator("body").inner_text(timeout=5000)
            interactive_text = interactive_frame.locator("body").inner_text(timeout=5000)
            combined_text = f"{main_text}\n{interactive_text}"

            if any(marker in combined_text for marker in FAILURE_MARKERS):
                page.screenshot(path=str(screenshot_path), full_page=True)
                browser.close()
                fail(f"Health check failed. Found failure marker in app output: {combined_text[:1200]}")

            if all(marker in main_text for marker in MAIN_FRAME_MARKERS) and all(
                marker in interactive_text for marker in INTERACTIVE_FRAME_MARKERS
            ):
                page.screenshot(path=str(screenshot_path), full_page=True)
                browser.close()
                success("Health check passed. Core UI and preview content loaded successfully.")

            page.wait_for_timeout(2000)

        page.screenshot(path=str(screenshot_path), full_page=True)
        browser.close()
        fail("Health check failed. Timed out before the deployed app reached a healthy state.")


if __name__ == "__main__":
    main()
