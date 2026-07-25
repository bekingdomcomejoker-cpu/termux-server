#!/usr/bin/env python3
"""
Minimal Termux Server Coordinator
Talks to two (or more) Termux Server instances.
"""

import requests
import json
from typing import List, Dict, Any, Optional

# ── Configure your instances here ──────────────────────────────
INSTANCES = {
    "original": "https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer",
    "second":   "https://8000-i0nugvn3w77z3rlgv7bzk-5ae40618.us1.manus.computer",
}

# Optional API key (leave None if you didn't set TERMUX_API_KEY)
API_KEY = None
# ───────────────────────────────────────────────────────────────

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY


def call(instance: str, method: str, path: str, **kwargs) -> Dict[str, Any]:
    """Call a single instance."""
    base = INSTANCES[instance].rstrip("/")
    url = f"{base}{path}"
    try:
        if method.upper() == "GET":
            r = requests.get(url, headers=HEADERS, timeout=30, **kwargs)
        elif method.upper() == "POST":
            r = requests.post(url, headers=HEADERS, timeout=30, **kwargs)
        elif method.upper() == "DELETE":
            r = requests.delete(url, headers=HEADERS, timeout=30, **kwargs)
        else:
            return {"success": False, "error": f"Unsupported method {method}"}
        return r.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute(command: str, targets: Optional[List[str]] = None, timeout: int = 30) -> Dict[str, Any]:
    """
    Run a command on one or more instances.
    targets = None  → all instances
    targets = ["second"] → only that one
    """
    if targets is None:
        targets = list(INSTANCES.keys())

    results = {}
    for name in targets:
        results[name] = call(name, "POST", "/execute",
                             json={"command": command, "timeout": timeout})
    return results


def health(targets: Optional[List[str]] = None) -> Dict[str, Any]:
    if targets is None:
        targets = list(INSTANCES.keys())
    return {name: call(name, "GET", "/health") for name in targets}


def info(targets: Optional[List[str]] = None) -> Dict[str, Any]:
    if targets is None:
        targets = list(INSTANCES.keys())
    return {name: call(name, "GET", "/info") for name in targets}


# ── Example usage ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Health check (both) ===")
    print(json.dumps(health(), indent=2))

    print("\n=== Run command on both ===")
    print(json.dumps(execute("whoami && hostname && uptime"), indent=2))

    print("\n=== Run only on the second instance ===")
    print(json.dumps(execute("df -h | head -5", targets=["second"]), indent=2))
