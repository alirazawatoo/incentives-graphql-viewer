"""Capture README screenshots from a running site backed by scripts/demo_provider.py.

usage: python scripts/screenshots.py http://127.0.0.1:8000 docs/screenshots
Needs the playwright package and Chromium. Fails if any page logs a console
error or an uncaught exception.
"""

import base64
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 390, "height": 844}
# (file name, path, viewport, full page, expected HTTP status)
SHOTS = [
    ("home-desktop.png", "/", DESKTOP, False, 200),
    ("chart-desktop.png", "/plot/?subnet=18", DESKTOP, True, 200),
    ("chart-mobile.png", "/plot/?subnet=18", MOBILE, False, 200),
    ("error-desktop.png", "/plot/?subnet=9999", DESKTOP, False, 502),
    ("empty-mobile.png", "/plot/?subnet=0", MOBILE, False, 200),
    ("invalid-mobile.png", "/plot/?subnet=abc", MOBILE, False, 400),
]
# Chromium logs the document's own 4xx/5xx status as a console error.
EXPECTED_STATUS_LOG = "Failed to load resource: the server responded with a status of"


def main(base_url: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    problems = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for name, path, viewport, full_page, status in SHOTS:
            page = browser.new_page(viewport=viewport)

            def on_console(msg, shot=name, expected=status):
                if msg.type != "error" or (expected != 200 and msg.text.startswith(EXPECTED_STATUS_LOG)):
                    return
                problems.append(f"{shot}: {msg.text}")

            page.on("console", on_console)
            page.on("pageerror", lambda exc, shot=name: problems.append(f"{shot}: {exc}"))
            response = page.goto(base_url + path, wait_until="networkidle")
            if response.status != status:
                problems.append(f"{name}: expected HTTP {status}, got {response.status}")
            page.evaluate("document.fonts.ready")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                problems.append(f"{name}: horizontal overflow")
            page.screenshot(path=str(out_dir / name), full_page=full_page)
            if name == "chart-desktop.png":
                src = page.get_attribute("figure img", "src")
                (out_dir / "synthetic-chart.png").write_bytes(base64.b64decode(src.split(",", 1)[1]))
            page.close()
            print("captured", name, flush=True)
        browser.close()
    if problems:
        sys.exit("\n".join(problems))


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/"), Path(sys.argv[2]))
