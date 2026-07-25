#!/usr/bin/env python3
"""
Termux Server API v2.4 — \"The Mesh\"
Real ghost workers, SQLite queue, capability routing, SSE streaming,
auto-restart, model hot-swap, rate limits, sandbox, token TTL.
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Request, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import subprocess
import os
import json
import asyncio
import pty
import signal
import psutil
import uuid
import time
import random
import secrets
import logging
import sqlite3
import threading
from datetime import datetime
from collections import defaultdict

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False

os.makedirs(os.path.expanduser("~/termux-server/var/log"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.expanduser("~/termux-server/var/log/api.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Termux Server v2.4 — The Mesh", version="2.4.0")

TERMUX_HOME = os.path.expanduser("~/termux-server/home")
TERMUX_TMP = os.path.expanduser("~/termux-server/tmp")
TERMUX_VAR = os.path.expanduser("~/termux-server/var")
TERMUX_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TERMUX_MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
for d in [TERMUX_HOME, TERMUX_TMP, TERMUX_VAR, TERMUX_MODELS]:
    os.makedirs(d, exist_ok=True)

if os.path.isdir(TERMUX_STATIC):
    app.mount("/static", StaticFiles(directory=TERMUX_STATIC), name="static")

OWNER_SECRET = os.environ.get("OWNER_SEED", secrets.token_urlsafe(32))
logger.info("=" * 60)
logger.info("OWNER SECRET (save this to access admin features):")
logger.info(f"  {OWNER_SECRET}")
logger.info("=" * 60)

ghost_tokens: Dict[str, float] = {}
TOKEN_TTL_SECONDS = 86400
join_attempts: Dict[str, List[float]] = defaultdict(list)
MAX_JOIN_ATTEMPTS_PER_HOUR = 10
BLOCKED_PATTERNS = ["rm -rf /", "> /dev/sda", "mkfs.", "dd if=/dev/zero", ":(){ :|:& };:"]

def create_ghost_token() -> str:
    tok = secrets.token_urlsafe(32)
    ghost_tokens[tok] = time.time() + TOKEN_TTL_SECONDS
    return tok

def is_owner(request: Request) -> bool:
    tok = request.cookies.get("ghost")
    if not tok:
        return False
    expiry = ghost_tokens.get(tok)
    if not expiry:
        return False
    if time.time() > expiry:
        ghost_tokens.pop(tok, None)
        return False
    return True

def require_owner(request: Request):
    if not is_owner(request):
        raise HTTPException(status_code=404, detail="Not found")

def check_rate_limit(ip: str):
    now = time.time()
    join_attempts[ip] = [t for t in join_attempts[ip] if now - t < 3600]
    if len(join_attempts[ip]) > MAX_JOIN_ATTEMPTS_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many attempts")
    join_attempts[ip].append(now)

def sandbox_check(command: str) -> Optional[str]:
    for pattern in BLOCKED_PATTERNS:
        if pattern in command:
            return f"Command blocked by sandbox: '{pattern}'"
    return None

DB_PATH = os.path.expanduser("~/termux-server/var/pool.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, prompt TEXT NOT NULL, status TEXT DEFAULT 'pending',
        result TEXT, worker_id TEXT, worker_type TEXT, created REAL, started REAL,
        completed REAL, stream INTEGER DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS peers (
        id TEXT PRIMARY KEY, url TEXT NOT NULL, api_key TEXT, last_seen REAL, enabled INTEGER DEFAULT 1)""")
    conn.commit()
    conn.close()

init_db()

def db_conn():
    return sqlite3.connect(DB_PATH)

def enqueue_job(prompt: str, stream: bool = False) -> str:
    job_id = str(uuid.uuid4())[:12]
    conn = db_conn()
    conn.execute("INSERT INTO jobs (id, prompt, status, created, stream) VALUES (?, ?, ?, ?, ?)",
                 (job_id, prompt, "pending", time.time(), int(stream)))
    conn.commit()
    conn.close()
    return job_id

def get_job(job_id: str) -> Optional[Dict]:
    conn = db_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    cols = ["id", "prompt", "status", "result", "worker_id", "worker_type", "created", "started", "completed", "stream"]
    return dict(zip(cols, row))

def update_job(job_id: str, **kwargs):
    conn = db_conn()
    for k, v in kwargs.items():
        conn.execute(f"UPDATE jobs SET {k} = ? WHERE id = ?", (v, job_id))
    conn.commit()
    conn.close()

def get_pending_jobs(limit: int = 10) -> List[Dict]:
    conn = db_conn()
    rows = conn.execute("SELECT * FROM jobs WHERE status = 'pending' ORDER BY created LIMIT ?", (limit,)).fetchall()
    conn.close()
    cols = ["id", "prompt", "status", "result", "worker_id", "worker_type", "created", "started", "completed", "stream"]
    return [dict(zip(cols, r)) for r in rows]

def get_queue_stats() -> Dict:
    conn = db_conn()
    pending = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'pending'").fetchone()[0]
    running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'").fetchone()[0]
    completed_1h = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'complete' AND completed > ?", (time.time() - 3600,)).fetchone()[0]
    avg_time = conn.execute("SELECT AVG(completed - started) FROM jobs WHERE status = 'complete' AND completed > ?", (time.time() - 3600,)).fetchone()[0]
    conn.close()
    return {"pending": pending, "running": running, "completed_1h": completed_1h, "avg_compute_time": round(avg_time, 2) if avg_time else None}

worker_registry: Dict[str, Dict] = {}
stream_queues: Dict[str, asyncio.Queue] = {}
scheduled_jobs: Dict[str, Dict] = {}
if SCHEDULER_AVAILABLE:
    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("Scheduler started")
else:
    scheduler = None
terminal_sessions: Dict[str, Dict] = {}

def score_worker(worker: Dict, job: Dict) -> float:
    score = 0.0
    caps = worker.get("capabilities", {})
    if worker.get("type") == "python":
        score += 10
    elif worker.get("type") == "ghost":
        score += 3
    if caps.get("has_gpu") or caps.get("gpu"):
        score += 5
    score += caps.get("ram_gb", 0) * 0.5
    last_seen = worker.get("last_seen", worker.get("connected", 0))
    score += max(0, 5 - (time.time() - last_seen))
    return score

def pick_worker_for_job(job: Dict) -> Optional[tuple]:
    if not worker_registry:
        return None
    candidates = [(wid, w) for wid, w in worker_registry.items()]
    candidates.sort(key=lambda x: score_worker(x[1], job), reverse=True)
    return candidates[0] if candidates else None

async def stale_worker_cleanup():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        stale = [wid for wid, w in list(worker_registry.items()) if now - w.get("last_seen", w.get("connected", 0)) > 60]
        for wid in stale:
            logger.info(f"[Cleanup] Removing stale worker {wid}")
            worker_registry.pop(wid, None)

async def queue_processor():
    while True:
        await asyncio.sleep(1)
        for job in get_pending_jobs(limit=20):
            picked = pick_worker_for_job(job)
            if not picked:
                continue
            wid, worker = picked
            try:
                update_job(job["id"], status="running", worker_id=wid, started=time.time())
                if worker.get("type") == "ghost":
                    await worker["ws"].send_text(json.dumps({"type": "inference_request", "task_id": job["id"], "prompt": job["prompt"], "stream": bool(job.get("stream"))}))
                else:
                    await worker["ws"].send_text(json.dumps({"type": "inference", "job_id": job["id"], "prompt": job["prompt"], "stream": bool(job.get("stream"))}))
                logger.info(f"[Queue] Assigned job {job['id']} to worker {wid}")
            except Exception as e:
                logger.error(f"[Queue] Failed to assign job {job['id']}: {e}")
                update_job(job["id"], status="pending", worker_id=None)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(stale_worker_cleanup())
    asyncio.create_task(queue_processor())
    logger.info("[Startup] Background tasks started")

class CommandRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    timeout: Optional[int] = 30

class FileRequest(BaseModel):
    path: str
    content: Optional[str] = None

class PackageRequest(BaseModel):
    action: str
    package: Optional[str] = None

class ScheduleRequest(BaseModel):
    name: str
    command: str
    cron: str
    enabled: bool = True

class InferenceRequest(BaseModel):
    prompt: str
    prefer_gpu: bool = True
    params: Optional[Dict[str, Any]] = None

class PeerRequest(BaseModel):
    url: str
    api_key: Optional[str] = None

class TermuxResponse(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
    returncode: Optional[int] = None

def resolve_path(filepath: str) -> str:
    full = os.path.join(TERMUX_HOME, filepath.lstrip("/"))
    resolved = os.path.abspath(full)
    if not resolved.startswith(os.path.abspath(TERMUX_HOME)):
        raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
    return resolved

async def fake_shell(websocket: WebSocket):
    await websocket.send_text("\x1b[2J\x1b[H")
    await websocket.send_text("\x1b[1;32m╔══════════════════════════════════════════╗\x1b[0m\r\n")
    await websocket.send_text("\x1b[1;32m║  Termux Compute Pool Node v2.4         ║\x1b[0m\r\n")
    await websocket.send_text("\x1b[1;32m║  Distributed Inference Network         ║\x1b[0m\r\n")
    await websocket.send_text("\x1b[1;32m╚══════════════════════════════════════════╝\x1b[0m\r\n")
    await websocket.send_text("\x1b[90mType 'help' for available commands.\x1b[0m\r\n\r\n")
    await websocket.send_text("\x1b[1;36m[donor]\x1b[0m\x1b[32m$\x1b[0m ")
    buf = ""
    while True:
        try:
            msg = await websocket.receive_text()
            for ch in msg:
                if ch == '\r':
                    cmd = buf.strip()
                    buf = ""
                    await websocket.send_text("\r\n")
                    if cmd == "help":
                        await websocket.send_text("\r\n  status, workers, queue, inference <prompt>, donate, clear, exit\r\n")
                    elif cmd == "status":
                        mem = psutil.virtual_memory()
                        load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
                        stats = get_queue_stats()
                        await websocket.send_text(f"\r\n  CPU Load: {load[0]:.2f}\r\n  Memory: {mem.percent}%\r\n  Workers: {len(worker_registry)}\r\n  Queue: {stats['pending']} pending, {stats['running']} running\r\n")
                    elif cmd == "queue":
                        stats = get_queue_stats()
                        await websocket.send_text(f"\r\n  Pending: {stats['pending']}\r\n  Running: {stats['running']}\r\n  Completed (1h): {stats['completed_1h']}\r\n")
                    elif cmd == "workers":
                        if not worker_registry:
                            await websocket.send_text("\r\n  No active donor nodes.\r\n")
                        else:
                            await websocket.send_text(f"\r\n  Active donors: {len(worker_registry)}\r\n")
                            for wid, w in worker_registry.items():
                                await websocket.send_text(f"    [{w.get('type','?')}] {wid[:8]}...\r\n")
                    elif cmd.startswith("inference "):
                        prompt = cmd[10:]
                        jid = enqueue_job(prompt)
                        await websocket.send_text(f"\r\n  \x1b[33m[job {jid}] Queued...\x1b[0m\r\n")
                        for _ in range(60):
                            j = get_job(jid)
                            if j and j["status"] == "complete":
                                await websocket.send_text(f"  \x1b[32mResult:\x1b[0m {(j['result'] or '')[:500]}\r\n")
                                break
                            await asyncio.sleep(1)
                        else:
                            await websocket.send_text(f"  \x1b[31m[job {jid}] Still processing.\x1b[0m\r\n")
                    elif cmd == "donate":
                        await websocket.send_text("\r\n  Python: export POOL_SERVER=wss://<host>/ws/worker && python3 worker_node.py\r\n  Browser: /static/ghost_worker.html\r\n")
                    elif cmd == "clear":
                        await websocket.send_text("\x1b[2J\x1b[H")
                    elif cmd == "exit":
                        await websocket.send_text("\r\n  Disconnecting...\r\n")
                        return
                    elif cmd:
                        await websocket.send_text(f"\r\n  \x1b[31m'{cmd}': command not found\x1b[0m\r\n")
                    await websocket.send_text("\x1b[1;36m[donor]\x1b[0m\x1b[32m$\x1b[0m ")
                elif ch in ('\x7f', '\b'):
                    if buf:
                        buf = buf[:-1]
                        await websocket.send_text("\b \b")
                elif ord(ch) >= 32:
                    buf += ch
                    await websocket.send_text(ch)
        except WebSocketDisconnect:
            break
        except Exception as e:
            logger.error(f"Fake shell error: {e}")
            break

@app.get("/", response_class=HTMLResponse)
async def root():
    return open(os.path.join(TERMUX_STATIC, "index.html")).read()

@app.get("/pool")
async def pool_gate(join: str = "", request: Request = None):
    client_ip = request.client.host if request and request.client else "unknown"
    if join:
        check_rate_limit(client_ip)
    if join == OWNER_SECRET:
        token = create_ghost_token()
        resp = RedirectResponse(url="/")
        resp.set_cookie(key="ghost", value=token, httponly=True, samesite="strict")
        return resp
    return JSONResponse({"pool": "Termux Compute Pool", "version": "2.4.0", "workers": len(worker_registry), "queue": get_queue_stats(), "message": "Download worker_node.py or open the ghost worker to donate compute."})

@app.get("/health")
async def health():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    stats = get_queue_stats()
    return {"status": "healthy", "pool": "Termux Compute Pool", "workers": len(worker_registry),
            "python_workers": sum(1 for w in worker_registry.values() if w.get("type") != "ghost"),
            "ghost_workers": sum(1 for w in worker_registry.values() if w.get("type") == "ghost"),
            "queue": stats, "memory": {"total": mem.total, "available": mem.available, "percent": mem.percent},
            "disk": {"total": disk.total, "free": disk.free, "percent": disk.percent}}

@app.get("/info")
async def get_info():
    uname = subprocess.run("uname -a", shell=True, capture_output=True, text=True).stdout.strip()
    return {"pool": "Termux Compute Pool", "home": TERMUX_HOME, "system": uname,
            "python_version": __import__("sys").version, "cpu_count": os.cpu_count(),
            "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else None,
            "workers_connected": len(worker_registry)}

@app.get("/auth/check")
async def auth_check(request: Request):
    return {"owner": is_owner(request)}

@app.post("/inference")
async def inference(request: InferenceRequest):
    job_id = enqueue_job(request.prompt, stream=False)
    for _ in range(60):
        j = get_job(job_id)
        if j and j["status"] == "complete":
            return {"job_id": job_id, "status": "complete", "result": j["result"]}
        await asyncio.sleep(1)
    j = get_job(job_id)
    return {"job_id": job_id, "status": j["status"] if j else "unknown", "result": j.get("result") if j else None}

@app.get("/inference/stream")
async def inference_stream(prompt: str):
    job_id = enqueue_job(prompt, stream=True)
    stream_queues[job_id] = asyncio.Queue()
    async def event_generator():
        yield f"data: {{\"job_id\": \"{job_id}\", \"status\": \"queued\"}}\n\n"
        while True:
            try:
                token = await asyncio.wait_for(stream_queues[job_id].get(), timeout=60.0)
                if token == "__DONE__":
                    j = get_job(job_id)
                    yield f"data: {{\"job_id\": \"{job_id}\", \"status\": \"complete\"}}\n\n"
                    break
                elif token.startswith("__ERROR__"):
                    yield f"data: {{\"job_id\": \"{job_id}\", \"status\": \"error\", \"result\": \"{token[9:]}\"}}\n\n"
                    break
                else:
                    safe = token.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
                    yield f"data: {{\"job_id\": \"{job_id}\", \"token\": \"{safe}\"}}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {{\"job_id\": \"{job_id}\", \"status\": \"timeout\"}}\n\n"
                break
        stream_queues.pop(job_id, None)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/models/{path:path}")
async def serve_model(path: str):
    filepath = os.path.join(TERMUX_MODELS, path.lstrip("/"))
    resolved = os.path.abspath(filepath)
    if not resolved.startswith(os.path.abspath(TERMUX_MODELS)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Model not found")
    return FileResponse(filepath, filename=os.path.basename(filepath))

@app.post("/federation/peers")
async def add_peer(request: PeerRequest, req: Request = None):
    require_owner(req)
    peer_id = str(uuid.uuid4())[:8]
    conn = db_conn()
    conn.execute("INSERT OR REPLACE INTO peers (id, url, api_key, last_seen) VALUES (?, ?, ?, ?)", (peer_id, request.url, request.api_key, time.time()))
    conn.commit()
    conn.close()
    return {"success": True, "peer_id": peer_id}

@app.get("/federation/peers")
async def list_peers(req: Request = None):
    require_owner(req)
    conn = db_conn()
    rows = conn.execute("SELECT id, url, last_seen, enabled FROM peers").fetchall()
    conn.close()
    return {"peers": [{"id": r[0], "url": r[1], "last_seen": r[2], "enabled": bool(r[3])} for r in rows]}

@app.post("/execute", response_model=TermuxResponse)
async def execute_command(request: CommandRequest, req: Request = None):
    require_owner(req)
    blocked = sandbox_check(request.command)
    if blocked:
        return TermuxResponse(success=False, output="", error=blocked, returncode=-1)
    try:
        cwd = request.cwd or TERMUX_HOME
        env = os.environ.copy()
        if request.env:
            env.update(request.env)
        env["HOME"] = TERMUX_HOME
        env["TMPDIR"] = TERMUX_TMP
        result = subprocess.run(request.command, shell=True, cwd=cwd, env=env, capture_output=True, text=True, timeout=request.timeout)
        return TermuxResponse(success=result.returncode == 0, output=result.stdout, error=result.stderr if result.stderr else None, returncode=result.returncode)
    except subprocess.TimeoutExpired:
        return TermuxResponse(success=False, output="", error=f"Timeout after {request.timeout}s", returncode=-1)
    except Exception as e:
        return TermuxResponse(success=False, output="", error=str(e), returncode=-1)

@app.post("/file/read", response_model=TermuxResponse)
async def read_file(request: FileRequest):
    try:
        filepath = resolve_path(request.path)
        with open(filepath, "r") as f:
            content = f.read()
        return TermuxResponse(success=True, output=content)
    except FileNotFoundError:
        return TermuxResponse(success=False, output="", error=f"File not found: {request.path}")
    except Exception as e:
        return TermuxResponse(success=False, output="", error=str(e))

@app.post("/file/write", response_model=TermuxResponse)
async def write_file(request: FileRequest, req: Request = None):
    require_owner(req)
    try:
        filepath = resolve_path(request.path)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            f.write(request.content or "")
        return TermuxResponse(success=True, output=f"File written: {request.path}")
    except Exception as e:
        return TermuxResponse(success=False, output="", error=str(e))

@app.post("/file/upload")
async def upload_file(path: str = Form(...), file: UploadFile = File(...), req: Request = None):
    require_owner(req)
    try:
        filepath = resolve_path(path)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            content = await file.read()
            f.write(content)
        return {"success": True, "output": f"Uploaded: {path}", "size": len(content)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/file/download/{path:path}")
async def download_file(path: str):
    try:
        filepath = resolve_path(path)
        if not os.path.isfile(filepath):
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(filepath, filename=os.path.basename(filepath))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/file/list/{path:path}")
async def list_files(path: str = ""):
    try:
        dirpath = resolve_path(path) if path else TERMUX_HOME
        if not os.path.isdir(dirpath):
            raise HTTPException(status_code=404, detail="Directory not found")
        items = []
        for entry in os.scandir(dirpath):
            stat = entry.stat()
            items.append({"name": entry.name, "path": os.path.relpath(entry.path, TERMUX_HOME), "type": "directory" if entry.is_dir() else "file", "size": stat.st_size, "modified": stat.st_mtime})
        items.sort(key=lambda x: (x["type"] != "directory", x["name"].lower()))
        return {"success": True, "path": path or "/", "items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/file/delete/{path:path}")
async def delete_file(path: str, req: Request = None):
    require_owner(req)
    try:
        filepath = resolve_path(path)
        if os.path.isdir(filepath):
            os.rmdir(filepath)
        else:
            os.remove(filepath)
        return {"success": True, "output": f"Deleted: {path}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/package", response_model=TermuxResponse)
async def manage_package(request: PackageRequest, req: Request = None):
    require_owner(req)
    try:
        if request.action == "install":
            if not request.package:
                raise ValueError("Package name required")
            cmd = f"apt-get install -y {request.package}"
        elif request.action == "remove":
            if not request.package:
                raise ValueError("Package name required")
            cmd = f"apt-get remove -y {request.package}"
        elif request.action == "update":
            cmd = "apt-get update"
        elif request.action == "list":
            cmd = "apt list --installed"
        else:
            raise ValueError(f"Unknown action: {request.action}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        return TermuxResponse(success=result.returncode == 0, output=result.stdout, error=result.stderr if result.returncode != 0 else None, returncode=result.returncode)
    except Exception as e:
        return TermuxResponse(success=False, output="", error=str(e))

@app.get("/processes")
async def list_processes(req: Request = None):
    require_owner(req)
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent", "status", "create_time"]):
            try:
                info = p.info
                info["cmdline"] = " ".join(p.cmdline()) if p.cmdline() else ""
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {"success": True, "count": len(procs), "processes": procs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/processes/kill/{pid}")
async def kill_process(pid: int, req: Request = None):
    require_owner(req)
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        gone, alive = psutil.wait_procs([proc], timeout=3)
        if proc in alive:
            proc.kill()
        return {"success": True, "output": f"Process {pid} terminated"}
    except psutil.NoSuchProcess:
        raise HTTPException(status_code=404, detail="Process not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/schedule")
async def create_schedule(request: ScheduleRequest, req: Request = None):
    require_owner(req)
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Scheduler not available. Install APScheduler.")
    try:
        job_id = str(uuid.uuid4())[:8]
        def job_wrapper():
            logger.info(f"[Scheduled {job_id}] Running: {request.command}")
            subprocess.run(request.command, shell=True, cwd=TERMUX_HOME, capture_output=True)
        trigger = CronTrigger.from_crontab(request.cron)
        job = scheduler.add_job(job_wrapper, trigger=trigger, id=job_id, name=request.name)
        scheduled_jobs[job_id] = {"id": job_id, "name": request.name, "command": request.command, "cron": request.cron, "enabled": request.enabled, "created": datetime.now().isoformat()}
        return {"success": True, "job_id": job_id, "next_run": str(job.next_run_time) if job.next_run_time else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/schedule")
async def list_schedules(req: Request = None):
    require_owner(req)
    if not SCHEDULER_AVAILABLE:
        return {"success": False, "error": "Scheduler not available", "jobs": []}
    jobs = []
    for job in scheduler.get_jobs():
        info = scheduled_jobs.get(job.id, {})
        jobs.append({"id": job.id, "name": info.get("name", job.name), "command": info.get("command", ""), "cron": info.get("cron", ""), "next_run": str(job.next_run_time) if job.next_run_time else None, "enabled": job.next_run_time is not None})
    return {"success": True, "jobs": jobs}

@app.delete("/schedule/{job_id}")
async def delete_schedule(job_id: str, req: Request = None):
    require_owner(req)
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        scheduler.remove_job(job_id)
        scheduled_jobs.pop(job_id, None)
        return {"success": True, "output": f"Job {job_id} removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/worker")
async def worker_ws(websocket: WebSocket):
    await websocket.accept()
    worker_id = str(uuid.uuid4())[:8]
    worker_registry[worker_id] = {"ws": websocket, "connected": time.time(), "ip": websocket.client.host if websocket.client else "unknown", "type": "python", "capabilities": {}, "models": [], "last_seen": time.time()}
    logger.info(f"[Worker {worker_id}] Connected")
    try:
        while True:
            msg = await websocket.receive_text()
            data = json.loads(msg)
            if data.get("type") in ("worker_registration", "register"):
                worker_id = data.get("worker_id", worker_id)
                worker_registry[worker_id] = {"ws": websocket, "connected": time.time(), "ip": websocket.client.host if websocket.client else "unknown", "type": "ghost" if data.get("platform") == "WASM/Browser" else "python", "capabilities": data.get("capabilities", {}), "models": data.get("models", []), "last_seen": time.time()}
                logger.info(f"[Worker {worker_id}] Registered: {data.get('platform', 'unknown')}")
            elif data.get("type") == "heartbeat":
                if worker_id in worker_registry:
                    worker_registry[worker_id]["last_seen"] = time.time()
                    if data.get("capabilities"):
                        worker_registry[worker_id]["capabilities"].update(data["capabilities"])
            elif data.get("type") == "inference_result":
                job_id = data.get("job_id")
                if job_id:
                    update_job(job_id, status="complete", result=data.get("result", ""), completed=time.time())
            elif data.get("type") == "inference_response":
                task_id = data.get("task_id") or data.get("job_id")
                if task_id:
                    update_job(task_id, status="complete", result=data.get("result", ""), completed=time.time())
            elif data.get("type") == "token":
                job_id = data.get("job_id") or data.get("task_id")
                if job_id and job_id in stream_queues:
                    await stream_queues[job_id].put(data.get("token", ""))
            elif data.get("type") == "stream_done":
                job_id = data.get("job_id") or data.get("task_id")
                if job_id:
                    update_job(job_id, status="complete", result=data.get("result", ""), completed=time.time())
                    if job_id in stream_queues:
                        await stream_queues[job_id].put("__DONE__")
            elif data.get("type") == "stream_error":
                job_id = data.get("job_id") or data.get("task_id")
                if job_id:
                    update_job(job_id, status="error", result=data.get("error", ""))
                    if job_id in stream_queues:
                        await stream_queues[job_id].put(f"__ERROR__{data.get('error','')}")
            elif data.get("type") == "model_loaded":
                if worker_id in worker_registry:
                    worker_registry[worker_id]["models"] = [data.get("model", "")]
    except WebSocketDisconnect:
        logger.info(f"[Worker {worker_id}] Disconnected")
    except Exception as e:
        logger.error(f"[Worker {worker_id}] Error: {e}")
    finally:
        worker_registry.pop(worker_id, None)

@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())[:8]
    is_admin = websocket.cookies.get("ghost") in ghost_tokens
    if not is_admin:
        logger.info(f"[Terminal {session_id}] Public donor session")
        await fake_shell(websocket)
        return
    logger.info(f"[Terminal {session_id}] Owner session started")
    try:
        master_fd, slave_fd = pty.openpty()
        pid = os.fork()
        if pid == 0:
            os.setsid()
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            os.close(master_fd)
            os.close(slave_fd)
            os.environ["HOME"] = TERMUX_HOME
            os.environ["TERM"] = "xterm-256color"
            os.chdir(TERMUX_HOME)
            os.execv("/bin/bash", ["/bin/bash", "-l"])
        else:
            os.close(slave_fd)
            terminal_sessions[session_id] = {"pid": pid, "fd": master_fd, "ws": websocket}
            import fcntl
            fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            loop = asyncio.get_event_loop()
            async def read_from_pty():
                while True:
                    try:
                        data = await loop.run_in_executor(None, lambda: os.read(master_fd, 4096))
                        if data:
                            await websocket.send_text(data.decode("utf-8", errors="replace"))
                        else:
                            break
                    except BlockingIOError:
                        await asyncio.sleep(0.01)
                    except OSError:
                        break
            async def write_to_pty():
                while True:
                    try:
                        msg = await websocket.receive_text()
                        if msg.startswith("\x00RESIZE:"):
                            parts = msg.split(":")[1].split(",")
                            cols, rows = int(parts[0]), int(parts[1])
                            import struct, termios
                            s = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, s)
                        else:
                            os.write(master_fd, msg.encode("utf-8"))
                    except WebSocketDisconnect:
                        break
                    except Exception as e:
                        logger.error(f"[Terminal {session_id}] Write error: {e}")
                        break
            read_task = asyncio.create_task(read_from_pty())
            write_task = asyncio.create_task(write_to_pty())
            done, pending = await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except WebSocketDisconnect:
        logger.info(f"[Terminal {session_id}] Disconnected")
    except Exception as e:
        logger.error(f"[Terminal {session_id}] Error: {e}")
    finally:
        if session_id in terminal_sessions:
            sess = terminal_sessions[session_id]
            try:
                os.close(sess["fd"])
                os.kill(sess["pid"], signal.SIGTERM)
            except Exception:
                pass
            terminal_sessions.pop(session_id, None)
        try:
            await websocket.close()
        except Exception:
            pass

@app.get("/terminal", response_class=HTMLResponse)
async def terminal_page():
    return open(os.path.join(TERMUX_STATIC, "terminal.html")).read()

@app.get("/files", response_class=HTMLResponse)
async def file_manager_page():
    return open(os.path.join(TERMUX_STATIC, "file_manager.html")).read()

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Termux Server v2.4 — The Mesh")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
