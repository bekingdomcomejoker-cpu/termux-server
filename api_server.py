#!/usr/bin/env python3
"""
Termux Server API v2.1
Integrated web terminal, file manager, process control, task scheduler,
and Distributed GPU Worker Node support.
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import subprocess
import os
import json
import asyncio
import threading
import pty
import select
import signal
import psutil
import uuid
import time
from datetime import datetime
from pathlib import Path
import logging

# Optional: APScheduler for cron jobs
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/home/ubuntu/termux-server/var/log/api.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Termux Server API v2.1", version="2.1.0")

# Environment configuration
TERMUX_HOME = "/home/ubuntu/termux-server/home"
TERMUX_TMP = "/home/ubuntu/termux-server/tmp"
TERMUX_VAR = "/home/ubuntu/termux-server/var"
TERMUX_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Auth config (set via env var)
API_KEY = os.environ.get("TERMUX_API_KEY", None)

# Ensure directories exist
for d in [TERMUX_HOME, TERMUX_TMP, TERMUX_VAR]:
    os.makedirs(d, exist_ok=True)

# Scheduler setup
scheduled_jobs: Dict[str, Dict] = {}
if SCHEDULER_AVAILABLE:
    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("Task scheduler started")
else:
    scheduler = None
    logger.warning("APScheduler not installed. Run: pip install apscheduler")

# Active terminal sessions
terminal_sessions: Dict[str, Dict] = {}

# Distributed Worker Nodes
worker_nodes: Dict[str, WebSocket] = {}
pending_tasks: Dict[str, asyncio.Future] = {}

# ============== AUTH ==============
async def verify_key(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return True

# ============== MODELS ==============
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
    cron: str  # e.g. "*/5 * * * *"
    enabled: bool = True

class InferenceRequest(BaseModel):
    prompt: str
    params: Optional[Dict[str, Any]] = None
    worker_id: Optional[str] = None

class TermuxResponse(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
    returncode: Optional[int] = None

# ============== HELPERS ==============
def resolve_path(filepath: str) -> str:
    """Resolve a path relative to TERMUX_HOME with traversal protection."""
    full = os.path.join(TERMUX_HOME, filepath.lstrip("/"))
    resolved = os.path.abspath(full)
    if not resolved.startswith(os.path.abspath(TERMUX_HOME)):
        raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
    return resolved

# ============== BASIC ENDPOINTS ==============
@app.get("/", response_class=HTMLResponse)
async def root():
    return open(os.path.join(TERMUX_STATIC, "index.html")).read()

@app.get("/health")
async def health():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "status": "healthy",
        "service": "termux-server",
        "uptime": time.time() - psutil.boot_time(),
        "memory": {"total": mem.total, "available": mem.available, "percent": mem.percent},
        "disk": {"total": disk.total, "free": disk.free, "percent": disk.percent},
        "workers": len(worker_nodes)
    }

@app.get("/info")
async def get_info():
    uname = subprocess.run("uname -a", shell=True, capture_output=True, text=True).stdout.strip()
    return {
        "home": TERMUX_HOME,
        "tmp": TERMUX_TMP,
        "var": TERMUX_VAR,
        "system": uname,
        "python_version": __import__("sys").version,
        "cpu_count": os.cpu_count(),
        "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else None,
        "workers": list(worker_nodes.keys())
    }

# ============== COMMAND EXECUTION ==============
@app.post("/execute", response_model=TermuxResponse)
async def execute_command(request: CommandRequest):
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

# ============== DISTRIBUTED INFERENCE ==============
@app.post("/inference")
async def run_inference(request: InferenceRequest):
    if not worker_nodes:
        raise HTTPException(status_code=503, detail="No active worker nodes available")
    
    target_worker = request.worker_id or next(iter(worker_nodes))
    if target_worker not in worker_nodes:
        raise HTTPException(status_code=404, detail=f"Worker {target_worker} not found")
    
    task_id = str(uuid.uuid4())[:8]
    task_future = asyncio.get_event_loop().create_future()
    pending_tasks[task_id] = task_future
    
    payload = {
        "type": "inference_request",
        "task_id": task_id,
        "prompt": request.prompt,
        "params": request.params or {}
    }
    
    try:
        await worker_nodes[target_worker].send_text(json.dumps(payload))
        # Wait for result from worker (timeout after 60s)
        result = await asyncio.wait_for(task_future, timeout=60.0)
        return {"success": True, "task_id": task_id, "worker": target_worker, "result": result}
    except asyncio.TimeoutError:
        pending_tasks.pop(task_id, None)
        raise HTTPException(status_code=504, detail="Worker timed out")
    except Exception as e:
        pending_tasks.pop(task_id, None)
        raise HTTPException(status_code=500, detail=str(e))

# ============== WEBSOCKET WORKER ==============
@app.websocket("/ws/worker")
async def websocket_worker(websocket: WebSocket):
    await websocket.accept()
    worker_id = None
    logger.info("[Worker] Attempting connection")
    
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg.get("type") == "worker_registration":
                worker_id = msg.get("worker_id")
                worker_nodes[worker_id] = websocket
                logger.info(f"[Worker {worker_id}] Registered")
                
            elif msg.get("type") == "inference_response":
                task_id = msg.get("task_id")
                result = msg.get("result")
                if task_id in pending_tasks:
                    pending_tasks[task_id].set_result(result)
                    pending_tasks.pop(task_id)
                    
    except WebSocketDisconnect:
        if worker_id:
            worker_nodes.pop(worker_id, None)
            logger.info(f"[Worker {worker_id}] Disconnected")
    except Exception as e:
        logger.error(f"[Worker] Error: {e}")
        if worker_id:
            worker_nodes.pop(worker_id, None)

# ============== FILE OPERATIONS ==============
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
async def write_file(request: FileRequest):
    try:
        filepath = resolve_path(request.path)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            f.write(request.content or "")
        return TermuxResponse(success=True, output=f"File written: {request.path}")
    except Exception as e:
        return TermuxResponse(success=False, output="", error=str(e))

@app.post("/file/upload")
async def upload_file(path: str = Form(...), file: UploadFile = File(...)):
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
async def delete_file(path: str):
    try:
        filepath = resolve_path(path)
        if os.path.isdir(filepath):
            os.rmdir(filepath)
        else:
            os.remove(filepath)
        return {"success": True, "output": f"Deleted: {path}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============== PACKAGE MANAGEMENT ==============
@app.post("/package", response_model=TermuxResponse)
async def manage_package(request: PackageRequest):
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

# ============== PROCESS MANAGEMENT ==============
@app.get("/processes")
async def list_processes():
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
async def kill_process(pid: int):
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

# ============== TASK SCHEDULER ==============
@app.post("/schedule")
async def create_schedule(request: ScheduleRequest):
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
            "id": job_id,
            "name": request.name,
            "command": request.command,
            "cron": request.cron,
            "enabled": request.enabled,
            "created": datetime.now().isoformat()
        }
        return {"success": True, "job_id": job_id, "next_run": str(job.next_run_time) if job.next_run_time else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/schedule")
async def list_schedules():
    if not SCHEDULER_AVAILABLE:
        return {"success": False, "error": "Scheduler not available", "jobs": []}
    jobs = []
    for job in scheduler.get_jobs():
        info = scheduled_jobs.get(job.id, {})
        jobs.append({
            "id": job.id,
            "name": info.get("name", job.name),
            "command": info.get("command", ""),
            "cron": info.get("cron", ""),
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "enabled": job.next_run_time is not None
        })
    return {"success": True, "jobs": jobs}

@app.delete("/schedule/{job_id}")
async def delete_schedule(job_id: str):
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        scheduler.remove_job(job_id)
        scheduled_jobs.pop(job_id, None)
        return {"success": True, "output": f"Job {job_id} removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============== WEBSOCKET TERMINAL ==============
@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())[:8]
    logger.info(f"[Terminal {session_id}] Connected")

    try:
        master_fd, slave_fd = pty.openpty()
        pid = os.fork()

        if pid == 0:
            # Child: spawn bash
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
            # Parent: bridge WebSocket <-> PTY
            os.close(slave_fd)
            terminal_sessions[session_id] = {"pid": pid, "fd": master_fd, "ws": websocket}

            # Set non-blocking
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
                        data = await websocket.receive_text()
                        os.write(master_fd, data.encode())
                    except WebSocketDisconnect:
                        break
                    except Exception:
                        break

            # Run both bridge tasks
            await asyncio.gather(read_from_pty(), write_to_pty())

    except WebSocketDisconnect:
        logger.info(f"[Terminal {session_id}] Disconnected")
    finally:
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        terminal_sessions.pop(session_id, None)

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Termux Server API v2.1")
    uvicorn.run(app, host="0.0.0.0", port=8000)
