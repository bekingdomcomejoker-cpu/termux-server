#!/usr/bin/env python3
"""
Termux Compute Pool — Worker Node v2.4
Model advertisement, streaming, auto-restart, hot-swap.
"""

import asyncio
import json
import os
import psutil
import sys
import time
import random
import traceback

SERVER_URL = os.environ.get("POOL_SERVER", "wss://YOUR-MANUS-URL/ws/worker")
API_KEY = os.environ.get("TERMUX_API_KEY", "")
MODEL_PATH = os.environ.get("GGUF_MODEL", "")
MODEL_FAMILY = os.environ.get("MODEL_FAMILY", "")

# Auto-restart config
MAX_RECONNECT_DELAY = 60
RECONNECT_DELAY = 5

# Try to import llama_cpp
try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except ImportError:
    LLAMA_AVAILABLE = False
    print("[Worker] llama_cpp not installed. Install with: pip install llama-cpp-python")

llm = None

def load_model(path: str):
    global llm, MODEL_FAMILY
    if not LLAMA_AVAILABLE:
        return False
    try:
        print(f"[Worker] Loading model: {path}")
        llm = Llama(model_path=path, n_ctx=2048, verbose=False)
        # Extract model family from filename
        fname = os.path.basename(path).lower()
        if "gemma" in fname:
            MODEL_FAMILY = "gemma"
        elif "llama" in fname:
            MODEL_FAMILY = "llama"
        elif "phi" in fname:
            MODEL_FAMILY = "phi"
        else:
            MODEL_FAMILY = "unknown"
        print(f"[Worker] Model loaded. Family: {MODEL_FAMILY}")
        return True
    except Exception as e:
        print(f"[Worker] Failed to load model: {e}")
        return False


def get_hardware_info():
    mem = psutil.virtual_memory()
    info = {
        "hostname": os.uname().nodename,
        "platform": sys.platform,
        "cpu_cores": psutil.cpu_count(),
        "ram_gb": round(mem.total / (1024**3), 1),
        "gpu": False,
        "model_loaded": llm is not None,
        "model_family": MODEL_FAMILY,
        "model_path": MODEL_PATH
    }
    return info


def run_inference(prompt: str, max_tokens: int = 128):
    """Run inference and yield tokens for streaming."""
    if not llm:
        yield f"[Worker {os.uname().nodename}] No model loaded. Echo: {prompt[:200]}"
        return

    try:
        output = llm(prompt, max_tokens=max_tokens, stop=["</s>", "<|end|>"], stream=True)
        for chunk in output:
            token = chunk["choices"][0]["text"]
            yield token
    except Exception as e:
        yield f"[ERROR: {e}]"


def worker_loop():
    global RECONNECT_DELAY
    import websocket

    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    while True:
        try:
            print(f"[Worker] Connecting to {SERVER_URL}...")
            ws = websocket.WebSocketApp(
                SERVER_URL,
                header=headers,
                on_open=lambda ws: on_open(ws),
                on_message=lambda ws, msg: on_message(ws, msg),
                on_error=lambda ws, err: on_error(ws, err),
                on_close=lambda ws, c, m: on_close(ws, c, m)
            )
            ws.run_forever()
        except Exception as e:
            print(f"[Worker] Connection error: {e}")

        # Exponential backoff
        delay = min(RECONNECT_DELAY, MAX_RECONNECT_DELAY)
        print(f"[Worker] Reconnecting in {delay}s...")
        time.sleep(delay)
        RECONNECT_DELAY = min(RECONNECT_DELAY * 2, MAX_RECONNECT_DELAY)


def on_open(ws):
    global RECONNECT_DELAY
    RECONNECT_DELAY = 5  # Reset backoff
    print("[Worker] Connected to pool.")
    # Register with capabilities
    ws.send(json.dumps({
        "type": "register",
        "worker_id": f"python-{os.uname().nodename}-{random.randint(1000,9999)}",
        "platform": f"Python/{sys.platform}",
        "capabilities": get_hardware_info(),
        "models": [MODEL_FAMILY] if MODEL_FAMILY else []
    }))


def on_message(ws, message):
    try:
        data = json.loads(message)
        msg_type = data.get("type")

        if msg_type in ("inference", "inference_request"):
            job_id = data.get("job_id") or data.get("task_id")
            prompt = data.get("prompt", "")
            stream = data.get("stream", False)
            max_tokens = data.get("params", {}).get("max_tokens", 128)

            print(f"[Worker] Job {job_id}: {prompt[:60]}...")

            if stream:
                # Streaming mode: send tokens as they generate
                full_result = ""
                for token in run_inference(prompt, max_tokens):
                    full_result += token
                    ws.send(json.dumps({
                        "type": "token",
                        "job_id": job_id,
                        "token": token
                    }))
                ws.send(json.dumps({
                    "type": "stream_done",
                    "job_id": job_id,
                    "result": full_result
                }))
                print(f"[Worker] Job {job_id} streamed complete.")
            else:
                # Batch mode: collect all then send
                tokens = list(run_inference(prompt, max_tokens))
                result = "".join(tokens)
                ws.send(json.dumps({
                    "type": "inference_result",
                    "job_id": job_id,
                    "result": result
                }))
                print(f"[Worker] Job {job_id} complete.")

        elif msg_type == "load_model":
            # Hot-swap model
            new_path = data.get("path", "")
            if new_path and os.path.exists(new_path):
                if load_model(new_path):
                    ws.send(json.dumps({
                        "type": "model_loaded",
                        "model": MODEL_FAMILY,
                        "path": new_path
                    }))
                else:
                    ws.send(json.dumps({
                        "type": "model_error",
                        "error": f"Failed to load {new_path}"
                    }))
            else:
                ws.send(json.dumps({
                    "type": "model_error",
                    "error": f"Model file not found: {new_path}"
                }))

        elif msg_type == "ping":
            ws.send(json.dumps({"type": "heartbeat", "capabilities": get_hardware_info()}))

    except Exception as e:
        print(f"[Worker] Message handler error: {e}")
        traceback.print_exc()


def on_error(ws, error):
    print(f"[Worker] WebSocket error: {error}")


def on_close(ws, close_status_code, close_msg):
    print(f"[Worker] Connection closed: {close_status_code} {close_msg}")


if __name__ == "__main__":
    print("=" * 60)
    print("  Termux Compute Pool — Worker Node v2.4")
    print("=" * 60)

    if MODEL_PATH and os.path.exists(MODEL_PATH):
        load_model(MODEL_PATH)
    else:
        print(f"[Worker] No model loaded. Set GGUF_MODEL env var.")
        print(f"[Worker] Will run in echo mode until a model is provided.")

    print(f"  Server: {SERVER_URL}")
    print(f"  Model:  {MODEL_PATH or 'None (echo mode)'}")
    print("=" * 60)

    try:
        worker_loop()
    except KeyboardInterrupt:
        print("\n[Worker] Shutting down.")
