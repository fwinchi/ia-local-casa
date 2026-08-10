@echo off
call "%~dp0secrets.local.bat"
%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\Scripts\mcpo.exe --host 127.0.0.1 --port 8002 -- %USERPROFILE%\AppData\Local\Python\bin\python.exe "%~dp0mcp_documentos.py"
