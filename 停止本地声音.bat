@echo off
chcp 65001 >nul
type nul > "%~dp0local-voice\stop-request"
echo 已请求停止本地声音，大肥鱼会继续使用云端龙嫱。
pause
