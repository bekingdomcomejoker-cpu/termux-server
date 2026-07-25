#!/usr/bin/env python3
"""
Termux Server - Universal Worker Node v2.3
Supports real LLM inference via llama-cpp-python (CPU/GPU).
"""

import os
import sys
import time
import json
import uuid
import platform
import threading
import websocket
import multiprocessing
from typing import Dict, Any

# ── Configuration ──────────────────────────────────────────────
SERVER_URL = "https://8000-i0nugvn3w77z3rlgv7bzk-5ae40618.us1.manus.computer"
WORKER_ID = f"worker-{platform.node()}-{uuid.uuid4().hex[:4]}"
API_KEY = os.environ.get("TERMUX_API_KEY", None)

# Model Path (GGUF format)
MODEL_PATH = os.environ.get("MODEL_PATH", "models/tiny-llama-1.1b.Q4_K_M.gguf")

# Global LLM instance
llm = None

def load_model():
    global llm
    try:
        from llama_cpp import Llama
        print(f"[*] Loading model from {MODEL_PATH}...")
        llm = Llama(
            model_path=MODEL_PATH,
            n_ctx=2048,
            n_threads=multiprocessing.cpu_count(),
            n_gpu_layers=-1 if HAS_GPU else 0,
            verbose=False
        )
        print("[+] Model loaded successfully.")
    except Exception as e:
        print(f"[!] Failed to load model: {e}")

# Detection
HAS_GPU = False
try:
    import subprocess
    subprocess.run(["nvidia-smi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    HAS_GPU = True
except:
    HAS_GPU = False

CPU_CORES = multiprocessing.cpu_count()
# ───────────────────────────────────────────────────────────────

def perform_inference(prompt: str, params: Dict[str, Any]) -> str:
    global llm
    if llm is None:
        return "Error: Model not loaded on worker."
    
    mode = "GPU" if HAS_GPU else "CPU"
    print(f"[*] [{mode}] Processing prompt...")
    
    try:
        output = llm(
            f"Q: {prompt}\nA:",
            max_tokens=params.get("max_tokens", 128),
            stop=["Q:", "\n"],
            echo=False
        )
        result = output['choices'][0]['text'].strip()
        return result
    except Exception as e:
        return f"Inference Error: {str(e)}"

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("type") == "inference_request":
            task_id = data.get("task_id")
            prompt = data.get("prompt")
            params = data.get("params", {})
            
            def run_task():
                result = perform_inference(prompt, params)
                response = {
                    "type": "inference_response",
                    "task_id": task_id,
                    "worker_id": WORKER_ID,
                    "result": result
                }
                ws.send(json.dumps(response))
                print(f"[+] Task {task_id} completed.")

            threading.Thread(target=run_task).start()
            
    except Exception as e:
        print(f"[!] Error: {e}")

def on_error(ws, error):
    print(f"[!] WS Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("[*] Connection lost. Retrying...")
    time.sleep(5)
    connect_to_server()

def on_open(ws):
    print(f"[+] Connected to Termux Server as {WORKER_ID}")
    import psutil
    registration = {
        "type": "worker_registration",
        "worker_id": WORKER_ID,
        "platform": platform.system(),
        "capabilities": {
            "has_gpu": HAS_GPU,
            "cpu_cores": CPU_CORES,
            "ram_gb": round(psutil.virtual_memory().total / (1024**3), 1),
            "model": MODEL_PATH
        }
    }
    ws.send(json.dumps(registration))

def connect_to_server():
    ws_url = SERVER_URL.replace("http", "ws").rstrip("/") + "/ws/worker"
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    ws = websocket.WebSocketApp(
        ws_url, header=headers,
        on_open=on_open, on_message=on_message,
        on_error=on_error, on_close=on_close
    )
    ws.run_forever()

if __name__ == "__main__":
    print(f"=== Termux Server Universal Worker v2.3 ===")
    
    # Check dependencies
    try:
        import llama_cpp
        import websocket
        import psutil
    except ImportError:
        print("[!] Missing dependencies. Run: pip install llama-cpp-python websocket-client psutil")
        sys.exit(1)
        
    load_model()
    connect_to_server()
