@echo off
:esperar
curl.exe -s -o nul http://localhost:5000/health/ready
if errorlevel 1 (
  ping -n 6 127.0.0.1 >nul
  goto esperar
)
%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\Scripts\mcpo.exe --port 8004 --server-type streamablehttp -- http://localhost:5000/mcp
