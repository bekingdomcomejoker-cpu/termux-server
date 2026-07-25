# Termux Server v2.4 — "The Pool"

Distributed compute pool, stealth auth, browser automation workers, and web-based management for Termux (Android) and Linux.

## Features

If you encounter installation issues (especially on Python 3.14+), please refer to the [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) guide.


| Feature | Description |
|---------|-------------|
| **Stealth Auth** | No login page. Owner unlocks via `/pool?join=OWNER_SECRET` cookie gate. |
| **Web Terminal** | Real bash PTY for owners, sandboxed fake shell for public. |
| **File Manager** | Browse, edit, upload, delete. Owner-only write access. |
| **Compute Pool** | Register workers (shell, browser, WASM) to share inference load. |
| **Inference API** | `POST /inference` queues jobs and routes to capable workers. |
| **Duck.ai Worker** | Stealth Selenium automation that donates Duck.ai answers to the pool. |
| **Ghost Worker** | Browser-based WASM worker for silent compute donation. |
| **Federation** | Connect multiple pool instances across devices. |
| **Rate Limiting** | 10 attempts/hour on the stealth auth gate. |
| **Command Sandbox** | Blocks `rm -rf /`, fork bombs, pipe-to-shell. |
| **Token TTL** | Owner tokens expire after 24h. |

## Quick Start

```bash
mkdir -p ~/termux-server && cd ~/termux-server
bash install.sh
export OWNER_SECRET="your-very-secret-string"
export PORT=8000
python3 api_server.py
```

Stealth Auth

No login form. No admin button. Visit:

```
https://your-server/pool?join=YOUR_SECRET
```

This sets a `ghost` cookie. Revisit `/terminal` for root PTY access.

Workers

Generic Shell Worker

```bash
COORDINATOR_URL=ws://localhost:8000/ws/worker python3 worker_node.py
```

Duck.ai Browser Worker

```bash
export CHROMEDRIVER_PATH=/data/data/com.termux/files/usr/bin/chromedriver
export CHROME_BINARY=/data/data/com.termux/files/usr/bin/chromium
export COORDINATOR_URL=ws://localhost:8000/ws/worker
python3 tools/duckai_worker.py
```

Ghost Browser Worker
Open `/ghost` in a browser and click Start Ghost.

Unified AI Bot (Standalone)

```bash
python3 tools/unified_ai_bot.py "What is the meaning of life?" --platform askrain
python3 tools/unified_ai_bot.py "Explain quantum computing" --platform duckai
```

API Endpoints

Endpoint	Method	Auth	Description	
`/health`	GET	None	Server status	
`/execute`	POST	Owner	Run shell commands	
`/file/read`	POST	None	Read files	
`/file/write`	POST	Owner	Write files	
`/file/delete`	POST	Owner	Delete files	
`/file/list`	GET	None	List directory	
`/inference`	POST	None	Queue inference job	
`/inference/stream/{id}`	GET	None	SSE job status	
`/inference/jobs`	GET	None	Recent jobs	
`/pool`	GET	None	Pool dashboard / auth gate	
`/federation/peers`	GET/POST	Owner	Peer management	
`/ws/worker`	WS	None	Worker registration	
`/ws/terminal`	WS	Cookie	Interactive terminal	

Security Notes

- No authentication by default — deploy behind HTTPS reverse proxy.
- `OWNER_SECRET` is printed on server startup. Save it.
- Public `/execute` is sandboxed to safe commands only.
- File write/delete requires owner cookie.
- Rate limiting protects the stealth auth gate.

Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │     │   Browser   │     │   Termux    │
│ Ghost Worker│     │ Duck.ai Bot │     │ Shell Worker│
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────┴──────┐
                    │  Coordinator│
                    │  (api_server│
                    │   built-in) │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────┴────┐  ┌────┴────┐  ┌────┴────┐
         │  Pool   │  │Terminal │  │  Files  │
         │Dashboard│  │  (WS)   │  │ Manager │
         └─────────┘  └─────────┘  └─────────┘
```

License

MIT — use at your own risk. Browser automation may violate ToS of target sites.