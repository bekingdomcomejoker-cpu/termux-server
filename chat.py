#!/usr/bin/env python3
import os
import time
import sys

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

URL = "https://askrain.rain.co.za/?id=7yAzKgvD7I6wVGEHMrQazaYjlhAILGXzjTzvAx8nVWk%3D"

CHROME_BINARY = os.environ.get("CHROME_BINARY", "/data/data/com.termux/files/usr/bin/chromium-browser")
CHROMEDRIVER_PATH = os.environ.get("CHROMEDRIVER_PATH", "/data/data/com.termux/files/usr/bin/chromedriver")

opts = Options()
opts.binary_location = CHROME_BINARY
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--window-size=1400,2200")

driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=opts)

def shadow():
    host = driver.find_element(By.TAG_NAME, "ai-chat-bot")
    return driver.execute_script("return arguments[0].shadowRoot", host)

def textarea():
    root = shadow()
    return driver.execute_script("return arguments[0].querySelector('textarea')", root)

def dump_messages():
    root = shadow()
    return driver.execute_script("""
const msgs = [];
arguments[0].querySelectorAll(".user-query, .ai-response").forEach(e => {
    let txt = (e.innerText || e.textContent || "").trim();
    if (!txt) {
        const p = e.querySelector("p");
        if (p) txt = (p.innerText || p.textContent || "").trim();
    }
    if (!txt) txt = e.innerHTML;
    msgs.push(txt);
});
return msgs;
""", root)

def wait_for_reply(timeout=60):
    last_text = None
    stable = 0
    msgs = []
    for _ in range(timeout):
        time.sleep(1)
        msgs = dump_messages()
        if not msgs:
            continue
        current = msgs[-1]
        t = current.strip().lower()
        if (not t) or ("loader" in t):
            last_text = None
            stable = 0
            continue
        if current == last_text:
            stable += 1
            if stable >= 3:
                break
        else:
            last_text = current
            stable = 0
    return msgs[-1] if msgs else ""

def send_message(text):
    box = textarea()
    box.click()
    box.send_keys(text)
    box.send_keys(Keys.ENTER)
    print(f"\n>>> {text}")

print("=" * 50)
print("  Termux AI Chat — AskRain (Rain ISP)")
print("  Type /quit or /exit to close")
print("=" * 50)
print("[*] Loading AskRain...")
driver.get(URL)
time.sleep(5)
print("[+] Ready.\n")

while True:
    try:
        user_input = input("You: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if user_input in ("/quit", "/exit"):
        break
    if not user_input:
        continue
    send_message(user_input)
    print("[*] Thinking...")
    reply = wait_for_reply()
    print(f"<<< {reply}")

driver.quit()
print("\n[*] Session ended.")
