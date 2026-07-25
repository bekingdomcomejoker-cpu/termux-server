# Termux Server v2.0 — Enhanced API & Web UI

A complete rewrite of the Termux Server with an **integrated web terminal**, **file manager**, **process monitor**, **task scheduler**, and **dashboard** — all served from a single FastAPI process on port 8000. No more `ttyd` dependency.

---

## 🚀 What's New

| Feature | v1.0 | v2.0 |
|---------|------|------|
| Web Terminal | External `ttyd` (broken on proxy) | **Built-in WebSocket terminal** via `/ws/terminal` |
| File Upload | ❌ Not supported | **Multipart upload** via `/file/upload` |
| File Download | ❌ Not supported | **Direct download** via `/file/download/{path}` |
| File Manager UI | ❌ None | **Full web UI** at `/files` |
| Process Monitor | ❌ None | **List & kill** via `/processes` |
| Task Scheduler | ❌ None | **Cron-like jobs** via `/schedule` |
| System Dashboard | ❌ None | **Live stats** at `/` |
| Auth | ❌ None | **Optional API key** via `TERMUX_API_KEY` env |

---

## 📦 Quick Install

Copy the install script to your server and run it:

```bash
# Option 1: Download and run
curl -fsSL <install.sh-url> | bash

# Option 2: Manual copy
cat > /tmp/install.sh <<'EOF'
[paste install.sh contents here]
EOF
bash /tmp/install.sh
```

Then start:
```bash
cd /home/ubuntu/termux-server
nohup python3 api_server.py > var/log/api.log 2>&1 &
```

---

## 🌐 Web Interfaces

All served from **port 8000** (same as the API):

| URL | What It Is |
|-----|-----------|
| `/` | **Dashboard** — system stats, quick command tester, endpoint docs |
| `/terminal` | **Web Terminal** — full xterm.js bash shell via WebSocket |
| `/files` | **File Manager** — browse, upload, download, edit, delete files |

---

## 🔌 API Endpoints

### Core
```bash
GET  /health          # Health + memory/disk stats
GET  /info            # Environment info
POST /execute         # Run shell commands
```

### Files
```bash
POST   /file/read              # Read text file
POST   /file/write             # Write text file
POST   /file/upload            # Upload binary (multipart/form-data)
GET    /file/download/{path}   # Download file
GET    /file/list/{path}       # List directory
DELETE /file/delete/{path}     # Delete file/folder
```

### Packages
```bash
POST /package  {"action":"install|remove|update|list", "package":"git"}
```

### Processes
```bash
GET    /processes              # List all processes
POST   /processes/kill/{pid}   # Terminate by PID
```

### Scheduled Tasks (requires APScheduler)
```bash
POST   /schedule               # Create cron job
GET    /schedule               # List jobs
DELETE /schedule/{job_id}      # Remove job
```

**Example:** Run a backup every 5 minutes
```bash
curl -X POST https://your-host/schedule \
  -H "Content-Type: application/json" \
  -d '{"name":"backup","command":"tar czf backup.tar.gz home/","cron":"*/5 * * * *"}'
```

### WebSocket Terminal
```
WS /ws/terminal
```
Connects to a real PTY bash session. Supports resize, colors, and all interactive programs (`vim`, `htop`, etc.).

---

## 🚀 Multi-Instance Management with Coordinator

To manage multiple Termux Server instances (e.g., across different Manus Cloud Computers), a Python coordinator script is provided. This script allows you to send commands and retrieve information from multiple instances simultaneously or selectively.

### Coordinator Script (`coordinator.py`)

```python
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
```

### How to use it

1.  **Save the script**: Ensure `coordinator.py` is in your working directory.
2.  **Install dependencies**: `pip install requests`
3.  **Run**: `python coordinator.py`

You can also import the functions into any other Python script or Manus skill:

```python
from coordinator import execute, health

# send the same command to both
execute("echo hello from both")

# send only to the new one
execute("apt list --installed | head", targets=["second"])
```

---

## 🔐 Optional Authentication

Set an API key to protect all endpoints:

```bash
export TERMUX_API_KEY="your-secret-key-here"
python3 api_server.py
```

Then include it in requests:
```bash
curl -H "X-API-Key: your-secret-key-here" https://your-host/health
```

---

## 🛠️ Tech Stack

- **FastAPI** — HTTP API
- **WebSocket** — Real-time terminal (PTY + xterm.js)
- **psutil** — Process & system monitoring
- **APScheduler** — Cron-like task scheduling (optional)
- **xterm.js** — In-browser terminal emulator (CDN)

---

## 📝 Changelog from v1.0

- Replaced broken `ttyd` with native WebSocket PTY terminal
- Added file upload/download/delete/list endpoints
- Added web-based file manager with inline text editor
- Added process list and kill endpoints
- Added cron-style task scheduler
- Added system dashboard with live stats
- Added optional API key authentication
- Consolidated everything into a single Python file

---

## 📄 License

MIT
