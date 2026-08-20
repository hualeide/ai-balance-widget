@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py -3.11
) else (
  set PY=python
)

if not exist ".venv\Scripts\python.exe" (
  echo 正在创建运行环境…
  %PY% -m venv .venv
)

".venv\Scripts\python.exe" -m pip install -r "pet\requirements.txt" -q
if errorlevel 1 (
  echo 依赖安装失败，请检查网络后重试。
  pause
  exit /b 1
)

start "AI余额桌宠" ".venv\Scripts\pythonw.exe" "pet\main.py"
