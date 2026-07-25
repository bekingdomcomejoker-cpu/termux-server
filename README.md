# Termux Server - Persistent Shell Environment API

A lightweight, persistent shell environment accessible via REST API, web terminal, and SSH tunnel. Run commands, manage files, and execute scripts without consuming credits or spinning up new resources.

## 🚀 Quick Start

### Access Methods

You have **three ways** to interact with your Termux Server:

#### 1. **REST API** (Recommended for automation)
```bash
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "echo Hello from Termux Server"}'
```

#### 2. **Web Terminal** (Interactive shell in browser)
Open in your browser:
```
https://3333-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer
```

#### 3. **SSH Tunnel** (Via chisel SOCKS5 proxy)
```bash
# On your local machine, set up the tunnel:
chisel client https://3001-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer 1080:socks

# Then SSH through the tunnel:
ssh -o "ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p" ubuntu@localhost -p 2222
```

---

## 📡 API Endpoints

### 1. Health Check
```bash
GET /health
```
**Response:**
```json
{"status": "healthy", "service": "termux-server"}
```

### 2. Execute Shell Command
```bash
POST /execute
Content-Type: application/json

{
  "command": "ls -la",
  "cwd": "/home/ubuntu/termux-server/home",
  "timeout": 30,
  "env": {"KEY": "value"}
}
```

**Response:**
```json
{
  "success": true,
  "output": "total 8\ndrwxr-xr-x 2 ubuntu ubuntu 4096 Jul 23 15:16 .\ndrwxr-xr-x 8 ubuntu ubuntu 4096 Jul 23 15:16 ..\n",
  "error": null,
  "returncode": 0
}
```

**Parameters:**
- `command` (required): Shell command to execute
- `cwd` (optional): Working directory (default: `/home/ubuntu/termux-server/home`)
- `timeout` (optional): Command timeout in seconds (default: 30)
- `env` (optional): Environment variables to set

### 3. Read File
```bash
POST /file/read
Content-Type: application/json

{
  "path": "myfile.txt"
}
```

**Response:**
```json
{
  "success": true,
  "output": "File contents here...",
  "error": null
}
```

### 4. Write File
```bash
POST /file/write
Content-Type: application/json

{
  "path": "myfile.txt",
  "content": "Hello World"
}
```

**Response:**
```json
{
  "success": true,
  "output": "File written: myfile.txt",
  "error": null
}
```

### 5. Manage Packages
```bash
POST /package
Content-Type: application/json

{
  "action": "install",
  "package": "git"
}
```

**Actions:**
- `install` - Install a package
- `remove` - Remove a package
- `update` - Update package list
- `list` - List installed packages

### 6. Get Environment Info
```bash
GET /info
```

**Response:**
```json
{
  "home": "/home/ubuntu/termux-server/home",
  "tmp": "/home/ubuntu/termux-server/tmp",
  "var": "/home/ubuntu/termux-server/var",
  "system": "Linux sandbox 6.1.0-...",
  "current_dir": "/home/ubuntu/termux-server",
  "python_version": "3.11.0rc1 ..."
}
```

---

## 🎯 Use Cases

### 1. Running Commands from Kai 9000
```bash
# Install chisel on the server
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "curl -sSL https://i.jpillora.com/chisel! | sudo bash"}'

# Install a package
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/package \
  -H "Content-Type: application/json" \
  -d '{"action": "install", "package": "nodejs"}'

# Run a script
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "bash /home/ubuntu/termux-server/home/my-script.sh"}'
```

### 2. Interactive Web Terminal
1. Open `https://3333-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer` in your browser
2. You'll see a full bash shell
3. Run commands as if you were SSH'd into the server

### 3. SSH Access via Chisel Tunnel
```bash
# Terminal 1: Set up the tunnel
chisel client https://3001-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer 1080:socks

# Terminal 2: SSH through the tunnel
ssh -o "ProxyCommand=nc -X 5 -x 127.0.0.1:1080 %h %p" ubuntu@localhost -p 2222
# Password: termux123
```

### 4. Persistent Data Storage
All files written to `/home/ubuntu/termux-server/home/` persist across sessions:

```bash
# Write a file
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/file/write \
  -H "Content-Type: application/json" \
  -d '{"path": "data.txt", "content": "Important data"}'

# Read it back later
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/file/read \
  -H "Content-Type: application/json" \
  -d '{"path": "data.txt"}'
```

---

## 🔧 Installation & Setup

### Prerequisites
- Python 3.7+
- FastAPI
- Uvicorn
- ttyd (for web terminal)
- chisel (for SSH tunneling)

### Install Dependencies
```bash
sudo apt-get update
sudo apt-get install -y python3-pip ttyd

# Install Python packages
pip3 install fastapi uvicorn

# Install chisel
curl -sSL https://i.jpillora.com/chisel! | sudo bash
```

### Start the Server
```bash
# API Server (port 8000)
python3 api_server.py

# Web Terminal (port 3333)
ttyd -p 3333 bash

# Chisel Server (port 3001)
chisel server --port 3001 --socks5
```

### Run in Background
```bash
# API Server
nohup python3 api_server.py > /tmp/api.log 2>&1 &

# Web Terminal
nohup ttyd -p 3333 bash > /tmp/ttyd.log 2>&1 &

# Chisel Server
nohup chisel server --port 3001 --socks5 > /tmp/chisel.log 2>&1 &
```

---

## 💡 Key Features

✅ **Persistent Environment** - Everything you install/configure stays across sessions
✅ **No Credits Used** - Call to your persistent server, not spinning up new resources
✅ **Multiple Access Methods** - API, Web Terminal, SSH Tunnel
✅ **File Management** - Read/write files directly via API
✅ **Package Management** - Install/remove packages on demand
✅ **Environment Variables** - Set custom env vars per command
✅ **Timeout Control** - Prevent long-running commands from blocking
✅ **Security** - Path traversal protection, command isolation

---

## 🔐 Security Considerations

1. **Path Traversal Protection** - File operations are restricted to `/home/ubuntu/termux-server/home/`
2. **Command Isolation** - Each command runs in its own process
3. **Timeout Limits** - Default 30-second timeout prevents resource exhaustion
4. **Authentication** - SSH requires password (default: `termux123`)
5. **HTTPS Only** - All API calls use HTTPS encryption

---

## 📊 Environment Paths

- **Home Directory**: `/home/ubuntu/termux-server/home`
- **Temp Directory**: `/home/ubuntu/termux-server/tmp`
- **Log Directory**: `/home/ubuntu/termux-server/var/log`

---

## 🐛 Troubleshooting

### API Returns 500 Error
Check the API logs:
```bash
tail -f /home/ubuntu/termux-server/var/log/api.log
```

### Web Terminal Not Loading
Verify ttyd is running:
```bash
ps aux | grep ttyd
```

### SSH Connection Refused
Ensure chisel tunnel is active:
```bash
ps aux | grep chisel
```

### Command Timeout
Increase the timeout parameter:
```bash
{
  "command": "long-running-command",
  "timeout": 300
}
```

---

## 📝 Examples

### Example 1: Install and Run Node.js
```bash
# Install Node.js
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/package \
  -H "Content-Type: application/json" \
  -d '{"action": "install", "package": "nodejs"}'

# Create a simple script
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/file/write \
  -H "Content-Type: application/json" \
  -d '{"path": "app.js", "content": "console.log(\"Hello from Node.js\")"}'

# Run it
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "node app.js"}'
```

### Example 2: Git Operations
```bash
# Clone a repository
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "git clone https://github.com/user/repo.git"}'

# Check status
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "cd repo && git status"}'
```

### Example 3: Data Processing
```bash
# Create a data file
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/file/write \
  -H "Content-Type: application/json" \
  -d '{"path": "data.csv", "content": "name,age\nAlice,30\nBob,25"}'

# Process with Python
curl -X POST https://8000-i7ybv0vcyztqxzo7i99r4-bd2e14d5.us1.manus.computer/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "python3 -c \"import csv; print(list(csv.DictReader(open(\\\"data.csv\\\"))))\"", "cwd": "/home/ubuntu/termux-server/home"}'
```

---

## 📚 API Response Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request |
| 403 | Access denied (path traversal) |
| 500 | Server error |

---

## 🤝 Contributing

Feel free to extend this project with:
- Additional API endpoints
- Authentication mechanisms
- Database integration
- Scheduled task support
- Real-time WebSocket updates

---

## 📄 License

MIT License - Use freely for personal and commercial projects

---

## 🔗 Related Projects

- **Omega Federation Bridge** - MikroTik terminal session manager built on this API
- **Kai 9000** - Mobile AI interface that calls this server
- **Manus** - The platform hosting this persistent server

---

## 📞 Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the API logs
3. Test endpoints individually
4. Verify network connectivity

---

**Your persistent Termux Server is ready to use!** 🚀
