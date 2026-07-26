#!/usr/bin/env python3
"""
duckai_worker.py
Duck.ai inference worker for the Termux Server compute pool.
Uses Selenium/Chromium to bypass bot detection.
"""

import asyncio
import json
import logging
import os
import sys
import time
from typing import Optional

import websockets

sys.path.insert(0, os.path.dirname(__file__))
from unified_ai_bot import DuckAIBot, BotConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("duckai_worker")

COORDINATOR_URL = os.environ.get("COORDINATOR_URL", "ws://localhost:8000/ws/worker")
WORKER_ID = os.environ.get("WORKER_ID", f"duckai-{os.getpid()}")
API_KEY = os.environ.get("WORKER_API_KEY", "")


class DuckAIWorker:
    def __init__(self):
        self.bot: Optional[DuckAIBot] = None
        self.ws = None
        self.config = BotConfig(
            headless=True,
            stealth=True,
            screenshot_on_fail=True,
            chromedriver_path=os.environ.get("CHROMEDRIVER_PATH"),
            binary_location=os.environ.get("CHROME_BINARY"),
            user_data_dir=os.environ.get("CHROME_USER_DATA_DIR"),
        )
        self.keepalive_task = None

    async def connect(self):
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY

        logger.info(f"Connecting to {COORDINATOR_URL} ...")
        self.ws = await websockets.connect(COORDINATOR_URL, additional_headers=headers)
        logger.info("Connected to coordinator")

        await self.ws.send(json.dumps({
            "type": "register",
            "worker_id": WORKER_ID,
            "capabilities": {
                "models": ["duckai-gpt4o", "duckai-claude-3-haiku", "duckai-llama-3.1", "default"],
                "max_concurrent": 1,
                "supports_streaming": False,
                "backend": "duck.ai",
                "stealth": True,
                "type": "browser_automation"
            },
            "hardware": {
                "platform": "termux" if "TERMUX_VERSION" in os.environ else "linux",
                "chrome_available": True
            }
        }))

        # Start keepalive pongs every 20s so server doesn't mark us stale
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
                    asyncio.create_task(self.handle_inference(data))

                elif msg_type == "shutdown":
                    logger.info("Shutdown requested by coordinator")
                    break

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Connection closed")
        except Exception as e:
            logger.error(f"Worker error: {e}")
        finally:
            if self.keepalive_task:
                self.keepalive_task.cancel()
            if self.bot:
                self.bot.stop()
            logger.info("Worker stopped")

    async def handle_inference(self, data: dict):
        job_id = data["job_id"]
        prompt = data["prompt"]
        model = data.get("model", "duckai-gpt4o")

        logger.info(f"Job {job_id}: processing ({len(prompt)} chars)")

        if not self.bot:
            self.bot = DuckAIBot(self.config)

        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(None, self.bot.send_message, prompt),
                timeout=120
            )

            await self.ws.send(json.dumps({
                "type": "inference_response",
                "job_id": job_id,
                "worker_id": WORKER_ID,
                "status": "success",
                "response": response,
                "model": model
            }))
            logger.info(f"Job {job_id}: success ({len(response)} chars)")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            await self.ws.send(json.dumps({
                "type": "inference_response",
                "job_id": job_id,
                "worker_id": WORKER_ID,
                "status": "error",
                "error": str(e)
            }))
            if self.bot:
                self.bot.stop()
                self.bot = None


if __name__ == "__main__":
    worker = DuckAIWorker()
    while True:
        try:
            asyncio.run(worker.run())
        except Exception as e:
            logger.error(f"Worker crashed: {e}")
            logger.info("Restarting in 10s...")
            time.sleep(10)
