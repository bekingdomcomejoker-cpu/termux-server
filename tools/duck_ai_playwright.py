#!/usr/bin/env python3
"""
duck_ai_playwright.py — Duck.ai via Playwright + system Chromium (Termux-friendly)

Must click Send (↑); Enter alone usually fails.
Set PLAYWRIGHT_BROWSERS_PATH=0 and pass executable_path to Termux chromium.
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
MAX_TURNS = int(os.environ.get("DUCKAI_MAX_TURNS", "3"))
TURN_DELAY = float(os.environ.get("DUCKAI_TURN_DELAY", "16"))
HEADLESS = os.environ.get("DUCKAI_HEADLESS", "1") not in ("0", "false", "False")

CHROME_BIN = os.environ.get(
    "CHROME_BIN",
    os.environ.get(
        "CHROMIUM_PATH",
        "/data/data/com.termux/files/usr/bin/chromium-browser",
    ),
)

CHROME_NOISE = re.compile(
    r"(Anonymized by DuckDuckGo|Zero data retention|No AI training|"
    r"Learn more|New Chat|New Voice Chat|Settings|Get the App|"
    r"How Duck\.ai Works|Chat Suggestions|Create & Edit Images|"
    r"All chats are private|AI can make mistakes|"
    r"Duck\.ai, by DuckDuckGo|DuckDuckGo anonymizes|"
    r"Privacy Policy|Terms of Service)",
    re.I,
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def launch_browser(p):
    kwargs = {
        "headless": HEADLESS,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-setuid-sandbox",
        ],
    }
    if CHROME_BIN and os.path.exists(CHROME_BIN):
        kwargs["executable_path"] = CHROME_BIN
        log(f"using system chromium: {CHROME_BIN}")
    else:
        log("CHROME_BIN missing — trying Playwright bundled chromium")
    return p.chromium.launch(**kwargs)


def find_input(page):
    for sel in (
        "textarea[placeholder*='Reply' i]",
        "textarea[placeholder*='Ask' i]",
        "textarea",
        "[contenteditable='true']",
        "[role='textbox']",
    ):
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    raise RuntimeError("chat input not found")


def click_send(page) -> None:
    for pattern in (r"send", r"ask", r"submit"):
        loc = page.get_by_role("button", name=re.compile(pattern, re.I))
        try:
            if loc.count():
                loc.first.click(timeout=3000)
                log(f"clicked send (role name ~ {pattern})")
                return
        except Exception:
            continue
    for sel in (
        "button[aria-label*='Send' i]",
        "button[aria-label*='Ask' i]",
        "button[type='submit']",
    ):
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=3000)
                log(f"clicked send ({sel})")
                return
        except Exception:
            continue
    buttons = page.locator("button:visible")
    n = buttons.count()
    if n:
        buttons.nth(n - 1).click(timeout=3000)
        log("clicked last visible button as send")
        return
    raise RuntimeError("send button not found")


def extract_reply(page, prompt: str) -> str:
    body = page.inner_text("body")
    prompt_l = prompt.strip().lower()
    m = re.search(
        r"(?:GPT-[\d.]+|Claude|Mistral|Llama)[^\n]*\n+(.+?)(?:\n\s*\n|$)",
        body,
        re.S | re.I,
    )
    if m:
        cand = CHROME_NOISE.sub(" ", m.group(1))
        cand = re.sub(r"\s+", " ", cand).strip()
        if len(cand) > 15 and cand.lower() != prompt_l:
            return cand
    cleaned = CHROME_NOISE.sub(" ", body)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if prompt and cleaned.lower().startswith(prompt_l):
        cleaned = cleaned[len(prompt) :].strip()
    for bad in ("New Chat", "Duck.ai", "Reply..."):
        if cleaned.startswith(bad):
            cleaned = cleaned[len(bad) :].strip()
    return cleaned


def wait_reply(page, prompt: str, timeout_ms: int = 90_000) -> str:
    deadline = time.time() + timeout_ms / 1000
    last = ""
    stable = 0
    while time.time() < deadline:
        try:
            page.get_by_text(re.compile(r"GPT-|Claude|Mistral|Llama")).first.wait_for(
                timeout=2000, state="visible"
            )
        except Exception:
            pass
        text = extract_reply(page, prompt)
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
    raise TimeoutError("no Duck.ai reply (send may have failed)")


def run(prompt: str, followups: list[str], max_turns: int) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("pip install playwright")
        return 1

    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

    conversation: list[tuple[str, str]] = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        context = browser.new_context(
            viewport={"width": 420, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            ),
        )
        page = context.new_page()
        log(f"Opening {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(3)
        try:
            page.screenshot(path=str(LOG_DIR / "00_loaded.png"))
        except Exception:
            pass

        turns = [prompt] + list(followups)
        for i, msg in enumerate(turns[:max_turns]):
            box = find_input(page)
            box.click()
            box.fill(msg)
            time.sleep(0.3)
            click_send(page)
            log(f">>> {msg[:120]}")
            try:
                reply = wait_reply(page, msg)
            except TimeoutError as e:
                log(str(e))
                try:
                    page.screenshot(path=str(LOG_DIR / f"timeout_{i}.png"))
                    (LOG_DIR / f"timeout_{i}.html").write_text(
                        page.content(), encoding="utf-8"
                    )
                except Exception:
                    pass
                break
            conversation.append((msg, reply))
            log("<<<")
            print(reply[:3000] + ("…" if len(reply) > 3000 else ""))
            try:
                page.screenshot(path=str(LOG_DIR / f"{i:02d}_after.png"))
            except Exception:
                pass
            if i < len(turns) - 1:
                d = TURN_DELAY + random.uniform(0, 2)
                log(f"sleep {d:.1f}s")
                time.sleep(d)

        browser.close()

    if conversation:
        (LOG_DIR / "conversation.log").write_text(
            "\n\n".join(f"USER: {u}\nAI: {a}" for u, a in conversation),
            encoding="utf-8",
        )
    return 0 if conversation else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Duck.ai via Playwright")
    ap.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT)
    ap.add_argument("--max-turns", type=int, default=MAX_TURNS)
    ap.add_argument("-f", "--followup", action="append", default=[])
    args = ap.parse_args()
    prompt = (args.prompt or "").strip()
    if not prompt:
        log("Pass a prompt or set DUCKAI_PROMPT")
        return 2
    log(f"playwright headless={HEADLESS} chrome={CHROME_BIN}")
    return run(prompt, args.followup, args.max_turns)


if __name__ == "__main__":
    sys.exit(main())
