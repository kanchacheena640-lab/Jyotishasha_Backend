
@echo off
echo === Starting Jyotishasha Backend ===

REM Step 1: Start Redis Server
start cmd /k "cd C:\Redis && .\redis-server.exe"

REM Step 2: Start Celery Worker
start cmd /k "cd C:\Jyotishasha_Backend && C:\Jyotishasha_Backend\venv\Scripts\activate && celery -A celery_app.celery worker --loglevel=info --pool=solo"

REM Step 3: Start Flask Server
start cmd /k "cd C:\Jyotishasha_Backend && C:\Jyotishasha_Backend\venv\Scripts\activate && python app.py"

echo All services started. You can close this window.
pause
