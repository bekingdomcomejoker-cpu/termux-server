#!/usr/bin/env python3
"""
duck_ai_chat.py — Duck.ai automation (AskRain-style)

Primary path: unofficial HTTP clients (duckai / duck-chat style) — preferred.
Fallback path: Selenium against https://duck.ai/ (fragile; UI changes).

Env (all optional except prompt):
  DUCKAI_PROMPT          First user message (required for one-shot)
  DUCKAI_MODEL           Model id string (see --list-models)
  DUCKAI_MAX_TURNS       Default 3
  DUCKAI_TURN_DELAY      Seconds between turns (default 16; public clients often ~1/15s)
  DUCKAI_MODE            api | selenium | auto  (default auto)
  DUCKAI_HEADLESS        1/0 for selenium (default 1)
  CHROME_BIN             Chromium path (Termux default set below)
  CHROMEDRIVER           chromedriver path
  DUCKAI_LOG_DIR         Log directory

Disclaimer: Unofficial. Respect DuckDuckGo terms, rate limits, and privacy norms.
Do not overload the service. Not affiliated with DuckDuckGo.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
LOG_DIR = Path(os.environ.get("DUCKAI_LOG_DIR", str(HOME / "duckai_logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)

URL = "https://duck.ai/"
DEFAULT_PROMPT = os.environ.get("DUCKAI_PROMPT", "").strip()
DEFAULT_MODEL = os.environ.get("DUCKAI_MODEL", "gpt-4o-mini")
MAX_TURNS = int(os.environ.get("DUCKAI_MAX_TURNS", "3"))
TURN_DELAY = float(os.environ.get("DUCKAI_TURN_DELAY", "16"))
MODE = os.environ.get("DUCKAI_MODE", "auto").lower()
HEADLESS = os.environ.get("DUCKAI_HEADLESS", "1") not in ("0", "false", "False")

CHROME_BIN = os.environ.get(
    "CHROME_BIN",
    "/data/data/com.termux/files/usr/bin/chromium-browser",
)
CHROMEDRIVER = os.environ.get(
    "CHROMEDRIVER",
    "/data/data/com.termux/files/usr/bin/chromedriver",
)

MODEL_ALIASES = {
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4o": "gpt-4o-mini",
    "claude": "claude-3-haiku",
    "claude-3-haiku": "claude-3-haiku",
    "mistral": "mistral-small-3",
    "mistral-small-3": "mistral-small-3",
    "llama": "llama-3.3-70b",
    "o3-mini": "o3-mini",
}


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def save_text(name: str, text: str) -> None:
    try:
        (LOG_DIR / name).write_text(text, encoding="utf-8")
    except Exception as e:
        log(f"save_text failed: {e}")


def try_api_chat(prompt: str, model: str) -> str | None:
    """Return reply text or None if no API client works."""
    model = MODEL_ALIASES.get(model, model)

    try:
        from duckai import DuckAI  # type: ignore

        log(f"[api:duckai] model={model}")
        client = DuckAI()
        try:
            return client.chat(prompt, model=model)
        except TypeError:
            return client.chat(prompt)
    except Exception as e:
        log(f"[api:duckai] unavailable: {e}")

    try:
        import asyncio

        try:
            from duck_chat import DuckChat  # type: ignore
        except ImportError:
            from duckduckgo_chat_ai import DuckChat  # type: ignore

        async def _ask() -> str:
            async with DuckChat() as chat:
                return await chat.ask_question(prompt)

        log("[api:duck_chat] asking…")
        return asyncio.run(_ask())
    except Exception as e:
        log(f"[api:duck_chat] unavailable: {e}")

    return None


def build_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    opts = Options()
    if os.path.exists(CHROME_BIN):
        opts.binary_location = CHROME_BIN
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,1800")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    service = None
    if os.path.exists(CHROMEDRIVER):
        service = Service(CHROMEDRIVER)
    else:
        try:
            from webdriver_manager.chrome import ChromeDriverManager

            service = Service(ChromeDriverManager().install())
        except Exception as e:
            raise RuntimeError(
                f"No chromedriver at {CHROMEDRIVER} and webdriver-manager failed: {e}"
            )

    driver = webdriver.Chrome(service=service, options=opts)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """
            },
        )
    except Exception:
        pass
    return driver


def selenium_find_input(driver, timeout: int = 25):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    selectors = [
        "textarea",
        "textarea[placeholder]",
        "[contenteditable='true']",
        "input[type='text']",
        "[role='textbox']",
        "form textarea",
    ]
    last_err = None
    for sel in selectors:
        try:
            el = WebDriverWait(driver, timeout // len(selectors) + 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            if el.is_displayed():
                return el
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not find chat input on {URL}: {last_err}")


def selenium_send(driver, text: str) -> None:
    from selenium.webdriver.common.keys import Keys

    box = selenium_find_input(driver)
    box.click()
    try:
        box.clear()
    except Exception:
        pass
    box.send_keys(text)
    box.send_keys(Keys.ENTER)
    log(f">>> {text[:120]}{'…' if len(text) > 120 else ''}")


def selenium_wait_reply(driver, previous_len: int, timeout: int = 120) -> str:
    from selenium.webdriver.common.by import By

    deadline = time.time() + timeout
    last = ""
    stable = 0
    while time.time() < deadline:
        candidates = []
        for sel in (
            "[data-testid*='assistant']",
            "[data-testid*='message']",
            ".assistant",
            ".message",
            "article",
            "[class*='response']",
            "[class*='assistant']",
        ):
            try:
                candidates.extend(driver.find_elements(By.CSS_SELECTOR, sel))
            except Exception:
                pass
        texts = []
        for el in candidates:
            t = (el.text or "").strip()
            if t and len(t) > 2:
                texts.append(t)
        if texts:
            current = texts[-1]
        else:
            current = (driver.find_element(By.TAG_NAME, "body").text or "").strip()
            if len(current) > previous_len + 20:
                current = current[previous_len:].strip()

        if current and current != last and len(current) > 5:
            last = current
            stable = 0
        elif current and current == last:
            stable += 1
            if stable >= 3:
                return current
        time.sleep(1.2)
    if last:
        return last
    raise TimeoutError("Timed out waiting for Duck.ai reply")


def run_selenium(prompt: str, followups: list[str], model: str) -> list[tuple[str, str]]:
    from selenium.webdriver.common.by import By

    driver = build_driver()
    conversation: list[tuple[str, str]] = []
    try:
        log(f"Opening {URL}")
        driver.get(URL)
        time.sleep(4)
        try:
            driver.save_screenshot(str(LOG_DIR / "00_loaded.png"))
        except Exception:
            pass

        if model:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, "button, [role='button']"):
                    t = (el.text or "").lower()
                    if "model" in t or "gpt" in t or "claude" in t:
                        el.click()
                        time.sleep(1)
                        break
            except Exception:
                pass

        turns = [prompt] + followups
        for i, msg in enumerate(turns[:MAX_TURNS]):
            before = len((driver.find_element(By.TAG_NAME, "body").text or ""))
            selenium_send(driver, msg)
            try:
                reply = selenium_wait_reply(driver, before)
            except TimeoutError as e:
                log(str(e))
                try:
                    (LOG_DIR / f"timeout_{i}.html").write_text(
                        driver.page_source, encoding="utf-8"
                    )
                except Exception:
                    pass
                break
            conversation.append((msg, reply))
            log("<<")
            print(reply[:2000] + ("…" if len(reply) > 2000 else ""))
            try:
                driver.save_screenshot(str(LOG_DIR / f"{i:02d}_after.png"))
            except Exception:
                pass
            if i < len(turns) - 1:
                delay = TURN_DELAY + random.uniform(0, 2)
                log(f"sleep {delay:.1f}s (rate limit hygiene)")
                time.sleep(delay)
        save_text(
            "conversation.log",
            "\n\n".join(f"USER: {u}\nAI: {a}" for u, a in conversation),
        )
        return conversation
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Duck.ai chat automation (API-first)")
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT, help="First message")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL)
    parser.add_argument("--mode", choices=("auto", "api", "selenium"), default=MODE)
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    parser.add_argument(
        "-f",
        "--followup",
        action="append",
        default=[],
        help="Extra turn (repeatable)",
    )
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()

    if args.list_models:
        print("Common model ids / aliases:")
        for k, v in MODEL_ALIASES.items():
            print(f"  {k:20} -> {v}")
        print("\nInstall API client:  pip install -U duckai")
        print("Selenium fallback needs: pip install selenium")
        return 0

    prompt = (args.prompt or "").strip()
    if not prompt:
        log("No prompt. Set DUCKAI_PROMPT or pass as argument.")
        return 2

    global MAX_TURNS
    MAX_TURNS = args.max_turns
    mode = args.mode
    model = args.model

    log(f"mode={mode} model={model} max_turns={MAX_TURNS}")

    if mode in ("auto", "api"):
        reply = try_api_chat(prompt, model)
        if reply:
            print(reply)
            save_text("conversation.log", f"USER: {prompt}\n\nAI: {reply}")
            for fu in args.followup[: max(0, MAX_TURNS - 1)]:
                time.sleep(TURN_DELAY + random.uniform(0, 1))
                r2 = try_api_chat(fu, model)
                if not r2:
                    break
                print(r2)
                with open(LOG_DIR / "conversation.log", "a", encoding="utf-8") as f:
                    f.write(f"\n\nUSER: {fu}\n\nAI: {r2}")
            log("Done (API).")
            return 0
        if mode == "api":
            log("API mode failed and selenium not requested.")
            return 1
        log("Falling back to Selenium…")

    try:
        run_selenium(prompt, args.followup, model)
    except Exception as e:
        log(f"Selenium failed: {e}")
        return 1
    log("Done (Selenium).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
