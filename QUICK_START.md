# Termux Server - Quick Start Guide

## 🎯 Three Ways to Access Your Server

### 1️⃣ REST API (Best for Automation & Kai 9000)
```bash
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "your-command-here"}'
```

### 2️⃣ Web Terminal (Best for Interactive Work)
Open in browser: `https://3333-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer`

### 3️⃣ SSH (Best for Traditional Terminal Users)
```bash
# Install chisel on your machine
curl -sSL https://i.jpillora.com/chisel! | sudo bash

# Connect to the tunnel
chisel client https://3001-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer 1080:socks

# In another terminal, SSH through the tunnel
ssh -o "ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p" ubuntu@localhost -p 2222
# Password: termux123
```

---

## 📋 Common Tasks

### Install a Package
```bash
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/package \
  -H "Content-Type: application/json" \
  -d '{"action": "install", "package": "git"}'
```

### Run a Command
```bash
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "ls -la"}'
```

### Save a File
```bash
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/file/write \
  -H "Content-Type: application/json" \
  -d '{"path": "myfile.txt", "content": "Hello World"}'
```

### Read a File
```bash
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/file/read \
  -H "Content-Type: application/json" \
  -d '{"path": "myfile.txt"}'
```

### Check Server Status
```bash
curl https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/health
```

---

## 🚀 Getting Started with Kai 9000

Tell Kai 9000:

> "Execute this command on my Termux Server: `curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute -H 'Content-Type: application/json' -d '{\"command\": \"echo Hello from Kai\"}'"

Kai will call your server and return the result!

---

## 💾 Your Data Persists

Everything you save to `/home/ubuntu/termux-server/home/` stays there forever:

```bash
# Save important data
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/file/write \
  -H "Content-Type: application/json" \
  -d '{"path": "important.txt", "content": "This will be here next time"}'

# Access it anytime
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/file/read \
  -H "Content-Type: application/json" \
  -d '{"path": "important.txt"}'
```

---

## 🔑 Key URLs

| Service | URL |
|---------|-----|
| **API** | https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer |
| **Web Terminal** | https://3333-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer |
| **Chisel Tunnel** | https://3001-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer |

---

## ⚡ Pro Tips

1. **Long-running commands?** Increase timeout:
   ```json
   {"command": "long-task", "timeout": 300}
   ```

2. **Need specific directory?** Set working directory:
   ```json
   {"command": "ls", "cwd": "/home/ubuntu/termux-server/home"}
   ```

3. **Environment variables?** Pass them:
   ```json
   {"command": "echo $MY_VAR", "env": {"MY_VAR": "value"}}
   ```

4. **Check what's installed?** List packages:
   ```json
   {"action": "list"}
   ```

---

## ❓ Troubleshooting

**API not responding?**
- Check if the server is running
- Verify your internet connection
- Try the health endpoint: `https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/health`

**SSH connection refused?**
- Make sure chisel tunnel is running
- Verify the tunnel is connected: `ps aux | grep chisel`

**File not found?**
- Files are stored in `/home/ubuntu/termux-server/home/`
- Use relative paths in the API

---

**That's it! You're ready to use your persistent Termux Server! 🎉**
