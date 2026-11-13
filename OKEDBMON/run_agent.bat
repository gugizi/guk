@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run run_collector.bat first so the Python environment is created.
  pause
  goto :eof
)
echo This agent collects the single target in config\agent.json.
.venv\Scripts\python.exe -m agent
