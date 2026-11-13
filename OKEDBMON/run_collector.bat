@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv || goto :error
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
)
echo OKEDBMON collector: http://127.0.0.1:8080/  (admin / okedbmon)
.venv\Scripts\python.exe -m collector
goto :eof
:error
echo Python 3.10 or later is required.
pause
