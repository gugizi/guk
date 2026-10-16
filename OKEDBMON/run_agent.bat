@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run run_collector.bat first so the Python environment is created.
  pause
  goto :eof
)
.venv\Scripts\python.exe -m agent
