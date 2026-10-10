@echo off
chcp 65001 >nul 2>&1
echo Starting DubIndia from dubbing_app...
cd /d "%~dp0dubbing_app"
call start.bat
