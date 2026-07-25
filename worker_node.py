#!/usr/bin/env python3
"""
Termux Server - Distributed Worker Node v1.0
Connects to a central Termux Server and performs GPU/CPU inference tasks.
"""

import os
import time
import json
import uuid
import requests
import threading
import websocket
from typing import Dict, Any

# ── Configuration ──────────────────────────────────────────────
SERVER_URL = "https://8000-i0nugvn3w77z3rlgv7bzk-5ae40618.us1.manus.computer"
WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"
# Optional: API Key for the Termux Server
API_KEY = os.environ.get("TERMUX_API_KEY", None)

# Inference Engine Settings (e.g., for llama-cpp-python or similar)
# For this demo, we use a mock inference function.
# In production, replace this with actual model loading and inference logic.
# ───────────────────────────────────────────────────────────────

def perform_inference(prompt: str, model_params: Dict[str, Any]) -> str:
    """
    Actual inference logic goes here.
    Example: use llama-cpp-python, transformers, or ollama API.
    """
    print(f"[*] Processing prompt: {prompt[:50]}...")
    # Simulate processing time
    time.sleep(2)
    return f"[Worker {WORKER_ID}] Processed result for: {prompt}"

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("type") == "inference_request":
            task_id = data.get("task_id")
            prompt = data.get("prompt")
            params = data.get("params", {})
            
            # Run inference in a separate thread to not block the WS
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
        print(f"[!] Error handling message: {e}")

def on_error(ws, error):
    print(f"[!] WebSocket Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("[*] Connection closed. Retrying in 5 seconds...")
    time.sleep(5)
    connect_to_server()

def on_open(ws):
    print(f"[+] Connected to Termux Server as {WORKER_ID}")
    # Register worker
    registration = {
        "type": "worker_registration",
        "worker_id": WORKER_ID,
        "capabilities": {
            "has_gpu": True, # Assume True for this script
            "vram_gb": 8,
            "engine": "mock-inference-v1"
        }
    }
    ws.send(json.dumps(registration))

def connect_to_server():
    ws_url = SERVER_URL.replace("http", "ws").rstrip("/") + "/ws/worker"
    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
        
    ws = websocket.WebSocketApp(
        ws_url,
        header=headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()

if __name__ == "__main__":
    print(f"=== Termux Server Worker Node {WORKER_ID} ===")
    print(f"[*] Connecting to: {SERVER_URL}")
    
    # Check for requirements
    try:
        import websocket
    except ImportError:
        print("[!] Missing 'websocket-client'. Run: pip install websocket-client")
        exit(1)
        
    connect_to_server()
