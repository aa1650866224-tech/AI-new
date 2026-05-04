@echo off
cd /d D:\pythonstudy\project\web
start "" http://localhost:8080
python -m http.server 8080
pause
