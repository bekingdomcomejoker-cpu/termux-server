#!/usr/bin/env python3
"""
Termux Server API v2.3 — "The Pool"
Stealth auth: Public gets a compute pool terminal. Owner gets root.
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Request, Depends
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
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
from datetime import datetime

# Optional scheduler
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False

# Logging
os.makedirs("/home/ubuntu/termux-server/var/log", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/home/ubuntu/termux-server/var/log/api.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Termux Server v2.3 — The Pool", version="2.3.0")

# Paths
TERMUX_HOME = "/home/ubuntu/termux-server/home"
TERMUX_TMP = "/home/ubuntu/termux-server/tmp"
TERMUX_VAR = "/home/ubuntu/termux-server/var"
TERMUX_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
for d in [TERMUX_HOME, TERMUX_TMP, TERMUX_VAR]:
    os.makedirs(d, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# STEALTH AUTH SYSTEM
# ═══════════════════════════════════════════════════════════════

# Owner secret: set via env, or auto-generated and printed to logs
OWNER_SECRET = os.environ.get("OWNER_SEED", secrets.token_urlsafe(32))
logger.info("=" * 60)
logger.info("OWNER SECRET (save this to access admin features):")
logger.info(f"  {OWNER_SECRET}")
logger.info("=" * 60)

# In-memory ghost token store (valid until restart; add file persistence if desired)
ghost_tokens: set = set()

# Worker registry for distributed inference
worker_registry: Dict[str, Dict] = {}
inference_results: Dict[str, Any] = {}

# Scheduler
scheduled_jobs: Dict[str, Dict] = {}
if SCHEDULER_AVAILABLE:
    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("Scheduler started")
else:
    scheduler = None

# Active terminal sessions
terminal_sessions: Dict[str, Dict] = {}


def create_ghost_token() -> str:
    tok = secrets.token_urlsafe(32)
    ghost_tokens.add(tok)
    return tok


def is_owner(request: Request) -> bool:
    """Check if request carries a valid ghost cookie."""
    return request.cookies.get("ghost") in ghost_tokens


def require_owner(request: Request):
    """Dependency: raise 404 (not 403) to avoid leaking that admin exists."""
    if not is_owner(request):
        raise HTTPException(status_code=404, detail="Not found")


# ═══════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════

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

class TermuxResponse(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
    returncode: Optional[int] = None


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def resolve_path(filepath: str) -> str:
    full = os.path.join(TERMUX_HOME, filepath.lstrip("/"))
    resolved = os.path.abspath(full)
    if not resolved.startswith(os.path.abspath(TERMUX_HOME)):
        raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
    return resolved


async def fake_shell(websocket: WebSocket):
    """Public-facing 'terminal' that looks real but is completely safe."""
    await websocket.send_text("\x1b[2J\x1b[H")
    await websocket.send_text("\x1b[1;32m╔══════════════════════════════════════════╗\x1b[0m\r\n")
    await websocket.send_text("\x1b[1;32m║  Termux Compute Pool Node v2.3         ║\x1b[0m\r\n")
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
                        out = (
                            "\r\n  \x1b[1mAvailable commands:\x1b[0m\r\n"
                            "  status       Show pool status\r\n"
                            "  workers      List active donor nodes\r\n"
                            "  inference    Run LLM (usage: inference <prompt>)\r\n"
                            "  donate       Get worker node setup script\r\n"
                            "  clear        Clear screen\r\n"
                            "  exit         Disconnect\r\n"
                        )
                        await websocket.send_text(out)
                    elif cmd == "status":
                        mem = psutil.virtual_memory()
                        load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
                        out = (
                            f"\r\n  CPU Load: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}\r\n"
                            f"  Memory:   {mem.percent}% used\r\n"
                            f"  Workers:  {len(worker_registry)} active\r\n"
                            f"  Queue:    {len(inference_results)} jobs processed\r\n"
                        )
                        await websocket.send_text(out)
                    elif cmd == "workers":
                        if not worker_registry:
                            await websocket.send_text("\r\n  No active donor nodes. Be the first!\r\n")
                        else:
                            await websocket.send_text(f"\r\n  Active donors: {len(worker_registry)}\r\n")
                    elif cmd.startswith("inference "):
                        prompt = cmd[10:]
                        jid = str(uuid.uuid4())[:8]
                        inference_results[jid] = None
                        # Try to route to worker
                        routed = False
                        if worker_registry:
                            w = random.choice(list(worker_registry.values()))
                            try:
                                await w["ws"].send_text(json.dumps({"type": "inference", "job_id": jid, "prompt": prompt}))
                                routed = True
                            except:
                                pass
                        if routed:
                            await websocket.send_text(f"\r\n  \x1b[33m[job {jid}] Routing to donor node...\x1b[0m\r\n")
                            # Wait up to 30s for result
                            for _ in range(30):
                                if inference_results.get(jid) is not None:
                                    break
                                await asyncio.sleep(1)
                            res = inference_results.pop(jid, None)
                            if res:
                                await websocket.send_text(f"  \x1b[32mResult:\x1b[0m {res[:500]}\r\n")
                            else:
                                await websocket.send_text(f"  \x1b[31m[job {jid}] Timeout. Try again.\x1b[0m\r\n")
                        else:
                            await websocket.send_text("\r\n  \x1b[31mNo donor nodes available.\x1b[0m\r\n")
                            await websocket.send_text("  Run 'donate' to learn how to contribute.\r\n")
                    elif cmd == "donate":
                        await websocket.send_text(
                            "\r\n  \x1b[1mDonate Compute:\x1b[0m\r\n"
                            "  Download worker_node.py and run it on any device.\r\n"
                            "  Your idle CPU/GPU cycles power the pool.\r\n"
                        )
                    elif cmd == "clear":
                        await websocket.send_text("\x1b[2J\x1b[H")
                    elif cmd == "exit":
                        await websocket.send_text("\r\n  Disconnecting...\r\n")
                        return
                    elif cmd == "":
                        pass
                    else:
                        await websocket.send_text(
                            f"\r\n  \x1b[31m'{cmd}': command not found\x1b[0m\r\n"
                            "  Run 'help' for available commands.\r\n"
                        )
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


# ═══════════════════════════════════════════════════════════════
# PUBLIC ROUTES (No auth required)
# ═══════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def root():
    return open(os.path.join(TERMUX_STATIC, "index.html")).read()


@app.get("/pool")
async def pool_gate(join: str = "", request: Request = None):
    """
    Public pool page. If join == OWNER_SECRET, sets ghost admin cookie.
    Looks like a normal 'join the pool' endpoint to everyone else.
    """
    if join == OWNER_SECRET:
        token = create_ghost_token()
        resp = RedirectResponse(url="/")
        resp.set_cookie(key="ghost", value=token, httponly=True, samesite="strict")
        return resp
    # Public pool info
    return JSONResponse({
        "pool": "Termux Compute Pool",
        "version": "2.3.0",
        "workers": len(worker_registry),
        "message": "Download worker_node.py to donate compute."
    })


@app.get("/health")
async def health():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "status": "healthy",
        "pool": "Termux Compute Pool",
        "workers": len(worker_registry),
        "memory": {"total": mem.total, "available": mem.available, "percent": mem.percent},
        "disk": {"total": disk.total, "free": disk.free, "percent": disk.percent}
    }


@app.get("/info")
async def get_info():
    uname = subprocess.run("uname -a", shell=True, capture_output=True, text=True).stdout.strip()
    return {
        "pool": "Termux Compute Pool",
        "home": TERMUX_HOME,
        "system": uname,
        "python_version": __import__("sys").version,
        "cpu_count": os.cpu_count(),
        "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else None,
        "workers_connected": len(worker_registry)
    }


# ═══════════════════════════════════════════════════════════════
# OWNER-ONLY ROUTES (Shell, file write, packages, processes, schedule)
# ═══════════════════════════════════════════════════════════════

@app.post("/execute", response_model=TermuxResponse)
async def execute_command(request: CommandRequest, req: Request = None):
    require_owner(req)
    try:
        cwd = request.cwd or TERMUX_HOME
        env = os.environ.copy()
        if request.env:
            env.update(request.env)
        env["HOME"] = TERMUX_HOME
        env["TMPDIR"] = TERMUX_TMP

        result = subprocess.run(
            request.command,
            shell=True,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=request.timeout
        )
        return TermuxResponse(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.stderr else None,
            returncode=result.returncode
        )
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
            items.append({
                "name": entry.name,
                "path": os.path.relpath(entry.path, TERMUX_HOME),
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size,
                "modified": stat.st_mtime
            })
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
        return TermuxResponse(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.returncode != 0 else None,
            returncode=result.returncode
        )
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
        scheduled_jobs[job_id] = {
            "id": job_id, "name": request.name, "command": request.command,
            "cron": request.cron, "enabled": request.enabled, "created": datetime.now().isoformat()
        }
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
        jobs.append({
            "id": job.id, "name": info.get("name", job.name),
            "command": info.get("command", ""), "cron": info.get("cron", ""),
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "enabled": job.next_run_time is not None
        })
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


# ═══════════════════════════════════════════════════════════════
# INFERENCE (Public — anyone can submit, workers process)
# ═══════════════════════════════════════════════════════════════

@app.post("/inference")
async def inference(request: InferenceRequest):
    job_id = str(uuid.uuid4())[:8]
    inference_results[job_id] = None

    if not worker_registry:
        return {"job_id": job_id, "status": "queued", "result": "No donor nodes available. Inference queued until a worker connects."}

    # Route to a random worker
    worker = random.choice(list(worker_registry.values()))
    try:
        await worker["ws"].send_text(json.dumps({
            "type": "inference",
            "job_id": job_id,
            "prompt": request.prompt,
            "prefer_gpu": request.prefer_gpu,
            "params": request.params or {}
        }))
    except Exception as e:
        return {"job_id": job_id, "status": "error", "result": str(e)}

    # Wait for result (max 60s)
    for _ in range(60):
        if inference_results.get(job_id) is not None:
            break
        await asyncio.sleep(1)

    res = inference_results.pop(job_id, None)
    if res:
        return {"job_id": job_id, "status": "complete", "result": res}
    else:
        return {"job_id": job_id, "status": "timeout", "result": "Worker did not respond in time."}


# ═══════════════════════════════════════════════════════════════
# WEBSOCKET: WORKER NODES (Public — anyone can donate compute)
# ═══════════════════════════════════════════════════════════════

@app.websocket("/ws/worker")
async def worker_ws(websocket: WebSocket):
    await websocket.accept()
    worker_id = str(uuid.uuid4())[:8]
    worker_registry[worker_id] = {"ws": websocket, "connected": time.time(), "ip": websocket.client.host}
    logger.info(f"[Worker {worker_id}] Connected from {websocket.client.host}")

    try:
        while True:
            msg = await websocket.receive_text()
            data = json.loads(msg)
            if data.get("type") == "inference_result":
                inference_results[data["job_id"]] = data.get("result", "")
                logger.info(f"[Worker {worker_id}] Returned result for job {data['job_id']}")
            elif data.get("type") == "heartbeat":
                worker_registry[worker_id]["last_seen"] = time.time()
    except WebSocketDisconnect:
        logger.info(f"[Worker {worker_id}] Disconnected")
    except Exception as e:
        logger.error(f"[Worker {worker_id}] Error: {e}")
    finally:
        worker_registry.pop(worker_id, None)


# ═══════════════════════════════════════════════════════════════
# WEBSOCKET: TERMINAL (Public gets fake shell, Owner gets real PTY)
# ═══════════════════════════════════════════════════════════════

@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())[:8]

    # Check ghost cookie via WebSocket cookies
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

            done, pending = await asyncio.wait(
                [read_task, write_task],
                return_when=asyncio.FIRST_COMPLETED
            )
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
            except:
                pass
            terminal_sessions.pop(session_id, None)
        try:
            await websocket.close()
        except:
            pass


# ═══════════════════════════════════════════════════════════════
# AUTH CHECK (for UI to toggle owner features)
# ═══════════════════════════════════════════════════════════════

@app.get("/auth/check")
async def auth_check(request: Request):
    return {"owner": is_owner(request)}

# ═══════════════════════════════════════════════════════════════
# WEB UI ROUTES
# ═══════════════════════════════════════════════════════════════

@app.get("/terminal", response_class=HTMLResponse)
async def terminal_page():
    return open(os.path.join(TERMUX_STATIC, "terminal.html")).read()

@app.get("/files", response_class=HTMLResponse)
async def file_manager_page():
    return open(os.path.join(TERMUX_STATIC, "file_manager.html")).read()


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Termux Server v2.3 — The Pool")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
