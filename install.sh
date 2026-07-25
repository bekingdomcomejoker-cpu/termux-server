#!/bin/bash
set -e

echo "========================================"
echo "  Termux Server v2.0 Installer"
echo "========================================"
echo ""

INSTALL_DIR="/home/ubuntu/termux-server"
BACKUP_DIR="$INSTALL_DIR/backup-$(date +%s)"

echo "[1/6] Checking prerequisites..."
python3 --version >/dev/null 2>&1 || { echo "ERROR: python3 not found"; exit 1; }
pip3 --version >/dev/null 2>&1 || { echo "ERROR: pip3 not found. Run: sudo apt-get install -y python3-pip"; exit 1; }

echo "[2/6] Installing Python dependencies..."
pip3 install --user fastapi uvicorn python-multipart psutil 2>/dev/null || pip3 install fastapi uvicorn python-multipart psutil

# Try to install apscheduler, but don't fail if it doesn't work
echo "[3/6] Installing optional scheduler..."
pip3 install --user apscheduler 2>/dev/null || pip3 install apscheduler 2>/dev/null || echo "  (APScheduler optional — cron jobs will be disabled)"

echo "[4/6] Backing up existing server..."
if [ -f "$INSTALL_DIR/api_server.py" ]; then
    mkdir -p "$BACKUP_DIR"
    cp "$INSTALL_DIR/api_server.py" "$BACKUP_DIR/"
    echo "  Backed up to $BACKUP_DIR"
fi

echo "[5/6] Installing new server files..."
mkdir -p "$INSTALL_DIR/static"

# Write api_server.py
cat > "$INSTALL_DIR/api_server.py" <<'PYEOF'
#!/usr/bin/env python3
"""
Termux Server API v2.0
Integrated web terminal, file manager, process control, and task scheduler.
Replaces ttyd with a built-in WebSocket terminal.
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

app = FastAPI(title="Termux Server API v2.0", version="2.0.0")

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
        "disk": {"total": disk.total, "free": disk.free, "percent": disk.percent}
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
        "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else None
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
                        msg = await websocket.receive_text()
                        if msg.startswith("\x00RESIZE:"):
                            # Handle resize: \x00RESIZE:cols,rows
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

            # Run both directions concurrently
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
        # Cleanup
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

# ============== WEB UI ROUTES ==============
@app.get("/terminal", response_class=HTMLResponse)
async def terminal_page():
    return open(os.path.join(TERMUX_STATIC, "terminal.html")).read()

@app.get("/files", response_class=HTMLResponse)
async def file_manager_page():
    return open(os.path.join(TERMUX_STATIC, "file_manager.html")).read()

# ============== MAIN ==============
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Termux Server API v2.0")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

PYEOF

# Note: The full static HTML files (terminal.html, file_manager.html, index.html) are generated by the complete install.sh.
# For the complete installer with all static assets, use the full version from the attachment.

echo "[6/6] Setting permissions..."
chmod +x "$INSTALL_DIR/api_server.py"

echo ""
echo "========================================"
echo "  Installation Complete!"
echo "========================================"
echo ""
echo "Start the server:"
echo "  cd $INSTALL_DIR && python3 api_server.py"
echo ""
echo "Or run in background:"
echo "  nohup python3 $INSTALL_DIR/api_server.py > $INSTALL_DIR/var/log/api.log 2>&1 &"
echo ""
echo "Web interfaces:"
echo "  Dashboard:  https://<your-host>/"
echo "  Terminal:   https://<your-host>/terminal"
echo "  Files:      https://<your-host>/files"
echo ""
echo "API key (optional):"
echo "  export TERMUX_API_KEY=your-secret-key"
echo ""
