#!/usr/bin/env python3
"""
worker_node.py
Generic compute worker for the Termux Server pool.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from typing import Optional

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("worker_node")

COORDINATOR_URL = os.environ.get("COORDINATOR_URL", "ws://localhost:8000/ws/worker")
WORKER_ID = os.environ.get("WORKER_ID", f"node-{os.getpid()}")
API_KEY = os.environ.get("WORKER_API_KEY", "")


def get_hardware_info() -> dict:
    info = {"platform": "termux" if "TERMUX_VERSION" in os.environ else "linux"}
    try:
        result = subprocess.run(["nproc"], capture_output=True, text=True)
        info["cores"] = int(result.stdout.strip())
    except Exception:
        info["cores"] = os.cpu_count() or 1
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    info["ram_kb"] = int(line.split()[1])
                    break
    except Exception:
        pass
    return info


class GenericWorker:
    def __init__(self):
        self.ws = None
        self.hardware = get_hardware_info()
        self.keepalive_task = None

    async def connect(self):
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        self.ws = await websockets.connect(COORDINATOR_URL, additional_headers=headers)
        logger.info(f"Connected to coordinator")

        await self.ws.send(json.dumps({
            "type": "register",
            "worker_id": WORKER_ID,
            "capabilities": {
                "models": ["local-shell", "default"],
                "max_concurrent": self.hardware.get("cores", 1),
                "supports_streaming": False,
                "backend": "shell",
                "type": "compute_node"
            },
            "hardware": self.hardware
        }))

        self.keepalive_task = asyncio.create_task(self._keepalive())

    async def _keepalive(self):
        while True:
            await asyncio.sleep(20)
            if self.ws and self.ws.open:
                try:
                    await self.ws.send(json.dumps({
                        "type": "pong",
                        "worker_id": WORKER_ID,
                        "timestamp": time.time()
                    }))
                except Exception:
                    break

    async def run(self):
        await self.connect()
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue
                msg_type = data.get("type")

                if msg_type == "ping":
                    await self.ws.send(json.dumps({
                        "type": "pong",
                        "worker_id": WORKER_ID,
                        "timestamp": time.time()
                    }))

                elif msg_type == "inference_request":
                    asyncio.create_task(self.handle_job(data))

                elif msg_type == "shutdown":
                    break

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Connection closed")
        finally:
            if self.keepalive_task:
                self.keepalive_task.cancel()
            logger.info("Worker stopped")

    async def handle_job(self, data: dict):
        job_id = data["job_id"]
        prompt = data["prompt"]
        logger.info(f"Job {job_id}: executing shell task")

        allowed = ["echo", "cat", "ls", "pwd", "uname", "date", "python3", "node"]
        cmd = prompt.strip()
        first_word = cmd.split()[0] if cmd.split() else ""

        if first_word not in allowed and not cmd.startswith("python3 -c"):
            await self.ws.send(json.dumps({
                "type": "inference_response",
                "job_id": job_id,
                "worker_id": WORKER_ID,
                "status": "error",
                "error": f"Command '{first_word}' not in allowed list"
            }))
            return

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                ),
                timeout=35
            )
            output = result.stdout or result.stderr or "(no output)"
            await self.ws.send(json.dumps({
                "type": "inference_response",
                "job_id": job_id,
                "worker_id": WORKER_ID,
                "status": "success",
                "response": output,
                "returncode": result.returncode
            }))
        except Exception as e:
            await self.ws.send(json.dumps({
                "type": "inference_response",
                "job_id": job_id,
                "worker_id": WORKER_ID,
                "status": "error",
                "error": str(e)
            }))


if __name__ == "__main__":
    worker = GenericWorker()
    while True:
        try:
            asyncio.run(worker.run())
        except Exception as e:
            logger.error(f"Worker crashed: {e}")
            time.sleep(10)
