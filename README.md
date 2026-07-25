# Termux Server v2.1 — Enhanced API, Web UI & Distributed GPU Support

A complete rewrite of the Termux Server with an **integrated web terminal**, **file manager**, **process monitor**, **task scheduler**, **dashboard**, and now **Distributed GPU Worker Node support**.

---

## 🚀 What's New in v2.1

| Feature | v2.0 | v2.1 |
|---------|------|------|
| Distributed Inference | ❌ None | **WebSocket Worker Node Support** via `/ws/worker` |
| Task Routing | ❌ Local only | **Route inference tasks** to any connected GPU worker |
| Worker Monitoring | ❌ None | **Live worker list** in `/info` and `/health` |

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
GET  /health          # Health + memory/disk stats + worker count
GET  /info            # Environment info + list of active workers
POST /execute         # Run shell commands
```

### Distributed Inference (v2.1)
```bash
POST /inference  {"prompt": "Hello world", "params": {}, "worker_id": "optional"}
```
Routes the inference task to a connected GPU worker node.

### Files
```bash
POST   /file/read              # Read text file
POST   /file/write             # Write text file
POST   /file/upload            # Upload binary (multipart/form-data)
GET    /file/download/{path}   # Download file
GET    /file/list/{path}       # List directory
DELETE /file/delete/{path}     # Delete file/folder
```

---

## 🛠️ Distributed GPU Workaround (The "Bitcoin Mining" Strategy)

If you don't have a GPU in the cloud, you can "borrow" one from any PC. This allows you to run large LLMs without paying for expensive cloud GPU hourly rates.

### 1. Setup the Worker Node on a PC with a GPU
Anyone with a GPU can become a worker for your Termux Server.

1.  **Install dependencies**:
    ```bash
    pip install websocket-client requests
    ```
2.  **Download `worker_node.py`** from this repository.
3.  **Configure and Run**:
    ```python
    # Edit worker_node.py and set your Termux Server URL
    SERVER_URL = "https://your-termux-server-url"
    python worker_node.py
    ```

### 2. How it Works
- The **Worker Node** connects to your Termux Server via a persistent WebSocket.
- When you call the `/inference` endpoint on your Termux Server, it "mines" the result by sending the task to the connected worker.
- The worker performs the inference on its local GPU and sends the result back to the server.

---

## 🚀 Multi-Instance Management with Coordinator

To manage multiple Termux Server instances (e.g., across different Manus Cloud Computers), a Python coordinator script is provided.

### Coordinator Script (`coordinator.py`)

```python
# (See coordinator.py in the repository for full source)
```

---

## 🔐 Optional Authentication

Set an API key to protect all endpoints:

```bash
export TERMUX_API_KEY="your-secret-key-here"
python3 api_server.py
```

---

## 🛠️ Tech Stack

- **FastAPI** — HTTP API
- **WebSocket** — Real-time terminal & Worker Node communication
- **psutil** — Process & system monitoring
- **xterm.js** — In-browser terminal emulator (CDN)

---

## 📄 License

MIT
