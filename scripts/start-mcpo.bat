@echo off
call "%~dp0secrets.local.bat"
if not defined PAPERLESS_TOKEN (
  echo Falta PAPERLESS_TOKEN. Copia secrets.local.bat.example a secrets.local.bat y rellena el token.
  exit /b 1
)
set "PAPERLESS_URL=http://localhost:8010"
set "PAPERLESS_API_KEY=%PAPERLESS_TOKEN%"
%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\Scripts\mcpo.exe --host 127.0.0.1 --port 8001 -- "%ProgramFiles%\nodejs\npx.cmd" -y @baruchiro/paperless-mcp@2.0.1
