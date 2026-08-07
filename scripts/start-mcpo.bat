@echo off
call "%~dp0secrets.local.bat"
if not defined PAPERLESS_TOKEN (
  echo Falta PAPERLESS_TOKEN. Copia secrets.local.bat.example a secrets.local.bat y rellena el token.
  exit /b 1
)
%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\Scripts\mcpo.exe --host 127.0.0.1 --port 8001 -- npx -y @baruchiro/paperless-mcp --baseUrl http://localhost:8010 --token %PAPERLESS_TOKEN%
