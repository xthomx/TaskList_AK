@echo off
cd /d "%~dp0"
call PRZYGOTUJ.bat
if errorlevel 1 goto fail
.venv\Scripts\python.exe main.py
if errorlevel 1 goto fail
exit /b 0
:fail
 echo Uruchomienie nie powiodlo sie. Przeczytaj INSTRUKCJA.txt.
 pause
 exit /b 1
