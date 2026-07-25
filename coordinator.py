#!/usr/bin/env python3
"""
coordinator.py
Standalone coordinator for multi-instance Termux Server pools.
Can also be imported and used inside api_server.py.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Optional
from dataclasses import dataclass, field

import websockets
from websockets.server import WebSocketServerProtocol

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("coordinator")


@dataclass
class Worker:
    ws: WebSocketServerProtocol
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


class Coordinator:
    def __init__(self, host: str = "0.0.0.0", port: int = 8001):
        self.host = host
        self.port = port
        self.workers: Dict[str, Worker] = {}
        self.jobs: Dict[str, Job] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.pending_futures: Dict[str, asyncio.Future] = {}

    async def register_worker(self, ws: WebSocketServerProtocol, data: dict):
        worker_id = data.get("worker_id", f"anon-{id(ws)}")
        caps = data.get("capabilities", {})
        self.workers[worker_id] = Worker(ws, worker_id, caps, time.time())
        logger.info(f"Worker registered: {worker_id} — {caps.get('models', [])}")
        await ws.send(json.dumps({"type": "registered", "worker_id": worker_id}))

    async def unregister_worker(self, worker_id: str):
        if worker_id in self.workers:
            del self.workers[worker_id]
            logger.info(f"Worker unregistered: {worker_id}")

    async def submit_job(self, prompt: str, model: str = "default") -> str:
        import secrets
        job_id = secrets.token_hex(8)
        job = Job(job_id=job_id, prompt=prompt, model=model)
        self.jobs[job_id] = job
        future = asyncio.get_event_loop().create_future()
        self.pending_futures[job_id] = future
        await self.queue.put(job_id)
        logger.info(f"Job {job_id} queued")
        return job_id, future

    async def route_jobs(self):
        while True:
            job_id = await self.queue.get()
            job = self.jobs.get(job_id)
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

            worker = capable[0]
            worker.current_job = job_id
            job.status = "assigned"
            job.worker_id = worker.worker_id

            try:
                await worker.ws.send(json.dumps({
                    "type": "inference_request",
                    "job_id": job_id,
                    "prompt": job.prompt,
                    "model": job.model
                }))
            except Exception as e:
                logger.error(f"Failed to route job {job_id} to {worker.worker_id}: {e}")
                worker.current_job = None
                await self.queue.put(job_id)

    async def handle_worker(self, ws: WebSocketServerProtocol, path: str):
        worker_id = None
        try:
            async for message in ws:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "register":
                    worker_id = data.get("worker_id")
                    await self.register_worker(ws, data)

                elif msg_type == "pong":
                    wid = data.get("worker_id")
                    if wid in self.workers:
                        self.workers[wid].last_ping = time.time()

                elif msg_type == "inference_response":
                    wid = data.get("worker_id")
                    jid = data.get("job_id")
                    if jid in self.pending_futures:
                        self.pending_futures[jid].set_result(data.get("response"))
                        del self.pending_futures[jid]
                    if wid in self.workers:
                        self.workers[wid].current_job = None
                    if jid in self.jobs:
                        self.jobs[jid].status = "completed"
                        self.jobs[jid].response = data.get("response")
                        self.jobs[jid].completed_at = time.time()

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if worker_id:
                await self.unregister_worker(worker_id)

    async def cleanup_stale(self):
        while True:
            await asyncio.sleep(30)
            now = time.time()
            stale = [wid for wid, w in self.workers.items() if now - w.last_ping > 60]
            for wid in stale:
                logger.info(f"Removing stale worker {wid}")
                await self.unregister_worker(wid)

    async def start(self):
        logger.info(f"Coordinator starting on ws://{self.host}:{self.port}")
        asyncio.create_task(self.route_jobs())
        asyncio.create_task(self.cleanup_stale())
        async with websockets.serve(self.handle_worker, self.host, self.port):
            await asyncio.Future()


if __name__ == "__main__":
    import os
    host = os.environ.get("COORDINATOR_HOST", "0.0.0.0")
    port = int(os.environ.get("COORDINATOR_PORT", "8001"))
    c = Coordinator(host=host, port=port)
    asyncio.run(c.start())