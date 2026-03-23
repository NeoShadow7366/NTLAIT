#!/usr/bin/env bash
set -e

echo "==========================================="
echo "Generative AI Manager"
echo "==========================================="

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
BIN_DIR="$ROOT_DIR/bin"
PYTHON_DIR="$BIN_DIR/python"
PYTHON_EXE="$PYTHON_DIR/bin/python3"

if [ ! -f "$PYTHON_EXE" ]; then
    echo "[ERROR] Portable Python not found."
    echo "Please run install.sh first before attempting to start the manager."
    exit 1
fi

echo "[1/3] Scanning Global Vault for new AI models via background crawler..."
"$PYTHON_EXE" "$ROOT_DIR/.backend/vault_crawler.py"

echo "[2/3] Fetching rich Civitai metadata and thumbnails for mapped models..."
"$PYTHON_EXE" "$ROOT_DIR/.backend/civitai_client.py"

echo "[3/3] Launching local Web Dashboard..."

# Cross-platform default browser launch
if command -v xdg-open > /dev/null; then
  xdg-open "http://localhost:8080"
elif command -v open > /dev/null; then
  open "http://localhost:8080"
fi

echo "Server is active. Please keep this window open to serve UI packages!"
"$PYTHON_EXE" "$ROOT_DIR/.backend/server.py"
