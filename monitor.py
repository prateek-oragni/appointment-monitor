#!/usr/bin/env python3
"""
Gentle Dental booking page monitor.
Checks whether the HSOne booking page is online (showing the appointment form)
or offline, and logs results with timestamps.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

URL = "https://booking.uk.hsone.app/soe/new/Gentle%20Dental%20UK%20Ltd?pid=UKGDC01"
LOG_FILE = Path(__file__).parent / "status_log.jsonl"

ONLINE_MARKERS = [
    "Have you booked an appointment with us before",
    "What can we help you with",
    "Express Clean Hygiene",
    "Choose your provider",
]

OFFLINE_MARKERS = [
    "offline",
    "currently unavailable",
    "not available",
    "temporarily closed",
    "outside of office hours",
    "come back later",
    "not accepting",
]


def check_page(headless: bool = True, timeout_ms: int = 30000) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": URL,
            "status": "unknown",
            "http_status": None,
            "detail": "",
            "page_text_snippet": "",
        }

        try:
            response = page.goto(URL, wait_until="networkidle", timeout=timeout_ms)
            result["http_status"] = response.status if response else None

            page.wait_for_timeout(5000)

            visible_text = page.evaluate("""() => {
                function getTextFromNode(node) {
                    let text = '';
                    if (node.shadowRoot) {
                        text += getTextFromNode(node.shadowRoot);
                    }
                    for (const child of node.childNodes) {
                        if (child.nodeType === Node.TEXT_NODE) {
                            text += child.textContent + ' ';
                        } else if (child.nodeType === Node.ELEMENT_NODE) {
                            const style = window.getComputedStyle(child);
                            if (style.display !== 'none' && style.visibility !== 'hidden') {
                                text += getTextFromNode(child);
                            }
                        }
                    }
                    return text;
                }
                return getTextFromNode(document.body);
            }""")

            result["page_text_snippet"] = visible_text.strip()[:500]
            lower = visible_text.lower()

            online_matched = [m for m in ONLINE_MARKERS if m.lower() in lower]
            offline_matched = [m for m in OFFLINE_MARKERS if m.lower() in lower]

            if online_matched:
                result["status"] = "online"
                result["detail"] = f"Booking form is visible ({', '.join(online_matched[:2])})"
            elif offline_matched:
                result["status"] = "offline"
                result["detail"] = f"Offline indicator found: {offline_matched}"
            elif len(visible_text.strip()) < 30:
                result["status"] = "offline"
                result["detail"] = "Page loaded but content is empty/minimal"
            else:
                result["status"] = "unknown"
                result["detail"] = f"Page loaded, could not classify. Text length: {len(visible_text.strip())}"

            uk_now = datetime.now(ZoneInfo("Europe/London"))
            ts_str = uk_now.strftime("%Y%m%d_%H%M%S")
            screenshots_dir = Path(__file__).parent / "screenshots"
            screenshots_dir.mkdir(exist_ok=True)
            ss_path = screenshots_dir / f"screenshot_{ts_str}.png"
            page.screenshot(path=str(ss_path))

            img = Image.open(ss_path)
            draw = ImageDraw.Draw(img)
            stamp = uk_now.strftime("%H:%M:%S")
            font = ImageFont.load_default(size=28)
            draw.rectangle([10, 10, 200, 48], fill="black")
            draw.text((15, 12), stamp, fill="white", font=font)
            img.save(ss_path)

        except PwTimeout:
            result["status"] = "error"
            result["detail"] = "Page load timed out"
        except Exception as e:
            result["status"] = "error"
            result["detail"] = str(e)
        finally:
            browser.close()

        return result


def log_result(result: dict):
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result) + "\n")


def print_result(result: dict):
    status_icon = {
        "online": "\033[32m● ONLINE\033[0m",
        "offline": "\033[31m● OFFLINE\033[0m",
        "error": "\033[33m● ERROR\033[0m",
        "unknown": "\033[33m● UNKNOWN\033[0m",
    }
    icon = status_icon.get(result["status"], "?")
    ts = result["timestamp"]
    print(f"[{ts}] {icon} — {result['detail']}")
    if result["status"] != "online":
        snippet = result["page_text_snippet"][:200].replace("\n", " ")
        print(f"  Page text: {snippet}")


def show_history():
    if not LOG_FILE.exists():
        print("No log history yet.")
        return

    entries = [json.loads(line) for line in LOG_FILE.read_text().splitlines() if line.strip()]
    if not entries:
        print("No log history yet.")
        return

    online_count = sum(1 for e in entries if e["status"] == "online")
    offline_count = sum(1 for e in entries if e["status"] == "offline")
    error_count = sum(1 for e in entries if e["status"] == "error")
    total = len(entries)

    print(f"\n{'='*60}")
    print(f"  Booking Page Monitor — {total} checks")
    print(f"{'='*60}")
    print(f"  Online:  {online_count:>4}  ({100*online_count/total:.1f}%)")
    print(f"  Offline: {offline_count:>4}  ({100*offline_count/total:.1f}%)")
    print(f"  Error:   {error_count:>4}  ({100*error_count/total:.1f}%)")
    print(f"{'='*60}\n")

    print("Recent checks:")
    for entry in entries[-20:]:
        print_result(entry)
    print()


def main():
    parser = argparse.ArgumentParser(description="Monitor Gentle Dental booking page")
    parser.add_argument("--loop", type=int, metavar="MINS", help="Re-check every N minutes")
    parser.add_argument("--history", action="store_true", help="Show check history and stats")
    parser.add_argument("--visible", action="store_true", help="Run browser in visible (non-headless) mode")
    args = parser.parse_args()

    if args.history:
        show_history()
        return

    while True:
        result = check_page(headless=not args.visible)
        log_result(result)
        print_result(result)

        if not args.loop:
            break

        print(f"  Next check in {args.loop} minutes...")
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()
