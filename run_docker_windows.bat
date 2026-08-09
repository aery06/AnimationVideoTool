@echo off
setlocal
where docker >nul 2>nul
if errorlevel 1 (
  echo Docker was not found. Install Docker Desktop, then run this file again.
  pause
  exit /b 1
)
docker compose up -d --build
if errorlevel 1 (
  echo Failed to start the local app.
  pause
  exit /b 1
)
echo.
echo AnimationVideoTool is running at http://127.0.0.1:7860
start "" http://127.0.0.1:7860
echo To stop it later, run stop_docker_windows.bat
pause
