@echo off
cd /d "%~dp0.."
uv run python -m final_agent.campus_demo
if errorlevel 1 (
  echo Campus walkway demo failed.
  pause
  exit /b 1
)
