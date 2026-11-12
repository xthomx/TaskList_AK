@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto validate
if exist ".venv" goto broken
rem Prefer a supported 64-bit Python already installed on this computer.
for %%V in (3.15 3.14 3.13 3.12 3.11 3.10) do (
    py -%%V -c "import sys,struct; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,16) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
    if not errorlevel 1 (
        py -%%V -m venv .venv
        if errorlevel 1 goto create_error
        goto validate
    )
)
rem Also support Python installed without the Windows py launcher.
python -c "import sys,struct; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,16) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto missing
python -m venv .venv
if errorlevel 1 goto create_error
:validate
.venv\Scripts\python.exe -c "import sys,struct; print('Python:', sys.version); sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,16) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 goto broken
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo Instalacja bibliotek nie powiodla sie. Sprawdz komunikat powyzej i polaczenie internetowe.
    exit /b 1
)
exit /b 0
:missing
echo Nie znaleziono Pythona 64-bit w wersji 3.10 do 3.15.
echo Zainstaluj Python 3.12 64-bit z https://www.python.org/downloads/windows/
echo Podczas instalacji zaznacz Python Launcher oraz Add Python to PATH.
echo Wykryte wersje launchera:
py --list 2>nul
echo Python dostepny przez PATH:
python --version 2>nul
exit /b 1
:broken
echo Katalog .venv zawiera niezgodne lub niekompletne srodowisko.
echo Zmien nazwe folderu .venv na .venv_stare i uruchom ten skrypt ponownie.
echo Pliki planu CSV i TXT pozostaw bez zmian.
exit /b 1
:create_error
echo Nie udalo sie utworzyc srodowiska .venv. Sprawdz blad powyzej.
echo Rozpakuj program do zapisywalnego katalogu, np. Dokumenty.
exit /b 1
