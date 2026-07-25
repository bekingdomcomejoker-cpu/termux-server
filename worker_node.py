#!/usr/bin/env python3
"""
Termux Server - Universal Worker Node v2.0
Cross-platform: Windows, Linux, Android (Termux).
Supports GPU (CUDA/ROCm) and CPU-only (GGUF) inference.
"""

import os
import sys
import time
import json
import uuid
import platform
import requests
import threading
import websocket
import multiprocessing
from typing import Dict, Any

# ── Configuration ──────────────────────────────────────────────
SERVER_URL = "https://8000-i0nugvn3w77z3rlgv7bzk-5ae40618.us1.manus.computer"
WORKER_ID = f"worker-{platform.node()}-{uuid.uuid4().hex[:4]}"
API_KEY = os.environ.get("TERMUX_API_KEY", None)

# Detection
HAS_GPU = False
try:
    import subprocess
    # Simple check for NVIDIA GPU
    subprocess.run(["nvidia-smi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    HAS_GPU = True
except:
    HAS_GPU = False

CPU_CORES = multiprocessing.cpu_count()
# ───────────────────────────────────────────────────────────────

def perform_inference(prompt: str, params: Dict[str, Any]) -> str:
    """
    Inference Logic:
    - If HAS_GPU: Use high-performance engine.
    - If CPU-only: Use llama-cpp-python or similar with GGUF models.
    """
    mode = "GPU" if HAS_GPU else "CPU"
    print(f"[*] [{mode}] Processing prompt: {prompt[:50]}...")
    
    # Placeholder for actual inference call:
    # Example for CPU (GGUF):
    # from llama_cpp import Llama
    # llm = Llama(model_path="model.gguf", n_threads=CPU_CORES)
    # output = llm(prompt, max_tokens=params.get("max_tokens", 128))
    
    # Simulate processing time based on complexity
    time.sleep(1 if HAS_GPU else 3)
    
    return f"[Worker {WORKER_ID}] [{mode}] Result for: {prompt}"

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
    registration = {
        "type": "worker_registration",
        "worker_id": WORKER_ID,
        "platform": platform.system(),
        "capabilities": {
            "has_gpu": HAS_GPU,
            "cpu_cores": CPU_CORES,
            "ram_gb": round(psutil.virtual_memory().total / (1024**3), 1) if 'psutil' in sys.modules else "Unknown"
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
    print(f"=== Termux Server Universal Worker v2.0 ===")
    print(f"[*] OS: {platform.system()} | CPU Cores: {CPU_CORES} | GPU: {HAS_GPU}")
    
    # Check dependencies
    deps_ok = True
    try: import websocket
    except: 
        print("[!] Missing 'websocket-client'. Run: pip install websocket-client")
        deps_ok = False
    try: import psutil
    except: 
        print("[!] Missing 'psutil'. Run: pip install psutil")
        deps_ok = False
        
    if not deps_ok: sys.exit(1)
    
    connect_to_server()
