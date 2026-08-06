@echo off
del /q "%~dp0revision.html" 2>nul
%USERPROFILE%\AppData\Local\Python\bin\python.exe "%~dp0revisar.py" >> "%~dp0revisar.log" 2>&1
findstr /C:"Grupo 1" "%~dp0revision.html" >nul && start "" "%~dp0revision.html"
