@echo off
setlocal
cd /d "%~dp0"
python quickedit.py
if errorlevel 1 pause
