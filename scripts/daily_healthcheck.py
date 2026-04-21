import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright


APP_URL = os.getenv("APP_URL", "https://skc-virtual-view-engine.streamlit.app")
HEALTHCHECK_CUSTOMER_ID = os.getenv("HEALTHCHECK_CUSTOMER_ID", "system-healthcheck")
HEALTHCHECK_TIMEZONE = os.getenv("HEALTHCHECK_TIMEZONE", "America/Toronto")
EXPECTED_LOCAL_HOUR = int(os.getenv("EXPECTED_LOCAL_HOUR", "9"))
REQUIRE_LOCAL_9AM = os.getenv("REQUIRE_LOCAL_9AM", "1") == "1"
ARTIFACT_DIR = Path(os.getenv("HEALTHCHECK_ARTIFACT_DIR", "healthcheck-artifacts"))
HEALTHCHECK_TIMEOUT_SECONDS = int(os.getenv("HEALTHCHECK_TIMEOUT_SECONDS", "300"))

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
STREAMLIT_SLEEP_MARKERS = [
    "This app has gone to sleep due to inactivity",
    "Would you like to wake it back up?",
]
WAKE_UP_BUTTON_LABEL = "Yes, get this app back up!"
STATUS_FILE_NAME = "status.txt"


def current_local_hour() -> int:
    return datetime.now(ZoneInfo(HEALTHCHECK_TIMEZONE)).hour


def build_url() -> str:
    separator = "&" if "?" in APP_URL else "?"
    return f"{APP_URL}{separator}customer_id={HEALTHCHECK_CUSTOMER_ID}"


def write_summary(status: str, message: str) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = ARTIFACT_DIR / "summary.md"
    status_path = ARTIFACT_DIR / STATUS_FILE_NAME
    status_path.write_text(status + "\n", encoding="utf-8")
    summary_path.write_text(
        f"# Daily health check\n\n"
        f"- status: `{status}`\n"
        f"- app_url: `{build_url()}`\n"
        f"- checked_at_utc: `{datetime.now(timezone.utc).isoformat()}`\n\n"
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


def skip(message: str) -> None:
    write_summary("skipped", message)
    print(message)
    sys.exit(0)


def maybe_skip_for_timezone() -> None:
    if not REQUIRE_LOCAL_9AM:
        return

    hour = current_local_hour()
    if hour != EXPECTED_LOCAL_HOUR:
        skip(
            f"Skipped run because current local hour in {HEALTHCHECK_TIMEZONE} is {hour}, "
            f"not {EXPECTED_LOCAL_HOUR}. This is expected when the workflow runs twice to handle DST."
        )


def read_body_text(target, timeout=5000) -> str:
    return target.locator("body").inner_text(timeout=timeout)


def maybe_wake_sleeping_app(page) -> bool:
    page_text = read_body_text(page)
    if not all(marker in page_text for marker in STREAMLIT_SLEEP_MARKERS):
        return False

    page.get_by_role("button", name=WAKE_UP_BUTTON_LABEL).click(timeout=10000)
    page.wait_for_timeout(5000)
    return True


def find_frame_with_markers(page, required_markers):
    for frame in page.frames:
        try:
            frame_text = read_body_text(frame)
        except Exception:
            continue

        if all(marker in frame_text for marker in required_markers):
            return frame, frame_text

    return None, ""


def collect_frame_texts(page) -> list[str]:
    frame_texts = []
    for frame in page.frames:
        try:
            frame_texts.append(read_body_text(frame))
        except Exception:
            continue
    return frame_texts


def main() -> None:
    maybe_skip_for_timezone()

    target_url = build_url()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = ARTIFACT_DIR / "app.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1600})
        page.goto(target_url, wait_until="domcontentloaded", timeout=120000)

        deadline = time.time() + HEALTHCHECK_TIMEOUT_SECONDS
        wake_attempted = False
        while time.time() < deadline:
            if maybe_wake_sleeping_app(page):
                wake_attempted = True

            frame_texts = collect_frame_texts(page)
            combined_text = "\n".join(frame_texts)

            if any(marker in combined_text for marker in FAILURE_MARKERS):
                page.screenshot(path=str(screenshot_path), full_page=True)
                browser.close()
                fail(f"Health check failed. Found failure marker in app output: {combined_text[:1200]}")

            main_frame, main_text = find_frame_with_markers(page, MAIN_FRAME_MARKERS)
            interactive_frame, interactive_text = find_frame_with_markers(
                page, INTERACTIVE_FRAME_MARKERS
            )

            if main_frame and interactive_frame:
                page.screenshot(path=str(screenshot_path), full_page=True)
                browser.close()
                success("Health check passed. Core UI and preview content loaded successfully.")

            page.wait_for_timeout(2000)

        page.screenshot(path=str(screenshot_path), full_page=True)
        browser.close()
        timeout_message = "Health check failed. Timed out before the deployed app reached a healthy state."
        if wake_attempted:
            timeout_message += " The app was woken from Streamlit sleep, but it still did not finish loading in time."
        fail(timeout_message)


if __name__ == "__main__":
    main()
