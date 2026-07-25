#!/usr/bin/env python3
"""
askrain_selenium.py
Standalone Selenium automation for AskRain (askrain.ai).
Pierces shadow DOM under <ai-chat-bot> to interact with controls.
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
logger = logging.getLogger("askrain")


def shadow_root(driver):
    """Pierce the <ai-chat-bot> shadow root."""
    host = driver.find_element(By.TAG_NAME, "ai-chat-bot")
    return driver.execute_script("return arguments[0].shadowRoot", host)


def run(message: str, headless: bool = True, timeout: int = 30) -> dict:
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")

    chromedriver = os.environ.get("CHROMEDRIVER_PATH")
    service = None
    if chromedriver:
        from selenium.webdriver.chrome.service import Service
        service = Service(chromedriver)

    driver = webdriver.Chrome(options=opts, service=service)
    wait = WebDriverWait(driver, timeout)

    try:
        logger.info("Navigating to askrain.ai...")
        driver.get("https://askrain.ai")
        time.sleep(3)

        # Close welcome overlay if present
        try:
            overlay = driver.find_element(
                By.CSS_SELECTOR, "[data-testid='welcome-close'], .welcome-overlay button"
            )
            overlay.click()
            time.sleep(0.5)
        except NoSuchElementException:
            pass

        root = shadow_root(driver)

        # Find input
        inp = root.find_element(
            By.CSS_SELECTOR,
            "textarea, input[type='text'], [contenteditable='true']"
        )
        inp.click()
        time.sleep(0.5)
        inp.send_keys(message)
        time.sleep(0.5)

        # Find send button inside shadow
        try:
            btn = root.find_element(
                By.CSS_SELECTOR,
                "button[aria-label*='send'], button[type='submit'], button:last-child"
            )
            btn.click()
            logger.info("Clicked send button inside shadow DOM")
        except Exception as e:
            logger.warning(f"Send click failed, trying Enter: {e}")
            inp.send_keys(Keys.RETURN)

        time.sleep(6)

        # Re-acquire shadow and extract response
        root = shadow_root(driver)
        responses = root.find_elements(
            By.CSS_SELECTOR,
            ".message-ai, .assistant-message, .response, [class*='message']:not([class*='user'])"
        )
        if responses:
            text = responses[-1].text
            return {"success": True, "response": text}
        return {"success": False, "error": "No response found in shadow DOM"}

    except TimeoutException:
        return {"success": False, "error": "Timeout waiting for shadow DOM elements"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        driver.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("message", help="Message to send to AskRain")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    result = run(args.message, headless=not args.no_headless, timeout=args.timeout)
    print(json.dumps(result, indent=2))