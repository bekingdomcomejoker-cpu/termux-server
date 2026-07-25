#!/usr/bin/env python3
"""
Termux Compute Pool — Worker Node
Donate idle CPU/GPU cycles to the pool.
"""

import asyncio
import json
import os
import psutil
import sys
import time
import websocket

SERVER_URL = os.environ.get("POOL_SERVER", "wss://YOUR-MANUS-URL/ws/worker")
API_KEY = os.environ.get("TERMUX_API_KEY", "")

# Try to import llama_cpp for local inference
try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except ImportError:
    LLAMA_AVAILABLE = False
    print("[Worker] llama_cpp not installed. Install with: pip install llama-cpp-python")

MODEL_PATH = os.environ.get("GGUF_MODEL", "")
llm = None

if LLAMA_AVAILABLE and MODEL_PATH and os.path.exists(MODEL_PATH):
    try:
        print(f"[Worker] Loading model: {MODEL_PATH}")
        llm = Llama(model_path=MODEL_PATH, n_ctx=2048, verbose=False)
        print("[Worker] Model loaded.")
    except Exception as e:
        print(f"[Worker] Failed to load model: {e}")


def get_hardware_info():
    mem = psutil.virtual_memory()
    info = {
        "hostname": os.uname().nodename,
        "platform": sys.platform,
        "cpu_cores": psutil.cpu_count(),
        "ram_gb": round(mem.total / (1024**3), 1),
        "gpu": False,  # Extend with torch/pynvml if needed
        "model_loaded": llm is not None
    }
    return info


def on_message(ws, message):
    data = json.loads(message)
    if data.get("type") == "inference":
        job_id = data["job_id"]
        prompt = data["prompt"]
        print(f"[Worker] Job {job_id}: {prompt[:60]}...")

        if llm:
            try:
                max_tokens = data.get("params", {}).get("max_tokens", 128)
                result = llm(prompt, max_tokens=max_tokens, stop=["</s>"])
                text = result["choices"][0]["text"]
                ws.send(json.dumps({"type": "inference_result", "job_id": job_id, "result": text}))
                print(f"[Worker] Job {job_id} complete.")
                return
            except Exception as e:
                print(f"[Worker] Inference error: {e}")

        # Fallback: echo back if no model
        ws.send(json.dumps({
            "type": "inference_result",
            "job_id": job_id,
            "result": f"[Worker {os.uname().nodename}] No model loaded. Echo: {prompt[:100]}"
        }))


def on_open(ws):
    print(f"[Worker] Connected to pool: {SERVER_URL}")
    ws.send(json.dumps({"type": "heartbeat", "hardware": get_hardware_info()}))


def on_close(ws, close_status_code, close_msg):
    print("[Worker] Disconnected. Reconnecting in 5s...")
    time.sleep(5)
    start_worker()


def on_error(ws, error):
    print(f"[Worker] Error: {error}")


def start_worker():
    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    ws = websocket.WebSocketApp(
        SERVER_URL,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
        on_error=on_error
    )
    ws.run_forever()


if __name__ == "__main__":
    print("=" * 50)
    print("  Termux Compute Pool — Worker Node")
    print("=" * 50)
    print(f"  Server: {SERVER_URL}")
    print(f"  Model:  {MODEL_PATH or 'None (echo mode)'}")
    print("=" * 50)
    start_worker()
