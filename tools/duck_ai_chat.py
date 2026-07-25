#!/usr/bin/env python3
"""
duck_ai_chat.py
HTTP-client based Duck.ai chat (no browser automation).
Uses DuckDuckGo's API endpoints directly. May be rate-limited.
"""

import argparse
import json
import logging
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("duck_ai_chat")

BASE_URL = "https://duckduckgo.com/duckchat/v1"


def get_vqd() -> str:
    """Fetch the VQD token required for chat sessions."""
    req = urllib.request.Request(
        "https://duckduckgo.com/duckchat/v1/status",
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "*/*",
            "x-vqd-accept": "1"
        }
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        headers = dict(resp.headers)
        vqd = headers.get("x-vqd-4") or headers.get("X-Vqd-4")
        if not vqd:
            body = resp.read().decode("utf-8")
            m = re.search(r'"vqd"\s*:\s*"([^"]+)"', body)
            if m:
                vqd = m.group(1)
        if not vqd:
            raise RuntimeError("Could not extract VQD token")
        return vqd


def chat(prompt: str, model: str = "gpt-4o-mini", vqd: str = None) -> str:
    if not vqd:
        vqd = get_vqd()

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{BASE_URL}/chat",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "x-vqd-4": vqd,
            "Accept": "text/event-stream"
        },
        method="POST"
    )

    response_text = ""
    with urllib.request.urlopen(req, timeout=60) as resp:
        for line in resp:
            line = line.decode("utf-8").strip()
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    if "message" in obj:
                        response_text += obj["message"]
                except json.JSONDecodeError:
                    pass

    return response_text


def main():
    parser = argparse.ArgumentParser(description="Duck.ai chat via HTTP API")
    parser.add_argument("prompt", help="Message to send")
    parser.add_argument("--model", default="gpt-4o-mini", choices=["gpt-4o-mini", "claude-3-haiku", "llama-3.1-70b", "mixtral-8x7b"])
    parser.add_argument("--vqd", default=None, help="Pre-fetched VQD token")
    args = parser.parse_args()

    try:
        result = chat(args.prompt, model=args.model, vqd=args.vqd)
        print(json.dumps({"success": True, "response": result}, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()