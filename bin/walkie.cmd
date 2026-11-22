@echo off
rem walkie – Walkie unter Windows (Einstellungen, Tasten, Start/Stopp, Einrichtung).
rem Nimmt die Python-Umgebung des Walkies, sonst ein installiertes Python 3. Fehlt es (oder ist
rem nur der Microsoft-Store-Platzhalter da), holt es uv (Prüfsummen in uvboot.py) – ohne Adminrechte.
setlocal
set "HERE=%~dp0.."
if defined WALKIE_VENV if exist "%WALKIE_VENV%\Scripts\python.exe" ( "%WALKIE_VENV%\Scripts\python.exe" "%HERE%\cli.py" %* & exit /b %ERRORLEVEL% )
set "SHARE=%USERPROFILE%\.local\share\walkie"
if defined XDG_DATA_HOME set "SHARE=%XDG_DATA_HOME%\walkie"
if exist "%SHARE%\venv\Scripts\python.exe" ( "%SHARE%\venv\Scripts\python.exe" "%HERE%\cli.py" %* & exit /b %ERRORLEVEL% )
if exist "%HERE%\.venv\Scripts\python.exe" ( "%HERE%\.venv\Scripts\python.exe" "%HERE%\cli.py" %* & exit /b %ERRORLEVEL% )
where py >nul 2>nul && ( py -3 -c "import sys" >nul 2>nul ) && ( py -3 "%HERE%\cli.py" %* & exit /b %ERRORLEVEL% )
rem „python“ kann der Store-Platzhalter sein: der läuft nicht, sondern endet mit Fehler
python -c "import sys" >nul 2>nul && ( python "%HERE%\cli.py" %* & exit /b %ERRORLEVEL% )

rem Kein Python: uv laden (feste Version, SHA-256 aus uvboot.py) und damit starten
set "UV=%SHARE%\uv\uv.exe"
if not exist "%UV%" (
  echo Kein Python gefunden - lade uv, das ein passendes Python mitbringt ... 1>&2
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uvboot.ps1" "%UV%"
)
if not exist "%UV%" ( echo uv liess sich nicht einrichten. Bitte Python installieren: winget install Python.Python.3.12 1>&2 & exit /b 1 )
"%UV%" run --no-project --python 3.12 "%HERE%\cli.py" %*
