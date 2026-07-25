#!/usr/bin/env python3
"""
google_ai_selenium.py
Standalone Selenium automation for Google AI Mode (labs.google).
Clicks the "Ask AI" / "AI Mode" button and submits prompts.
"""

import argparse
import json
import logging
import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("google_ai")


def run(message: str, headless: bool = True, timeout: int = 30) -> dict:
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")

    # Termux-specific paths
    termux_chrome = "/data/data/com.termux/files/usr/bin/chromium"
    termux_driver = "/data/data/com.termux/files/usr/bin/chromedriver"
    if os.path.exists(termux_chrome):
        opts.binary_location = termux_chrome

    chromedriver = os.environ.get("CHROMEDRIVER_PATH", termux_driver if os.path.exists(termux_driver) else None)
    service = None
    if chromedriver:
        from selenium.webdriver.chrome.service import Service
        service = Service(chromedriver)

    driver = webdriver.Chrome(options=opts, service=service)
    wait = WebDriverWait(driver, timeout)

    try:
        logger.info("Navigating to Google...")
        driver.get("https://www.google.com")
        time.sleep(2)

        # Look for AI Mode button (labs.google or search page)
        try:
            ai_btn = wait.until(EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                "a[href*='labs.google'], button[aria-label*='AI'], [data-testid='ai-mode']"
            )))
            ai_btn.click()
            logger.info("Clicked AI Mode button")
        except TimeoutException:
            logger.warning("AI Mode button not found, trying direct labs URL")
            driver.get("https://labs.google")
            time.sleep(3)

        # Find input
        try:
            inp = wait.until(EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                "textarea, input[type='text'], [contenteditable='true'], [role='textbox']"
            )))
        except TimeoutException:
            return {"success": False, "error": "Could not find input field"}

        inp.click()
        time.sleep(0.5)
        inp.send_keys(message)
        time.sleep(0.5)
        inp.send_keys(Keys.RETURN)
        logger.info("Sent message")

        time.sleep(6)

        # Extract response
        try:
            responses = driver.find_elements(
                By.CSS_SELECTOR,
                ".response, .ai-response, [data-testid='response'], .message"
            )
            if responses:
                return {"success": True, "response": responses[-1].text}
        except Exception as e:
            logger.error(f"Response extraction failed: {e}")

        return {"success": False, "error": "No response extracted"}

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        driver.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("message", help="Message to send")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    result = run(args.message, headless=not args.no_headless, timeout=args.timeout)
    print(json.dumps(result, indent=2))