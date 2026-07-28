# Restart the gallery app on port 5050.
# Usage:  .\restart.ps1
# Leaves the Cloudflare tunnel (cloudflared) running so the public URL stays the same.

$ErrorActionPreference = 'Stop'
$port   = 5050
$python = 'C:\Users\Shadow\AppData\Local\Programs\Python\Python314\python.exe'
$appDir = 'C:\GEROINZO\geroinzo-gallery'

Write-Host "Stopping anything on port $port ..." -ForegroundColor Yellow
$conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force
    Write-Host "  stopped pid $($conn.OwningProcess)" -ForegroundColor DarkGray
} else {
    Write-Host "  nothing was running" -ForegroundColor DarkGray
}

Write-Host "Starting app ..." -ForegroundColor Yellow
$env:PORT = "$port"
Start-Process $python -ArgumentList 'app.py' -WorkingDirectory $appDir `
    -RedirectStandardOutput app.out -RedirectStandardError app.err -WindowStyle Hidden

Start-Sleep -Seconds 2
$conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($conn) {
    Write-Host "OK - the gallery is listening on $port (pid $($conn.OwningProcess))." -ForegroundColor Green
    Write-Host "If something looks wrong, check errors with:" -ForegroundColor DarkGray
    Write-Host "    Get-Content `"$appDir\app.err`" -Tail 20" -ForegroundColor DarkGray
} else {
    Write-Host "FAILED - app is not listening on $port. Recent errors:" -ForegroundColor Red
    Get-Content "$appDir\app.err" -Tail 20
}
