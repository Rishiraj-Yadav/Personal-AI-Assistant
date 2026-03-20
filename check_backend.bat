@echo off
echo ================================================
echo Checking Backend Container Status
echo ================================================
echo.

echo [1] All Docker containers:
docker ps -a
echo.
echo.

echo [2] Backend container logs (last 50 lines):
echo ================================================
docker logs personal-ai-assistant-backend-1 --tail 50
echo.
echo.

echo [3] Backend container logs (last 50 lines) - alternate name:
echo ================================================
docker logs sonarbot-backend --tail 50
echo.
echo.

pause
