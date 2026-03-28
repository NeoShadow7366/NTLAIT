---
description: Cross-platform compatibility rules ensuring Windows, macOS, and Linux parity
---

# Cross-Platform Rules

Every feature must work identically on **Windows 10/11**, **macOS** (Intel + Apple Silicon), and **Linux** (x86_64 + arm64).

## 1. Path Handling

```python
# ✅ CORRECT — os.path.join handles separators
filepath = os.path.join(root_dir, ".backend", "metadata.sqlite")

# ❌ FORBIDDEN — hardcoded separators
filepath = root_dir + "/.backend/metadata.sqlite"
filepath = root_dir + "\\.backend\\metadata.sqlite"
```

## 2. Python Executable Location

```python
# Venv python location differs by platform
if os.name == 'nt':
    python_exe = os.path.join(venv_dir, "Scripts", "python.exe")
else:
    python_exe = os.path.join(venv_dir, "bin", "python")
```

## 3. Symlinks vs Junctions

```python
if platform.system() == "Windows":
    # Use NTFS Directory Junctions (no admin required)
    cmd = ["cmd.exe", "/c", "mklink", "/J", target_link, source_dir]
    subprocess.run(cmd, capture_output=True, text=True)
else:
    # Standard POSIX symlink
    os.symlink(source_dir, target_link, target_is_directory=True)
```

## 4. Process Management

```python
# Subprocess creation flags
kwargs = {}
if os.name == 'nt':
    kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)

# Process termination
if os.name == 'nt':
    subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
else:
    p.terminate()  # or os.kill(pid, signal.SIGTERM)
```

## 5. File Opening

```python
# Always specify encoding for text files
with open(filepath, 'r', encoding='utf-8') as f:
    # ...

# Use 'rb' for binary operations (hashing, image downloads)
with open(filepath, 'rb') as f:
    # ...
```

## 6. Folder Opening (Explorer / Finder)

```python
if os.name == 'nt':
    subprocess.Popen(['explorer', folder_path])
elif sys.platform == 'darwin':
    subprocess.Popen(['open', folder_path])
else:
    subprocess.Popen(['xdg-open', folder_path])
```

## 7. Line Endings

- Python files: LF (`\n`) — enforced by `.gitattributes`
- Batch files (`.bat`): CRLF (`\r\n`) — required by Windows
- Shell scripts (`.sh`): LF (`\n`) — required by UNIX

## 8. Architecture Detection (for python-build-standalone)

```bash
# Shell
ARCH=$(uname -m)  # x86_64, aarch64, arm64

# Python
import platform
arch = platform.machine()  # AMD64, x86_64, arm64, aarch64
```

## 9. Recursive Directory Deletion (shutil.rmtree)

```python
# Windows throws PermissionError when deleting read-only files (e.g., inside .git folders)
import shutil, os, stat

def remove_readonly(func, path, _):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

shutil.rmtree(target_dir, onerror=remove_readonly)
```

