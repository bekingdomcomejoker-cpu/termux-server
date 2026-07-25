# Troubleshooting Termux Server Installation

If you encounter `ModuleNotFoundError: No module named 'fastapi'` or errors building `pydantic-core` on Python 3.14+, use this fix ladder.

---

## Fix 1: Termux Native Package (No Compiling)
Termux maintains pre-built packages for common Python libraries. Try this first:

```bash
pkg install python-fastapi python-uvicorn python-websockets -y
```

---

## ✅ Confirmed Fix: Set Android API Level + Build Tools

This is the confirmed solution for **Python 3.14 on Termux (Android API 33/arm64)**. It allows `maturin` to compile `pydantic-core` correctly.

### 1. Set the Environment Variable
Run this to tell the compiler your Android version:
```bash
export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)
```

### 2. Install Build Essentials
Install the Rust toolchain and LLVM utilities:
```bash
pkg install rust binutils-is-llvm lld -y
```

### 3. Install Python Packages
Now `pip` will be able to build the native wheels:
```bash
pip install fastapi uvicorn websockets selenium
```

### 4. Make it Permanent
Add the export to your `.bashrc` so you don't have to run it again:
```bash
echo 'export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)' >> ~/.bashrc
source ~/.bashrc
```


---

## Fix 3: Use Pre-Built Wheels (Avoid Rust Entirely)
Force pip to use only pre-built wheels. This may use older versions but avoids compilation:

```bash
export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)
pip install --only-binary :all: fastapi uvicorn websockets selenium
```

---

## Fix 4: Downgrade Python (Nuclear Option)
Python 3.14 is very new. If nothing else works, use a more mature version:

```bash
# Install Python 3.12 if available
pkg install python3.12 -y
python3.12 -m pip install fastapi uvicorn websockets selenium
python3.12 api_server.py
```

---

## Quick Diagnostic
Run this to see your environment details:

```bash
echo "API: $(getprop ro.build.version.sdk)"
echo "Python: $(python3 --version)"
pkg search python-fastapi 2>/dev/null | head -5
```
