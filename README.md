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
