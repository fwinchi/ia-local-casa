@echo off
timeout /t 60 /nobreak
%USERPROFILE%\AppData\Local\Python\bin\python.exe "%~dp0indexar_pdfs.py" >> "%~dp0indexar.log" 2>&1
