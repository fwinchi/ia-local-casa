@echo off
call "%~dp0secrets.local.bat"
"%USERPROFILE%\AppData\Local\Python\bin\python.exe" "%~dp0salud.py"
pause
