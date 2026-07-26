#!/usr/bin/env python3
"""
api_server.py — Termux Server v2.4 "The Pool"
FastAPI server with stealth auth, distributed compute pool,
inference API, file manager, web terminal, and federation.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("termux-server")

# ── Configuration ──
TERMUX_HOME = os.environ.get("TERMUX_HOME", os.path.expanduser("~"))
API_KEY = os.environ.get("TERMUX_API_KEY")
OWNER_SECRET = os.environ.get("OWNER_SECRET", secrets.token_urlsafe(32))
PORT = int(os.environ.get("PORT", 8000))
RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_MAX", 10))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", 3600))
TOKEN_TTL = int(os.environ.get("TOKEN_TTL", 86400))

logger.info(f"OWNER_SECRET (save this): {OWNER_SECRET}")

# ── Database ──
DB_DIR = os.path.join(TERMUX_HOME, ".termux_server")
DB_PATH = os.path.join(DB_DIR, "server.db")
os.makedirs(DB_DIR, exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            prompt TEXT,
            status TEXT DEFAULT 'queued',
            response TEXT,
            worker_id TEXT,
            created_at REAL,
            completed_at REAL,
            model TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            created_at REAL,
            expires_at REAL,
            type TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            key TEXT PRIMARY KEY,
            count INTEGER,
            window_start REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS federation_peers (
            url TEXT PRIMARY KEY,
            added_at REAL,
            last_seen REAL,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def db_exec(query: str, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    if fetch:
        result = c.fetchall()
    else:
        result = None
    conn.commit()
    conn.close()
    return result


# ── Rate Limiter ──
class RateLimiter:
    def __init__(self, max_req: int = RATE_LIMIT_MAX, window: int = RATE_LIMIT_WINDOW):
        self.max_req = max_req
        self.window = window

    def check(self, key: str) -> bool:
        now = time.time()
        row = db_exec("SELECT count, window_start FROM rate_limits WHERE key = ?", (key,), fetch=True)
        if not row:
            db_exec("INSERT INTO rate_limits VALUES (?, 1, ?)", (key, now))
            return True
        count, window_start = row[0]
        if now - window_start > self.window:
            db_exec("UPDATE rate_limits SET count = 1, window_start = ? WHERE key = ?", (now, key))
            return True
        if count >= self.max_req:
            return False
        db_exec("UPDATE rate_limits SET count = count + 1 WHERE key = ?", (key,))
        return True


rate_limiter = RateLimiter()

# ── Auth ──
def is_owner(request: Request) -> bool:
    token = request.cookies.get("ghost")
    if not token:
        return False
    row = db_exec(
        "SELECT expires_at FROM tokens WHERE token = ? AND type = 'owner'",
        (token,), fetch=True
    )
    if row and row[0][0] > time.time():
        return True
    return False


def require_owner(request: Request):
    if not is_owner(request):
        raise HTTPException(status_code=403, detail="Forbidden — owner only")
    return True


# ── Command Sandbox ──
SANDBOX_PATTERNS = [
    r"rm\s+-rf\s+/",
    r":\(\)\s*\{\s*:\|:\s*&\s*\};",
    r"mkfs\.",
    r"dd\s+if=.+",
    r">\s*/dev/[sh]da",
    r"curl\s+.*\s*\|\s*sh",
    r"wget\s+.*\s*\|\s*sh",
    r"\bformat\s+/dev",
]


def sandbox_check(command: str) -> bool:
    for pat in SANDBOX_PATTERNS:
        if re.search(pat, command, re.IGNORECASE):
            return False
    return True


# ── Worker Management ──
@dataclass
class Worker:
    ws: WebSocket
    worker_id: str
    capabilities: dict
    last_ping: float
    current_job: Optional[str] = None


@dataclass
class Job:
    job_id: str
    prompt: str
    model: str
    status: str = "queued"
    response: Optional[str] = None
    worker_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


class WorkerPool:
    def __init__(self):
        self.workers: Dict[str, Worker] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.pending: Dict[str, asyncio.Future] = {}
        self.job_cache: Dict[str, Job] = {}

    async def register(self, ws: WebSocket, worker_id: str, caps: dict):
        self.workers[worker_id] = Worker(ws, worker_id, caps, time.time())
        logger.info(f"Worker registered: {worker_id}")

    async def unregister(self, worker_id: str):
        if worker_id in self.workers:
            del self.workers[worker_id]
            logger.info(f"Worker unregistered: {worker_id}")

    async def submit(self, prompt: str, model: str = "default") -> tuple:
        job_id = secrets.token_hex(8)
        db_exec(
            "INSERT INTO jobs (id, prompt, status, created_at, model) VALUES (?, ?, 'queued', ?, ?)",
            (job_id, prompt, time.time(), model)
        )
        job = Job(job_id=job_id, prompt=prompt, model=model)
        self.job_cache[job_id] = job
        future = asyncio.get_event_loop().create_future()
        self.pending[job_id] = future
        await self.queue.put(job_id)
        return job_id, future

    async def route(self):
        while True:
            job_id = await self.queue.get()
            job = self.job_cache.get(job_id)
            if not job:
                continue

            capable = [
                w for w in self.workers.values()
                if w.current_job is None
                and any(m in w.capabilities.get("models", []) for m in [job.model, "default"])
            ]

            if not capable:
                await asyncio.sleep(2)
                await self.queue.put(job_id)
                continue

            worker = max(capable, key=lambda w: len(w.capabilities.get("models", [])))
            worker.current_job = job_id
            job.status = "assigned"
            job.worker_id = worker.worker_id

            try:
                await worker.ws.send_json({
                    "type": "inference_request",
                    "job_id": job_id,
                    "prompt": job.prompt,
                    "model": job.model
                })
            except Exception as e:
                logger.error(f"Routing failed for {job_id}: {e}")
                worker.current_job = None
                await self.queue.put(job_id)

    async def handle_response(self, job_id: str, response: str, worker_id: str):
        if job_id in self.pending:
            self.pending[job_id].set_result(response)
            del self.pending[job_id]
        if worker_id in self.workers:
            self.workers[worker_id].current_job = None
        db_exec(
            "UPDATE jobs SET status = ?, response = ?, worker_id = ?, completed_at = ? WHERE id = ?",
            ("completed", response, worker_id, time.time(), job_id)
        )
        if job_id in self.job_cache:
            self.job_cache[job_id].status = "completed"
            self.job_cache[job_id].response = response
            self.job_cache[job_id].completed_at = time.time()


pool = WorkerPool()


# ── Lifespan ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(pool.route())
    asyncio.create_task(cleanup_stale_workers())
    asyncio.create_task(cleanup_expired_tokens())
    yield


app = FastAPI(title="Termux Server v2.4", version="2.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


# ═══════════════════════════════════════════
#  HTTP Endpoints
# ═══════════════════════════════════════════

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "2.4.0",
        "codename": "The Pool",
        "workers_online": len(pool.workers),
        "queue_depth": pool.queue.qsize()
    }


@app.post("/execute")
async def execute(request: Request):
    data = await request.json()
    command = data.get("command", "")
    timeout = min(data.get("timeout", 30), 300)

    owner = is_owner(request)

    if not owner:
        if not sandbox_check(command):
            return JSONResponse({"error": "Command blocked by sandbox"}, status_code=403)
        allowed = ("echo", "cat", "ls", "pwd", "uname", "ps", "df", "free",
                   "whoami", "date", "head", "tail", "grep", "wc", "sort", "uniq")
        stripped = command.strip()
        if not any(stripped.startswith(p) for p in allowed):
            return JSONResponse({"error": "Command not allowed for public users"}, status_code=403)

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=TERMUX_HOME
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "owner": owner
        }
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "Timeout"}, status_code=408)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/file/read")
async def file_read(request: Request):
    data = await request.json()
    path = data.get("path", "")
    full = os.path.abspath(os.path.join(TERMUX_HOME, path))
    if not full.startswith(os.path.abspath(TERMUX_HOME)):
        raise HTTPException(403, "Path traversal detected")
    if not os.path.exists(full):
        raise HTTPException(404, "File not found")
    try:
        with open(full, "r") as f:
            return {"content": f.read(), "path": path}
    except UnicodeDecodeError:
        return JSONResponse({"error": "Binary file — use /file/download"}, status_code=400)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/file/write")
async def file_write(request: Request):
    require_owner(request)
    data = await request.json()
    path = data.get("path", "")
    content = data.get("content", "")
    full = os.path.abspath(os.path.join(TERMUX_HOME, path))
    if not full.startswith(os.path.abspath(TERMUX_HOME)):
        raise HTTPException(403, "Path traversal detected")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return {"status": "ok", "path": path}


@app.post("/file/delete")
async def file_delete(request: Request):
    require_owner(request)
    data = await request.json()
    path = data.get("path", "")
    full = os.path.abspath(os.path.join(TERMUX_HOME, path))
    if not full.startswith(os.path.abspath(TERMUX_HOME)):
        raise HTTPException(403, "Path traversal detected")
    if os.path.isdir(full):
        import shutil
        shutil.rmtree(full)
    else:
        os.remove(full)
    return {"status": "deleted", "path": path}


@app.get("/file/list")
async def file_list(request: Request, path: str = ""):
    full = os.path.abspath(os.path.join(TERMUX_HOME, path))
    if not full.startswith(os.path.abspath(TERMUX_HOME)):
        raise HTTPException(403, "Path traversal detected")
    if not os.path.isdir(full):
        raise HTTPException(404, "Not a directory")
    items = []
    for name in os.listdir(full):
        p = os.path.join(full, name)
        items.append({
            "name": name,
            "is_dir": os.path.isdir(p),
            "size": os.path.getsize(p) if os.path.isfile(p) else None,
            "mtime": os.path.getmtime(p)
        })
    return {"path": path or "/", "items": items}


@app.post("/inference")
async def inference(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "")
    model = data.get("model", "default")
    if not prompt:
        raise HTTPException(400, "prompt required")

    job_id, future = await pool.submit(prompt, model)
    try:
        result = await asyncio.wait_for(future, timeout=90)
        return {"job_id": job_id, "status": "completed", "response": result}
    except asyncio.TimeoutError:
        return JSONResponse({"job_id": job_id, "status": "timeout"}, status_code=408)


@app.get("/inference/stream/{job_id}")
async def inference_stream(job_id: str):
    async def event_generator():
        while True:
            row = db_exec("SELECT status, response FROM jobs WHERE id = ?", (job_id,), fetch=True)
            if row:
                status, response = row[0]
                yield f"data: {json.dumps({'status': status, 'response': response})}\n\n"
                if status in ("completed", "error"):
                    break
            await asyncio.sleep(1)
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/inference/jobs")
async def inference_jobs(limit: int = 50):
    rows = db_exec(
        "SELECT id, prompt, status, worker_id, created_at, completed_at, model "
        "FROM jobs ORDER BY created_at DESC LIMIT ?",
        (limit,), fetch=True
    )
    jobs = []
    for r in rows:
        jobs.append({
            "id": r[0], "prompt": r[1][:100] + "..." if len(r[1]) > 100 else r[1],
            "status": r[2], "worker_id": r[3],
            "created_at": r[4], "completed_at": r[5], "model": r[6]
        })
    return {"jobs": jobs}


@app.get("/pool")
async def pool_dashboard(request: Request, join: Optional[str] = None):
    if join == OWNER_SECRET:
        if not rate_limiter.check(f"join_{request.client.host}"):
            raise HTTPException(429, "Rate limited")
        token = secrets.token_urlsafe(32)
        now = time.time()
        db_exec(
            "INSERT INTO tokens VALUES (?, ?, ?, 'owner')",
            (token, now, now + TOKEN_TTL)
        )
        resp = JSONResponse({"status": "owner_authenticated", "ttl": TOKEN_TTL})
        resp.set_cookie(key="ghost", value=token, httponly=True, max_age=TOKEN_TTL)
        return resp

    workers = []
    for w in pool.workers.values():
        workers.append({
            "id": w.worker_id,
            "capabilities": w.capabilities,
            "current_job": w.current_job,
            "last_ping": int(time.time() - w.last_ping)
        })

    stats = db_exec("SELECT status, COUNT(*) FROM jobs GROUP BY status", fetch=True)
    queue_stats = {row[0]: row[1] for row in stats} if stats else {}

    return {
        "pool": "Termux Compute Pool",
        "version": "2.4.0",
        "workers_online": len(workers),
        "workers": workers,
        "queue_stats": queue_stats,
        "queue_depth": pool.queue.qsize(),
        "donate": "Connect a worker to donate compute power to the pool."
    }


@app.get("/federation/peers")
async def federation_peers():
    rows = db_exec("SELECT url, status, last_seen FROM federation_peers", fetch=True)
    return {"peers": [{"url": r[0], "status": r[1], "last_seen": r[2]} for r in rows]}


@app.post("/federation/peers")
async def add_peer(request: Request):
    require_owner(request)
    data = await request.json()
    url = data.get("url", "")
    db_exec(
        "INSERT OR REPLACE INTO federation_peers VALUES (?, ?, ?, ?)",
        (url, time.time(), time.time(), "active")
    )
    return {"status": "added", "url": url}


@app.get("/info")
async def info():
    try:
        uname = subprocess.run(["uname", "-a"], capture_output=True, text=True).stdout.strip()
    except Exception:
        uname = "unknown"
    return {
        "platform": "termux" if "TERMUX_VERSION" in os.environ else "linux",
        "home": TERMUX_HOME,
        "uname": uname,
        "owner_secret_set": bool(os.environ.get("OWNER_SECRET")),
        "api_key_set": bool(API_KEY)
    }


@app.post("/proxy/duckchat")
async def proxy_duckchat(request: Request):
    """Proxy Duck.ai chat API — server-side, no CORS issues."""
    data = await request.json()
    prompt = data.get("prompt", "")
    model = data.get("model", "gpt-4o-mini")
    vqd = data.get("vqd")

    import urllib.request
    import urllib.error

    # Fetch VQD token if not provided
    if not vqd:
        try:
            req = urllib.request.Request(
                "https://duckduckgo.com/duckchat/v1/status",
                headers={"x-vqd-accept": "1", "Accept": "*/*", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                vqd = resp.headers.get("x-vqd-4") or resp.headers.get("X-Vqd-4")
                if not vqd:
                    raw = resp.read()
                    if raw:
                        body = raw.decode("utf-8", errors="ignore")
                        try:
                            obj = json.loads(body)
                            vqd = obj.get("vqd")
                        except:
                            pass
                if not vqd:
                    return JSONResponse({"error": "No VQD token from DuckDuckGo"}, status_code=500)
        except urllib.error.HTTPError as e:
            return JSONResponse({"error": f"DuckDuckGo HTTP {e.code}: {e.reason}"}, status_code=502)
        except Exception as e:
            return JSONResponse({"error": f"VQD fetch failed: {e}"}, status_code=500)

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://duckduckgo.com/duckchat/v1/chat",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-vqd-4": vqd,
            "Accept": "text/event-stream",
            "User-Agent": "Mozilla/5.0"
        },
        method="POST"
    )

    try:
        loop = asyncio.get_event_loop()
        def do_request():
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                if not raw:
                    return ""
                return raw.decode("utf-8", errors="ignore")

        text = await asyncio.wait_for(loop.run_in_executor(None, do_request), timeout=65)

        response_text = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data: "):
                data_line = line[6:]
                if data_line == "[DONE]":
                    break
                try:
                    obj = json.loads(data_line)
                    if "message" in obj:
                        response_text += obj["message"]
                except:
                    pass

        return {"response": response_text, "vqd": vqd}

    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")[:500]
        except:
            err_body = ""
        return JSONResponse({"error": f"DuckDuckGo chat HTTP {e.code}: {e.reason}. {err_body}"}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": f"Chat request failed: {e}"}, status_code=500)


# ═══════════════════════════════════════════
#  WebSocket Endpoints
# ═══════════════════════════════════════════

@app.websocket("/ws/worker")
async def worker_ws(websocket: WebSocket):
    await websocket.accept()
    worker_id = None
    try:
        msg = await websocket.receive_json()
        if msg.get("type") == "register":
            worker_id = msg.get("worker_id", f"anon-{id(websocket)}")
            caps = msg.get("capabilities", {})
            await pool.register(websocket, worker_id, caps)

            while True:
                msg = await websocket.receive_json()
                mtype = msg.get("type")
                if mtype == "pong":
                    if worker_id in pool.workers:
                        pool.workers[worker_id].last_ping = time.time()
                elif mtype == "inference_response":
                    jid = msg.get("job_id")
                    await pool.handle_response(jid, msg.get("response", ""), worker_id)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Worker WS error: {e}")
    finally:
        if worker_id:
            await pool.unregister(worker_id)


@app.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    await websocket.accept()

    owner = False
    try:
        auth_msg = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        auth_data = json.loads(auth_msg)
        token = auth_data.get("token", "")
        row = db_exec(
            "SELECT expires_at FROM tokens WHERE token = ? AND type = 'owner'",
            (token,), fetch=True
        )
        if row and row[0][0] > time.time():
            owner = True
    except Exception:
        pass

    if owner:
        await _real_pty(websocket)
    else:
        await _fake_shell(websocket)


async def _real_pty(websocket: WebSocket):
    import pty
    import os as os_mod
    import select

    master_fd, slave_fd = pty.openpty()
    pid = os_mod.fork()
    if pid == 0:
        os_mod.setsid()
        os_mod.dup2(slave_fd, 0)
        os_mod.dup2(slave_fd, 1)
        os_mod.dup2(slave_fd, 2)
        os_mod.close(master_fd)
        os_mod.close(slave_fd)
        os_mod.chdir(TERMUX_HOME)
        os_mod.execv("/bin/bash", ["bash", "-l"])
        os_mod._exit(1)

    os_mod.close(slave_fd)

    try:
        while True:
            ready, _, _ = select.select([master_fd, websocket], [], [], 0.1)
            if master_fd in ready:
                try:
                    data = os_mod.read(master_fd, 4096)
                    if data:
                        await websocket.send_text(data.decode("utf-8", errors="replace"))
                except OSError:
                    break
            if websocket in ready:
                try:
                    msg = await websocket.receive_text()
                    os_mod.write(master_fd, msg.encode())
                except WebSocketDisconnect:
                    break
    finally:
        os_mod.close(master_fd)
        try:
            os_mod.kill(pid, 9)
        except Exception:
            pass


async def _fake_shell(websocket: WebSocket):
    await websocket.send_text("\r\nTermux Public Shell [sandboxed]\r\n$ ")
    while True:
        try:
            msg = await websocket.receive_text()
            cmd = msg.strip()
            if cmd in ("exit", "quit"):
                await websocket.send_text("\r\nGoodbye.\r\n")
                break
            if not sandbox_check(cmd):
                await websocket.send_text("Command blocked by sandbox\r\n$ ")
                continue
            allowed = ("echo", "cat", "ls", "pwd", "uname", "date", "whoami", "ps", "df", "free")
            if not any(cmd.startswith(p) for p in allowed):
                await websocket.send_text(f"{cmd}: command not allowed\r\n$ ")
                continue
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=10, cwd=TERMUX_HOME
                )
                out = result.stdout + result.stderr
                await websocket.send_text(out.replace("\n", "\r\n") + "\r\n$ ")
            except Exception as e:
                await websocket.send_text(f"Error: {e}\r\n$ ")
        except WebSocketDisconnect:
            break


# ═══════════════════════════════════════════
#  Background Tasks
# ═══════════════════════════════════════════

async def cleanup_stale_workers():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        stale = [wid for wid, w in pool.workers.items() if now - w.last_ping > 60]
        for wid in stale:
            logger.info(f"Removing stale worker {wid}")
            await pool.unregister(wid)


async def cleanup_expired_tokens():
    while True:
        await asyncio.sleep(3600)
        db_exec("DELETE FROM tokens WHERE expires_at < ?", (time.time(),))
        logger.info("Expired tokens cleaned")


# ═══════════════════════════════════════════
#  Static Page Routes
# ═══════════════════════════════════════════

@app.get("/")
async def index():
    return FileResponse(os.path.join(static_path, "index.html"))


@app.get("/terminal")
async def terminal_page():
    return FileResponse(os.path.join(static_path, "terminal.html"))


@app.get("/files")
async def files_page():
    return FileResponse(os.path.join(static_path, "file_manager.html"))


@app.get("/ghost")
async def ghost_page():
    return FileResponse(os.path.join(static_path, "ghost_worker.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
