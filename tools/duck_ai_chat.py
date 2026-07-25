#!/usr/bin/env python3
"""
duck_ai_chat.py — Duck.ai automation (AskRain-style)

Duck.ai UI: must click Send (↑ / Ask). Enter alone usually does nothing.
Termux: prefer Selenium; API wheels often fail on arm64.
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

CHROME_NOISE = re.compile(
    r"(Anonymized by DuckDuckGo|Zero data retention|No AI training|"
    r"Learn more|New Chat|New Voice Chat|Settings|Get the App|"
    r"How Duck\.ai Works|Chat Suggestions|Create & Edit Images|"
    r"All chats are private|AI can make mistakes|"
    r"Duck\.ai, by DuckDuckGo|DuckDuckGo anonymizes|"
    r"Privacy Policy|Terms of Service|Free\s*\|\s*by DuckDuckGo)",
    re.I,
)


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def save_text(name: str, text: str) -> None:
    try:
        (LOG_DIR / name).write_text(text, encoding="utf-8")
    except Exception as e:
        log(f"save_text failed: {e}")


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
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

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
                "source": (
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{get: () => undefined});"
                )
            },
        )
    except Exception:
        pass
    return driver


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
    last_err = None
    end = time.time() + timeout
    while time.time() < end:
        for sel in selectors:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed() and el.is_enabled():
                        return el
            except Exception as e:
                last_err = e
        time.sleep(0.4)
    raise RuntimeError(f"Could not find chat input on {URL}: {last_err}")


def selenium_click_send(driver) -> bool:
    from selenium.webdriver.common.by import By

    candidates = []
    for sel in (
        "button[aria-label*='Send' i]",
        "button[aria-label*='Ask' i]",
        "button[type='submit']",
        "[data-testid*='send' i]",
        "[data-testid*='ask' i]",
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
    time.sleep(0.2)
    try:
        box.clear()
    except Exception:
        pass
    try:
        box.send_keys(text)
    except Exception:
        driver.execute_script(
            "const el=arguments[0],val=arguments[1]; el.focus(); el.value=val;"
            "el.dispatchEvent(new Event('input',{bubbles:true}));",
            box,
            text,
        )
    time.sleep(0.3)

    clicked = selenium_click_send(driver)
    if not clicked:
        log("send button not found; trying Enter as last resort")
        try:
            box.send_keys(Keys.ENTER)
        except Exception:
            pass
    log(f">>> {text[:120]}{'…' if len(text) > 120 else ''}")


def _clean_body(text: str, prompt: str) -> str:
    t = CHROME_NOISE.sub(" ", text)
    t = re.sub(r"\s+", " ", t).strip()
    if prompt and t.startswith(prompt):
        t = t[len(prompt) :].strip()
    return t


def selenium_wait_reply(driver, prompt: str, timeout: int = 90) -> str:
    from selenium.webdriver.common.by import By

    deadline = time.time() + timeout
    last_good = ""
    stable = 0
    prompt_l = prompt.strip().lower()

    while time.time() < deadline:
        snippets: list[str] = []

        for sel in (
            "[data-testid*='assistant']",
            "[data-testid*='message']",
            "[class*='assistant']",
            "[class*='response']",
            "article",
            "[role='article']",
            "main p",
            "main div",
        ):
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    t = (el.text or "").strip()
                    if len(t) < 8:
                        continue
                    if t.lower() == prompt_l:
                        continue
                    if CHROME_NOISE.search(t) and len(t) < 80:
                        continue
                    snippets.append(t)
            except Exception:
                pass

        body = ""
        try:
            body = driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            pass

        m = re.search(
            r"(?:GPT-[\d.]+|Claude|Mistral|Llama)[^\n]*\n+(.+?)(?:\n\s*\n|$)",
            body,
            re.S | re.I,
        )
        if m:
            candidate = CHROME_NOISE.sub(" ", m.group(1).strip())
            candidate = re.sub(r"\s+", " ", candidate).strip()
            if len(candidate) > 15 and candidate.lower() != prompt_l:
                snippets.append(candidate)

        cleaned = _clean_body(body, prompt)
        if cleaned and len(cleaned) > 20:
            snippets.append(cleaned)

        snippets = sorted(set(snippets), key=len, reverse=True)
        current = ""
        for s in snippets:
            if prompt_l and prompt_l in s.lower() and len(s) < len(prompt) + 30:
                continue
            if "New Chat" in s or s.startswith("Duck.ai"):
                continue
            current = s
            break

        if current and len(current) > 15:
            if current == last_good:
                stable += 1
                if stable >= 3:
                    return current
            else:
                last_good = current
                stable = 0
        time.sleep(1.0)

    if last_good:
        return last_good
    raise TimeoutError("Timed out waiting for Duck.ai reply (send may not have clicked)")


def run_selenium(
    prompt: str, followups: list[str], model: str, max_turns: int = MAX_TURNS
) -> list[tuple[str, str]]:
    driver = build_driver()
    conversation: list[tuple[str, str]] = []
    try:
        log(f"Opening {URL}")
        driver.get(URL)
        time.sleep(5)
        try:
            driver.save_screenshot(str(LOG_DIR / "00_loaded.png"))
        except Exception:
            pass

        turns = [prompt] + list(followups)
        for i, msg in enumerate(turns[:max_turns]):
            selenium_send(driver, msg)
            try:
                reply = selenium_wait_reply(driver, msg)
            except TimeoutError as e:
                log(str(e))
                try:
                    (LOG_DIR / f"timeout_{i}.html").write_text(
                        driver.page_source, encoding="utf-8"
                    )
                    driver.save_screenshot(str(LOG_DIR / f"timeout_{i}.png"))
                except Exception:
                    pass
                break
            conversation.append((msg, reply))
            log("<<<")
            print(reply[:3000] + ("…" if len(reply) > 3000 else ""))
            try:
                driver.save_screenshot(str(LOG_DIR / f"{i:02d}_after.png"))
            except Exception:
                pass
            if i < len(turns) - 1:
                delay = TURN_DELAY + random.uniform(0, 2)
                log(f"sleep {delay:.1f}s")
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
    parser = argparse.ArgumentParser(description="Duck.ai chat automation")
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
        print("\nTermux: use Selenium (API wheels often missing on arm64).")
        print("Duck.ai UI: must click Send (↑); Enter alone usually fails.")
        return 0

    prompt = (args.prompt or "").strip()
    if not prompt:
        log("No prompt. Pass one as argument or set DUCKAI_PROMPT.")
        return 2

    max_turns = args.max_turns
    mode = args.mode
    model = args.model
    log(f"mode={mode} model={model} max_turns={max_turns}")

    if mode in ("auto", "api"):
        reply = try_api_chat(prompt, model)
        if reply:
            print(reply)
            save_text("conversation.log", f"USER: {prompt}\n\nAI: {reply}")
            log("Done (API).")
            return 0
        if mode == "api":
            log("API failed.")
            return 1
        log("Falling back to Selenium…")

    try:
        run_selenium(prompt, args.followup, model, max_turns=max_turns)
    except Exception as e:
        log(f"Selenium failed: {e}")
        return 1
    log("Done (Selenium).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
