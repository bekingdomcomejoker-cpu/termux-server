#!/usr/bin/env python3
"""
Termux Server API - Persistent shell environment accessible via HTTP/API
Allows calling shell commands, file operations, and package management without using credits
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import os
import json
from typing import Optional, Dict, Any
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Termux Server API", version="1.0.0")

# Environment configuration
TERMUX_HOME = "/home/ubuntu/termux-server/home"
TERMUX_TMP = "/home/ubuntu/termux-server/tmp"
TERMUX_VAR = "/home/ubuntu/termux-server/var"

# Ensure directories exist
os.makedirs(TERMUX_HOME, exist_ok=True)
os.makedirs(TERMUX_TMP, exist_ok=True)
os.makedirs(TERMUX_VAR, exist_ok=True)

class CommandRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    timeout: Optional[int] = 30

class FileRequest(BaseModel):
    path: str
    content: Optional[str] = None
    mode: Optional[str] = "r"

class PackageRequest(BaseModel):
    action: str  # install, remove, update, list
    package: Optional[str] = None

class TermuxResponse(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
    returncode: Optional[int] = None

@app.get("/")
async def root():
    """Health check and API info"""
    return {
        "service": "Termux Server API",
        "version": "1.0.0",
        "status": "running",
        "purpose": "Persistent shell environment accessible via API - No credits required",
        "endpoints": {
            "health": "GET /health",
            "execute": "POST /execute",
            "file_read": "POST /file/read",
            "file_write": "POST /file/write",
            "package": "POST /package",
            "info": "GET /info"
        }
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "service": "termux-server"}

@app.post("/execute", response_model=TermuxResponse)
async def execute_command(request: CommandRequest):
    """
    Execute a shell command in the persistent Termux environment
    """
    try:
        # Set working directory
        cwd = request.cwd or TERMUX_HOME
        
        # Prepare environment
        env = os.environ.copy()
        if request.env:
            env.update(request.env)
        env["HOME"] = TERMUX_HOME
        env["TMPDIR"] = TERMUX_TMP
        
        # Execute command
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
            error=result.stderr if result.returncode != 0 else None,
            returncode=result.returncode
        )
    
    except subprocess.TimeoutExpired:
        return TermuxResponse(
            success=False,
            output="",
            error=f"Command timed out after {request.timeout} seconds",
            returncode=-1
        )
    except Exception as e:
        return TermuxResponse(
            success=False,
            output="",
            error=str(e),
            returncode=-1
        )

@app.post("/file/read", response_model=TermuxResponse)
async def read_file(request: FileRequest):
    """
    Read a file from the persistent Termux environment
    """
    try:
        filepath = os.path.join(TERMUX_HOME, request.path.lstrip("/"))
        
        # Security: prevent path traversal
        if not os.path.abspath(filepath).startswith(TERMUX_HOME):
            raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
        
        with open(filepath, "r") as f:
            content = f.read()
        
        return TermuxResponse(
            success=True,
            output=content
        )
    except FileNotFoundError:
        return TermuxResponse(
            success=False,
            output="",
            error=f"File not found: {request.path}"
        )
    except Exception as e:
        return TermuxResponse(
            success=False,
            output="",
            error=str(e)
        )

@app.post("/file/write", response_model=TermuxResponse)
async def write_file(request: FileRequest):
    """
    Write a file to the persistent Termux environment
    """
    try:
        filepath = os.path.join(TERMUX_HOME, request.path.lstrip("/"))
        
        # Security: prevent path traversal
        if not os.path.abspath(filepath).startswith(TERMUX_HOME):
            raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
        
        # Create parent directories if needed
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, "w") as f:
            f.write(request.content or "")
        
        return TermuxResponse(
            success=True,
            output=f"File written: {request.path}"
        )
    except Exception as e:
        return TermuxResponse(
            success=False,
            output="",
            error=str(e)
        )

@app.post("/package", response_model=TermuxResponse)
async def manage_package(request: PackageRequest):
    """
    Manage packages (install, remove, update, list)
    """
    try:
        if request.action == "install":
            if not request.package:
                raise ValueError("Package name required for install")
            cmd = f"apt-get install -y {request.package}"
        elif request.action == "remove":
            if not request.package:
                raise ValueError("Package name required for remove")
            cmd = f"apt-get remove -y {request.package}"
        elif request.action == "update":
            cmd = "apt-get update"
        elif request.action == "list":
            cmd = "apt list --installed"
        else:
            raise ValueError(f"Unknown action: {request.action}")
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        return TermuxResponse(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.returncode != 0 else None,
            returncode=result.returncode
        )
    
    except Exception as e:
        return TermuxResponse(
            success=False,
            output="",
            error=str(e)
        )

@app.get("/info")
async def get_info():
    """
    Get information about the Termux server environment
    """
    try:
        uname = subprocess.run("uname -a", shell=True, capture_output=True, text=True).stdout
        pwd = subprocess.run("pwd", shell=True, capture_output=True, text=True).stdout
        
        return {
            "home": TERMUX_HOME,
            "tmp": TERMUX_TMP,
            "var": TERMUX_VAR,
            "system": uname.strip(),
            "current_dir": pwd.strip(),
            "python_version": __import__("sys").version
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
