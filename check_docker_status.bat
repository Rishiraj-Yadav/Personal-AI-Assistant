@echo off
echo ================================================
echo Checking Docker Container Status
echo ================================================
echo.

echo [1] All running containers:
docker ps
echo.
echo.

echo [2] All containers (including stopped):
docker ps -a
echo.
echo.

echo [3] Backend container logs:
echo ================================================
docker logs sonarbot-backend --tail 100
echo.
echo.

pause
