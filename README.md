# Termux Server v2.2 — Universal "Any-CPU" Distributed Cluster

A complete rewrite of the Termux Server with an **integrated web terminal**, **file manager**, **process monitor**, **task scheduler**, **dashboard**, and **Universal Distributed Worker support**.

---

## 🚀 What's New in v2.2: The "Any-CPU" Workaround

You can now harness the power of **any device**—PCs, laptops, old Android phones, or tablets—to build a massive distributed compute cluster for free.

| Feature | v2.1 | v2.2 |
|---------|------|------|
| Device Support | GPU-only focus | **Universal (Windows, Linux, Android/Termux)** |
| Hardware Detection | Manual | **Auto-detects CPU cores, RAM, and GPU** |
| Intelligent Routing | Random worker | **Prefers GPU; falls back to sharding across CPUs** |

---

## 📦 Quick Install

```bash
git clone https://github.com/bekingdomcomejoker-cpu/termux-server.git
cd termux-server
bash install.sh
nohup python3 api_server.py > var/log/api.log 2>&1 &
```

---

## 🛠️ Setting Up the Universal Worker Node

Run this on **any** device you want to add to your cluster.

1.  **Install dependencies**:
    ```bash
    pip install websocket-client psutil requests
    ```
2.  **Run the worker**:
    ```bash
    # Download worker_node.py and set SERVER_URL inside
    python worker_node.py
    ```

### Why this works (The "Backdoor" Principle)
This setup leverages the fact that modern CPUs (Intel/AMD/ARM) are designed for background task handling. By running the worker at a low priority, it utilizes "idle cycles" to perform LLM inference without interrupting the owner's work. It's the software equivalent of a distributed mining rig.

---

## 🔌 API Endpoints

### Core
```bash
GET  /health          # Cluster health + GPU/CPU worker counts
GET  /info            # Detailed worker list and hardware caps
POST /execute         # Run shell commands
```

### Distributed Inference
```bash
POST /inference  
{
  "prompt": "Explain quantum physics",
  "prefer_gpu": true,
  "params": {"max_tokens": 256}
}
```

---

## 🚀 Multi-Instance Management
Use `coordinator.py` to manage multiple Termux Server "Command Centers" across different accounts.

---

## 📄 License
MIT
