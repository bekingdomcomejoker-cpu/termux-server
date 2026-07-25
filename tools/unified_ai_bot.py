#!/usr/bin/env python3
"""
unified_ai_bot.py
Unified automation framework for AI chat interfaces.
Supports AskRain (shadow DOM) and Duck.ai (light DOM + stealth anti-detection).
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementNotInteractableException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("unified_ai_bot")


@dataclass
class BotConfig:
    headless: bool = True
    timeout: int = 30
    stealth: bool = True
    screenshot_on_fail: bool = True
    user_data_dir: Optional[str] = None
    chromedriver_path: Optional[str] = None
    binary_location: Optional[str] = None
    window_size: str = "1920,1080"


class AIBot(ABC):
    """Abstract base for AI chat automation."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None

    def _build_options(self) -> webdriver.ChromeOptions:
        opts = webdriver.ChromeOptions()

        if self.config.headless:
            opts.add_argument("--headless=new")

        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument(f"--window-size={self.config.window_size}")
        opts.add_argument("--disable-infobars")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-popup-blocking")
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--allow-running-insecure-content")
        opts.add_argument("--disable-features=IsolateOrigins,site-per-process")

        if self.config.stealth:
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
            opts.add_argument(
                "--user-agent=Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )

        if self.config.user_data_dir:
            opts.add_argument(f"--user-data-dir={self.config.user_data_dir}")

        if self.config.binary_location:
            opts.binary_location = self.config.binary_location

        return opts

    def _apply_stealth_js(self):
        """Patch navigator.webdriver and other detection vectors via CDP."""
        if not self.config.stealth or not self.driver:
            return
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications'
                        ? Promise.resolve({ state: Notification.permission })
                        : originalQuery(parameters)
                );
            """
        })

    def start(self):
        """Initialize the browser."""
        opts = self._build_options()
        service = None
        if self.config.chromedriver_path:
            from selenium.webdriver.chrome.service import Service
            service = Service(self.config.chromedriver_path)
        self.driver = webdriver.Chrome(options=opts, service=service)
        self.wait = WebDriverWait(self.driver, self.config.timeout)
        self._apply_stealth_js()
        logger.info("Browser started")

    def stop(self):
        """Clean up."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            logger.info("Browser stopped")

    def _human_delay(self, min_sec: float = 0.5, max_sec: float = 2.0):
        time.sleep(random.uniform(min_sec, max_sec))

    def _type_like_human(self, element, text: str):
        """Type text with variable speed to mimic human behavior."""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.01, 0.08))

    def _screenshot(self, name: str) -> Optional[str]:
        if not self.config.screenshot_on_fail or not self.driver:
            return None
        path = f"/tmp/bot_fail_{name}_{int(time.time())}.png"
        try:
            self.driver.save_screenshot(path)
            logger.info(f"Screenshot saved: {path}")
            return path
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None

    def _dump_dom(self, name: str) -> Optional[str]:
        """Dump page source for debugging."""
        if not self.driver:
            return None
        path = f"/tmp/bot_dom_{name}_{int(time.time())}.html"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            return path
        except Exception as e:
            logger.error(f"DOM dump failed: {e}")
            return None

    @abstractmethod
    def send_message(self, message: str) -> str:
        pass

    @abstractmethod
    def is_challenge_present(self) -> bool:
        pass


class AskRainBot(AIBot):
    """Bot for AskRain — pierces shadow DOM under <ai-chat-bot>."""

    URL = "https://askrain.ai"
    HOST_TAG = "ai-chat-bot"

    def _get_shadow_root(self):
        host = self.wait.until(
            EC.presence_of_element_located((By.TAG_NAME, self.HOST_TAG))
        )
        return self.driver.execute_script("return arguments[0].shadowRoot", host)

    def is_challenge_present(self) -> bool:
        return False

    def send_message(self, message: str) -> str:
        if not self.driver:
            self.start()

        self.driver.get(self.URL)
        self._human_delay(2, 4)

        # Close welcome overlay if present
        try:
            overlay = self.driver.find_element(
                By.CSS_SELECTOR, "[data-testid='welcome-close'], .welcome-overlay button, .modal-close"
            )
            overlay.click()
            self._human_delay(0.5, 1)
        except NoSuchElementException:
            pass

        root = self._get_shadow_root()

        # Find input inside shadow
        inp = root.find_element(
            By.CSS_SELECTOR,
            "textarea, input[type='text'], [contenteditable='true']"
        )
        inp.click()
        self._human_delay(0.3, 0.8)
        self._type_like_human(inp, message)
        self._human_delay(0.5, 1.5)

        # Find send button inside shadow
        try:
            btn = root.find_element(
                By.CSS_SELECTOR,
                "button[aria-label*='send'], button[type='submit'], button svg, button:last-child"
            )
            btn.click()
        except Exception as e:
            logger.warning(f"Send button click failed, trying Enter: {e}")
            inp.send_keys(Keys.RETURN)

        self._human_delay(4, 8)

        # Re-acquire shadow and extract response
        try:
            root = self._get_shadow_root()
            responses = root.find_elements(
                By.CSS_SELECTOR,
                ".message-ai, .assistant-message, .response, [class*='message']:not([class*='user'])"
            )
            if responses:
                return responses[-1].text
        except Exception as e:
            logger.error(f"Response extraction failed: {e}")

        return "No response extracted from AskRain"


class DuckAIBot(AIBot):
    """Bot for Duck.ai — light DOM with stealth anti-detection."""

    URL = "https://duck.ai"

    CHALLENGE_MARKERS: List[str] = [
        "select all squares containing",
        "bots use duckduckgo",
        "please complete the following challenge",
        "captcha",
        "verify you are human",
        "prove you are human",
    ]

    def is_challenge_present(self) -> bool:
        if not self.driver:
            return False
        try:
            return self._check_challenge()
        except Exception:
            return False

    def _check_challenge(self) -> bool:
        page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        return any(marker in page_text for marker in self.CHALLENGE_MARKERS)

    def send_message(self, message: str) -> str:
        if not self.driver:
            self.start()

        self.driver.get(self.URL)
        self._human_delay(4, 7)

        if self._check_challenge():
            self._screenshot("duck_challenge_pre")
            self._dump_dom("duck_challenge_pre")
            raise RuntimeError("DuckDuckGo bot challenge detected on load. Automation blocked.")

        # Find textarea
        try:
            inp = self.wait.until(EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                "textarea[placeholder*='Reply'], textarea[placeholder*='Message'], "
                "textarea[placeholder*='Ask'], .chat-input textarea, [contenteditable='true']"
            )))
        except TimeoutException:
            self._screenshot("duck_no_input")
            self._dump_dom("duck_no_input")
            raise RuntimeError("Could not find Duck.ai input textarea")

        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", inp)
        self._human_delay(0.5, 1.2)

        try:
            inp.click()
        except ElementNotInteractableException:
            self.driver.execute_script("arguments[0].focus();", inp)
        self._human_delay(0.3, 0.7)

        inp.clear()
        self._type_like_human(inp, message)
        self._human_delay(1.0, 2.0)

        # Click send button (NOT Enter — Duck.ai requires explicit button click)
        send_clicked = False
        try:
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
            for btn in reversed(buttons):
                try:
                    btn.find_element(By.TAG_NAME, "svg")
                    btn.click()
                    send_clicked = True
                    logger.info("Send clicked via SVG button")
                    break
                except NoSuchElementException:
                    continue
        except Exception as e:
            logger.warning(f"SVG button search failed: {e}")

        if not send_clicked:
            try:
                send_btn = self.wait.until(EC.element_to_be_clickable((
                    By.CSS_SELECTOR,
                    "button[aria-label*='send'], button[title*='send'], .send-button"
                )))
                send_btn.click()
                send_clicked = True
                logger.info("Send clicked via aria-label")
            except Exception as e:
                logger.warning(f"Aria-label send failed: {e}")

        if not send_clicked:
            raise RuntimeError("Could not find or click Duck.ai send button")

        self._human_delay(0.5, 1.0)

        # Wait for response
        self._human_delay(5, 10)

        if self._check_challenge():
            self._screenshot("duck_challenge_post")
            self._dump_dom("duck_challenge_post")
            raise RuntimeError("DuckDuckGo bot challenge appeared after sending.")

        # Extract response
        try:
            msgs = self.driver.find_elements(By.CSS_SELECTOR, "[data-testid='assistant-message'], .message-ai, .assistant")
            if msgs:
                return msgs[-1].text
            all_msgs = self.driver.find_elements(By.CSS_SELECTOR, ".message, .chat-message")
            if len(all_msgs) >= 2:
                return all_msgs[-1].text
        except Exception as e:
            logger.error(f"Response extraction error: {e}")

        return "Response extraction failed"


def main():
    parser = argparse.ArgumentParser(description="Unified AI Bot")
    parser.add_argument("message", help="Message to send")
    parser.add_argument("--platform", choices=["askrain", "duckai"], required=True)
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", dest="headless", action="store_false")
    parser.add_argument("--stealth", action="store_true", default=True)
    parser.add_argument("--no-stealth", dest="stealth", action="store_false")
    parser.add_argument("--chromedriver", default=os.environ.get("CHROMEDRIVER_PATH"))
    parser.add_argument("--binary", default=os.environ.get("CHROME_BINARY"))
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--user-data-dir", default=None)
    args = parser.parse_args()

    config = BotConfig(
        headless=args.headless,
        timeout=args.timeout,
        stealth=args.stealth,
        chromedriver_path=args.chromedriver,
        binary_location=args.binary,
        user_data_dir=args.user_data_dir,
    )

    BotClass = AskRainBot if args.platform == "askrain" else DuckAIBot
    bot = BotClass(config)

    try:
        response = bot.send_message(args.message)
        print(json.dumps({"success": True, "response": response}, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, indent=2))
        sys.exit(1)
    finally:
        bot.stop()


if __name__ == "__main__":
    main()