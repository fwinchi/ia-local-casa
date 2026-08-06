@echo off
call "%~dp0secrets.local.bat"
%USERPROFILE%\AppData\Local\Python\bin\python.exe "%~dp0autocorresponsal.py" >> "%~dp0autocorresponsal.log" 2>&1
