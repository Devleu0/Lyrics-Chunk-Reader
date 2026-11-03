@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
set "OLLAMA_URL=http://127.0.0.1:11434"
set "APP_URL=http://127.0.0.1:7860"
set "MODEL=qwen3:8b"

if not exist "%PYTHON%" (
    echo Python virtual environment not found: "%PYTHON%"
    echo Follow the Windows setup instructions in README.md first.
    goto error
)

if not exist "%OLLAMA%" (
    where ollama.exe >nul 2>&1
    if errorlevel 1 (
        echo Ollama is not installed. Install it from https://ollama.com/download
        goto error
    )
    set "OLLAMA=ollama.exe"
)

curl.exe --fail --silent --output NUL "%OLLAMA_URL%/api/tags"
if errorlevel 1 (
    echo Starting Ollama server...
    start "Ollama server" /min "%OLLAMA%" serve
)

for /L %%i in (1,1,30) do (
    curl.exe --fail --silent --output NUL "%OLLAMA_URL%/api/tags"
    if not errorlevel 1 goto ollama_ready
    timeout /t 2 /nobreak >nul
)
echo Ollama did not start at %OLLAMA_URL%.
goto error

:ollama_ready
curl.exe --fail --silent "%OLLAMA_URL%/api/tags" | findstr /I /C:"%MODEL%" >nul
if errorlevel 1 (
    echo Downloading the %MODEL% translation model, approximately 5.2 GB...
    "%OLLAMA%" pull "%MODEL%"
    if errorlevel 1 goto error
)

curl.exe --fail --silent --output NUL "%APP_URL%"
if errorlevel 1 (
    echo Starting the web app...
    start "Lyrics Jikdok" "%PYTHON%" -u app.py
    for /L %%i in (1,1,30) do (
        curl.exe --fail --silent --output NUL "%APP_URL%"
        if not errorlevel 1 goto app_ready
        timeout /t 1 /nobreak >nul
    )
    echo The web app did not start at %APP_URL%.
    goto error
)

:app_ready
start "" "%APP_URL%"
echo Lyrics Jikdok is ready at %APP_URL%
exit /b 0

:error
echo.
echo Startup failed. Check the message above and try again.
pause
exit /b 1
