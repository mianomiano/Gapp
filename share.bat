@echo off
REM ============================================================
REM  Run the gallery publicly (free) via Cloudflare Tunnel.
REM  Double-click this file. It opens TWO windows:
REM    1) the app  2) the tunnel (which prints your public URL)
REM  Copy the https://....trycloudflare.com URL into @BotFather.
REM  Close either window to stop. (Does not touch ngrok.)
REM ============================================================
cd /d "%~dp0"

echo Starting the gallery app...
REM Port 5050 keeps this app off 5000, which is used by the other (ngrok) bot.
start "gallery-app" cmd /k "set PORT=5050 && python app.py"

echo Waiting for the app to come up...
timeout /t 3 >nul

echo Opening public tunnel - your URL appears below:
echo.
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:5050
