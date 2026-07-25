#!/usr/bin/env python3
"""
duck_ai_playwright.py
Playwright-based Duck.ai automation with anti-detection measures.
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("duck_ai_playwright")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Error: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


def run(prompt: str, headless: bool = True, timeout: int = 30) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            logger.info("Navigating to duck.ai...")
            page.goto("https://duck.ai", wait_until="networkidle", timeout=timeout * 1000)
            time.sleep(3)

            # Check for bot challenge
            body_text = page.locator("body").inner_text().lower()
            challenge_markers = [
                "select all squares containing",
                "bots use duckduckgo",
                "please complete the following challenge"
            ]
            if any(m in body_text for m in challenge_markers):
                page.screenshot(path=f"/tmp/duck_challenge_{int(time.time())}.png")
                return {"success": False, "error": "Bot challenge detected"}

            # Find textarea
            textarea = page.locator("textarea[placeholder*='Reply'], textarea[placeholder*='Message'], textarea[placeholder*='Ask']")
            textarea.wait_for(state="visible", timeout=10000)
            textarea.click()
            time.sleep(0.5)

            # Type like human
            for char in prompt:
                textarea.type(char, delay=random.randint(10, 80))
            time.sleep(1)

            # Click send (SVG button or aria)
            send_clicked = False
            buttons = page.locator("button").all()
            for btn in reversed(buttons):
                try:
                    if btn.locator("svg").count() > 0:
                        btn.click()
                        send_clicked = True
                        logger.info("Clicked send via SVG button")
                        break
                except Exception:
                    continue

            if not send_clicked:
                try:
                    send = page.get_by_role("button", name=re.compile("send", re.I))
                    send.click()
                    send_clicked = True
                except Exception:
                    pass

            if not send_clicked:
                textarea.press("Enter")

            time.sleep(6)

            # Extract response
            msgs = page.locator("[data-testid='assistant-message'], .message-ai, .assistant").all()
            if msgs:
                return {"success": True, "response": msgs[-1].inner_text()}

            all_msgs = page.locator(".message, .chat-message").all()
            if len(all_msgs) >= 2:
                return {"success": True, "response": all_msgs[-1].inner_text()}

            return {"success": False, "error": "No response extracted"}

        except PlaywrightTimeout:
            page.screenshot(path=f"/tmp/duck_timeout_{int(time.time())}.png")
            return {"success": False, "error": "Timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", help="Message to send")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    result = run(args.prompt, headless=not args.no_headless, timeout=args.timeout)
    print(json.dumps(result, indent=2))