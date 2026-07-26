#!/usr/bin/env python3
"""
duck_ai_chat.py — Duck.ai automation (Termux / Selenium)

- Clicks Send (↑); Enter alone usually fails
- Detects DuckDuckGo bot challenge and exits cleanly (no CAPTCHA solve)
- Prefer system Chromium + chromedriver on Termux

Env:
  DUCKAI_PROMPT, DUCKAI_MODEL, DUCKAI_MAX_TURNS, DUCKAI_TURN_DELAY
  DUCKAI_MODE=auto|api|selenium   DUCKAI_HEADLESS=1|0
  CHROME_BIN, CHROMEDRIVER, DUCKAI_LOG_DIR
"""

from __future__ import annotations

import argparse
import os
import random
import re
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

CHALLENGE_RE = re.compile(
    r"(bots use DuckDuckGo|Select all squares containing a duck|"
    r"complete the following challenge|confirm this prompt was made by a human|"
    r"Unfortunately, bots use)",
    re.I,
)

CHROME_NOISE = re.compile(
    r"(Anonymized by DuckDuckGo|Zero data retention|No AI training|"
    r"Learn more|New Chat|New Voice Chat|Settings|Get the App|"
    r"How Duck\.ai Works|Chat Suggestions|Create & Edit Images|"
    r"All chats are private|AI can make mistakes|"
    r"Duck\.ai, by DuckDuckGo|DuckDuckGo anonymizes|"
    r"Privacy Policy|Terms of Service|Your recent chats live here|"
    r"Got It!|How It Works|Generating response|"
    r"Duck\.ai works best in our private)",
    re.I,
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def save_text(name: str, text: str) -> None:
    try:
        (LOG_DIR / name).write_text(text, encoding="utf-8")
    except Exception as e:
        log(f"save_text failed: {e}")


def is_challenge(text: str) -> bool:
    return bool(text and CHALLENGE_RE.search(text))


def try_api_chat(prompt: str, model: str) -> str | None:
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

    for mod in ("duckduckgo_search", "ddgs"):
        try:
            m = __import__(mod, fromlist=["DDGS"])
            DDGS = m.DDGS
            log(f"[api:{mod}] trying chat…")
            with DDGS() as ddgs:
                if hasattr(ddgs, "chat"):
                    return ddgs.chat(prompt, model=model)
        except Exception as e:
            log(f"[api:{mod}] unavailable: {e}")
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
    opts.add_argument("--window-size=420,900")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    if os.path.exists(CHROMEDRIVER):
        service = Service(CHROMEDRIVER)
    else:
        service = Service()
        log(f"chromedriver not at {CHROMEDRIVER}; trying Selenium Manager")

    driver = webdriver.Chrome(service=service, options=opts)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{get: () => undefined});"
                )
            },
        )
    except Exception:
        pass
    return driver


def page_text(driver) -> str:
    from selenium.webdriver.common.by import By

    try:
        return driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return ""


def dump_failure(driver, tag: str) -> None:
    try:
        driver.save_screenshot(str(LOG_DIR / f"{tag}.png"))
    except Exception:
        pass
    try:
        (LOG_DIR / f"{tag}.html").write_text(driver.page_source, encoding="utf-8")
    except Exception:
        pass
    try:
        save_text(f"{tag}.txt", page_text(driver))
    except Exception:
        pass


def selenium_find_input(driver, timeout: int = 30):
    from selenium.webdriver.common.by import By

    selectors = [
        "textarea[placeholder*='Reply']",
        "textarea[placeholder*='Ask']",
        "textarea",
        "[contenteditable='true']",
        "[role='textbox']",
        "input[type='text']",
    ]
    end = time.time() + timeout
    while time.time() < end:
        body = page_text(driver)
        if is_challenge(body):
            raise RuntimeError("BOT_CHALLENGE")
        for sel in selectors:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed() and el.is_enabled():
                        return el
            except Exception:
                pass
        time.sleep(0.4)
    raise RuntimeError("chat input not found")


def selenium_click_send(driver) -> bool:
    from selenium.webdriver.common.by import By

    candidates = []
    for sel in (
        "button[aria-label*='Send' i]",
        "button[aria-label*='Ask' i]",
        "button[type='submit']",
        "[data-testid*='send' i]",
        "button",
    ):
        try:
            candidates.extend(driver.find_elements(By.CSS_SELECTOR, sel))
        except Exception:
            pass

    scored = []
    for el in candidates:
        try:
            if not el.is_displayed() or not el.is_enabled():
                continue
            label = " ".join(
                filter(
                    None,
                    [
                        el.get_attribute("aria-label") or "",
                        el.get_attribute("title") or "",
                        el.text or "",
                        el.get_attribute("class") or "",
                    ],
                )
            ).lower()
            score = 0
            if any(k in label for k in ("send", "ask", "submit")):
                score += 5
            if "arrow" in label:
                score += 3
            scored.append((score, el))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    for score, el in scored:
        if score >= 3:
            try:
                el.click()
                log(f"clicked send control (score={score})")
                return True
            except Exception:
                try:
                    driver.execute_script("arguments[0].click();", el)
                    log("clicked send via JS")
                    return True
                except Exception:
                    continue

    try:
        buttons = [
            b for b in driver.find_elements(By.CSS_SELECTOR, "button") if b.is_displayed()
        ]
        if buttons:
            driver.execute_script("arguments[0].click();", buttons[-1])
            log("clicked last visible button as send fallback")
            return True
    except Exception:
        pass
    return False


def selenium_send(driver, text: str) -> None:
    from selenium.webdriver.common.keys import Keys

    box = selenium_find_input(driver)
    box.click()
    time.sleep(0.25 + random.uniform(0, 0.3))
    try:
        box.clear()
    except Exception:
        pass
    try:
        for ch in text:
            box.send_keys(ch)
            time.sleep(random.uniform(0.02, 0.08))
    except Exception:
        driver.execute_script(
            "const el=arguments[0],val=arguments[1]; el.focus(); el.value=val;"
            "el.dispatchEvent(new Event('input',{bubbles:true}));",
            box,
            text,
        )
    time.sleep(0.4 + random.uniform(0, 0.4))
    if not selenium_click_send(driver):
        log("send button not found; trying Enter as last resort")
        try:
            box.send_keys(Keys.ENTER)
        except Exception:
            pass
    log(f">>> {text[:120]}{'…' if len(text) > 120 else ''}")


def extract_reply(body: str, prompt: str) -> str:
    if is_challenge(body):
        return ""
    prompt_l = prompt.strip().lower()
    m = re.search(
        r"(?:GPT-[\d.]+|Claude|Mistral|Llama)[^\n]*\n+(.+?)(?:\n\s*\n|$)",
        body,
        re.S | re.I,
    )
    if m:
        cand = CHROME_NOISE.sub(" ", m.group(1))
        cand = re.sub(r"\s+", " ", cand).strip()
        if len(cand) > 15 and cand.lower() != prompt_l and not is_challenge(cand):
            return cand
    cleaned = CHROME_NOISE.sub(" ", body)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if prompt and cleaned.lower().startswith(prompt_l):
        cleaned = cleaned[len(prompt) :].strip()
    if is_challenge(cleaned):
        return ""
    return cleaned


def selenium_wait_reply(driver, prompt: str, timeout: int = 90) -> str:
    deadline = time.time() + timeout
    last = ""
    stable = 0
    while time.time() < deadline:
        body = page_text(driver)
        if is_challenge(body):
            dump_failure(driver, "challenge")
            raise RuntimeError("BOT_CHALLENGE")
        text = extract_reply(body, prompt)
        if text and len(text) > 20 and "New Chat" not in text[:30]:
            if text == last:
                stable += 1
                if stable >= 3:
                    return text
            else:
                last = text
                stable = 0
        time.sleep(1.0)
    if last:
        return last
    dump_failure(driver, "timeout")
    raise TimeoutError("no Duck.ai reply (timeout or blocked)")


def run_selenium(
    prompt: str, followups: list[str], model: str, max_turns: int = MAX_TURNS
) -> int:
    driver = build_driver()
    conversation: list[tuple[str, str]] = []
    try:
        log(f"Opening {URL} (headless={HEADLESS})")
        driver.get(URL)
        time.sleep(4 + random.uniform(0, 2))
        body0 = page_text(driver)
        if is_challenge(body0):
            dump_failure(driver, "challenge_on_load")
            log("BLOCKED: DuckDuckGo bot challenge on page load.")
            log("Use a normal phone browser for duck.ai, or try later.")
            return 3
        try:
            driver.save_screenshot(str(LOG_DIR / "00_loaded.png"))
        except Exception:
            pass

        turns = [prompt] + list(followups)
        for i, msg in enumerate(turns[:max_turns]):
            try:
                selenium_send(driver, msg)
                reply = selenium_wait_reply(driver, msg)
            except RuntimeError as e:
                if "BOT_CHALLENGE" in str(e):
                    log("BLOCKED: DuckDuckGo bot challenge after send.")
                    log("Screenshot/HTML saved under ~/duckai_logs/")
                    log("Automation cannot complete the duck CAPTCHA.")
                    return 3
                raise
            except TimeoutError as e:
                log(str(e))
                return 1
            conversation.append((msg, reply))
            log("<<<")
            print(reply[:3000] + ("…" if len(reply) > 3000 else ""))
            try:
                driver.save_screenshot(str(LOG_DIR / f"{i:02d}_after.png"))
            except Exception:
                pass
            if i < len(turns) - 1:
                d = TURN_DELAY + random.uniform(0, 2)
                log(f"sleep {d:.1f}s")
                time.sleep(d)

        if conversation:
            save_text(
                "conversation.log",
                "\n\n".join(f"USER: {u}\nAI: {a}" for u, a in conversation),
            )
        return 0 if conversation else 1
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Duck.ai chat (Selenium/API)")
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT)
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL)
    parser.add_argument("--mode", choices=("auto", "api", "selenium"), default=MODE)
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    parser.add_argument("-f", "--followup", action="append", default=[])
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()

    if args.list_models:
        for k, v in MODEL_ALIASES.items():
            print(f"  {k:20} -> {v}")
        print("\nTermux: Selenium + system Chromium.")
        print("If you see a duck CAPTCHA, use a normal browser — not automation.")
        return 0

    prompt = (args.prompt or "").strip()
    if not prompt:
        log("Pass a prompt argument or set DUCKAI_PROMPT")
        return 2

    max_turns = args.max_turns
    mode = args.mode
    model = args.model
    log(f"mode={mode} model={model} max_turns={max_turns}")

    if mode in ("auto", "api"):
        reply = try_api_chat(prompt, model)
        if reply:
            if is_challenge(reply):
                log("API returned challenge-like text; treating as blocked")
                return 3
            print(reply)
            save_text("conversation.log", f"USER: {prompt}\n\nAI: {reply}")
            log("Done (API).")
            return 0
        if mode == "api":
            log("API failed.")
            return 1
        log("Falling back to Selenium…")

    try:
        return run_selenium(prompt, args.followup, model, max_turns=max_turns)
    except Exception as e:
        log(f"Selenium failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
