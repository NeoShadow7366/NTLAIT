@echo off
setlocal
echo ===========================================
echo Generative AI Manager
echo ===========================================

set "ROOT_DIR=%~dp0"
set "BIN_DIR=%ROOT_DIR%bin"
set "PYTHON_DIR=%BIN_DIR%\python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Portable Python not found.
    echo Please run install.bat first before attempting to start the manager.
    pause
    exit /b 1
)

echo [1/3] Scanning Global Vault for new AI models via background crawler...
"%PYTHON_EXE%" "%ROOT_DIR%.backend\vault_crawler.py"

echo [2/3] Fetching rich Civitai metadata and thumbnails for mapped models...
"%PYTHON_EXE%" "%ROOT_DIR%.backend\civitai_client.py"

echo [3/3] Launching local Web Dashboard...
start http://localhost:8080

echo Server is active. Please keep this window open to serve UI packages!
"%PYTHON_EXE%" "%ROOT_DIR%.backend\server.py"

pause
