@echo off
cd /d "%~dp0server"
py -m pip install -r ..\requirements.txt
py app.py --host 127.0.0.1 --port 8000
pause
