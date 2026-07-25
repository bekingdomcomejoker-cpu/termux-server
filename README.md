# Termux Server v2.3 — "The Pool"

A stealth-secured, distributed compute pool built on Termux Server.

**Public sees:** A compute pool anyone can join, donate cycles to, and run inference through.  
**Owner sees:** Full root shell, file manager, process control, and scheduling — unlocked via a secret cookie gate.

---

## 🎯 The Stealth Auth Model

No login page. No "Admin Panel" button. No obvious auth flow.

| Path | Public | Owner (ghost cookie) |
|------|--------|----------------------|
| `/` | Pool dashboard | Pool dashboard |
| `/terminal` | Fake shell (safe commands only) | Real bash PTY |
| `/files` | Browse & download only | Upload, edit, delete, create |
| `/execute` | `404 Not Found` | Full shell execution |
| `/processes` | `404 Not Found` | Process list & kill |
| `/schedule` | `404 Not Found` | Cron job scheduler |
| `/package` | `404 Not Found` | apt-get install/remove |

**How to become owner:**
```
GET /pool?join=<OWNER_SECRET>
```
This sets an HttpOnly `ghost` cookie and redirects you home. The secret is printed to server logs on first start (or set via `OWNER_SEED` env var).

---

## 🚀 Quick Start

```bash
git clone https://github.com/bekingdomcomejoker-cpu/termux-server.git
cd termux-server
bash install.sh
nohup python3 api_server.py > var/log/api.log 2>&1 &
```

**Check logs for your owner secret:**
```bash
tail -f /home/ubuntu/termux-server/var/log/api.log
```

---

## 🌐 Web Interfaces

| URL | Access |
|-----|--------|
| `/` | Pool dashboard — stats, inference playground, API docs |
| `/terminal` | Terminal (fake for public, real PTY for owner) |
| `/files` | File manager (read-only public, full control for owner) |

---

## 🔌 API Endpoints

### Public (Pool)
```
GET  /health              # Pool health + worker count
GET  /info                # Environment info
GET  /pool?join=<secret>  # Become owner (sets ghost cookie)
GET  /auth/check          # Returns {"owner": true/false}
POST /inference           # Submit LLM prompt to worker pool
WS   /ws/terminal         # Terminal (fake shell or real PTY)
WS   /ws/worker           # Worker node registration
```

### Owner-Only (404 to public)
```
POST /execute             # Shell commands
POST /file/write          # Write files
POST /file/upload         # Upload files
DELETE /file/delete/{path}
POST /package             # apt-get
GET  /processes           # List processes
POST /processes/kill/{pid}
POST /schedule            # Create cron jobs
GET  /schedule            # List jobs
DELETE /schedule/{job_id}
```

---

## 🧠 Inference Playground

Anyone can POST to `/inference`:
```bash
curl -X POST https://your-host/inference \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain quantum physics", "prefer_gpu": true}'
```

The server routes the job to an available worker node. If no workers are connected, it queues until one appears.

---

## 💻 Donate Compute (Worker Node)

Run `worker_node.py` on any device (PC, old phone, laptop, tablet):

```bash
export POOL_SERVER="wss://your-host/ws/worker"
export GGUF_MODEL="/path/to/model.gguf"  # optional
python3 worker_node.py
```

The worker connects via WebSocket, receives inference jobs, runs them locally, and returns results.

---

## 🔐 Security Notes

- `OWNER_SECRET` is auto-generated on first start and logged. Set `OWNER_SEED` env var to fix it.
- Public endpoints return `404` (not `403`) for owner-only routes to avoid leaking admin existence.
- The fake shell in `/ws/terminal` for public users is completely sandboxed — it runs no system commands.
- File read/list/download are public (useful for sharing pool artifacts). Write/delete are owner-only.

---

## 📄 License

MIT
