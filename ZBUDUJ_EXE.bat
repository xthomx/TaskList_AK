@echo off
cd /d "%~dp0"
call PRZYGOTUJ.bat
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name TaskListAK --add-data "ui;ui" --collect-all webview main.py
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name TaskListUpdater --distpath dist\TaskListAK updater_runner.py
if errorlevel 1 goto fail
 echo Gotowe: dist\TaskListAK\TaskListAK.exe
 echo Przenos CALY folder dist\TaskListAK, nie sam plik EXE.
 explorer "dist\TaskListAK"
 pause
 exit /b 0
:fail
 echo Budowanie nie powiodlo sie. Przekaz tresc bledu.
 pause
 exit /b 1
