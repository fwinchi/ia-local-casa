@echo off
call "%~dp0secrets.local.bat"
%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\Scripts\mcpo.exe --host 127.0.0.1 --port 8005 -- %USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\python.exe "D:\proyecto-repo\scripts\mcp_correo.py"
