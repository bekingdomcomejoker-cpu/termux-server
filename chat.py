#!/usr/bin/env python3
"""
chat.py — Interactive AI chat CLI for Termux
Stays open. Type freely. Sends to Duck.ai via Selenium. Prints response.
"""

import os
import sys
import readline

# Import our bot from the tools folder
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
from unified_ai_bot import DuckAIBot, BotConfig

print("=" * 50)
print("  Termux AI Chat — Duck.ai")
print("  Type your message and hit Enter")
print("  Commands: /quit, /exit, /model, /clear")
print("=" * 50)

config = BotConfig(
    headless=True,
    stealth=True,
    screenshot_on_fail=True,
    chromedriver_path=os.environ.get("CHROMEDRIVER_PATH"),
    binary_location=os.environ.get("CHROME_BINARY"),
)

bot = DuckAIBot(config)

# Optional: start browser once and reuse it
print("[*] Starting browser (this takes a few seconds)...")
try:
    bot.start()
    print("[+] Browser ready.\n")
except Exception as e:
    print(f"[!] Failed to start browser: {e}")
    sys.exit(1)

while True:
    try:
        user_input = input("You: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[*] Exiting.")
        break

    if not user_input:
        continue

    if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
        print("[*] Closing browser...")
        break

    if user_input.lower() == "/clear":
        os.system("clear")
        continue

    print("[*] Thinking...")
    try:
        response = bot.send_message(user_input)
        print(f"AI: {response}\n")
    except Exception as e:
        print(f"[!] Error: {e}\n")
        # Reset browser on failure
        try:
            bot.stop()
            bot.start()
        except Exception:
            pass

bot.stop()
print("[*] Done.")
