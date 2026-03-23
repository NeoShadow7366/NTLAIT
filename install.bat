@echo off
setlocal
echo ===========================================
echo Generative AI Manager Bootstrap (Windows)
echo ===========================================

set "ROOT_DIR=%~dp0"
set "BIN_DIR=%ROOT_DIR%bin"
set "PYTHON_DIR=%BIN_DIR%\python"

mkdir "%BIN_DIR%" 2>nul
mkdir "%ROOT_DIR%Global_Vault" 2>nul
mkdir "%ROOT_DIR%packages" 2>nul

if not exist "%PYTHON_DIR%\python.exe" (
    echo [1/3] Downloading Portable Python...
    curl -L "https://github.com/indygreg/python-build-standalone/releases/download/20240224/cpython-3.11.8+20240224-x86_64-pc-windows-msvc-shared-install_only.tar.gz" -o "%BIN_DIR%\python.tar.gz"
    echo Extracting Python...
    tar -xf "%BIN_DIR%\python.tar.gz" -C "%BIN_DIR%"
    del "%BIN_DIR%\python.tar.gz"
    echo Python installed successfully.
) else (
    echo [1/3] Portable Python found.
)

echo [2/3] Fetching latest backend resources...
rem If python exists, execute bootstrap:
if exist "%PYTHON_DIR%\python.exe" (
    "%PYTHON_DIR%\python.exe" "%ROOT_DIR%.backend\bootstrap.py"
) else (
    echo [Note] Skipping python execution because portable python was not found. Please install the python binaries and re-run.
)

echo [3/3] Bootstrap complete. Run the manager to start.
pause
