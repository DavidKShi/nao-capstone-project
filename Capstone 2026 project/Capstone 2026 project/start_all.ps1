$LAPTOP_IP = "YOUR_ROBOT_IP"
$PROJECT   = Split-Path -Parent $MyInvocation.MyCommand.Path
$REPO      = Join-Path $PROJECT "Chat-with-NAO-robot-using-ChatGPT"
$WS        = Join-Path $REPO "websocket"
$NAO       = Join-Path $REPO "naoqi"
$ENV_FILE  = Join-Path $PROJECT ".env"

# ---------- load .env ----------
if (Test-Path $ENV_FILE) {
    Get-Content $ENV_FILE | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
            Set-Item -Path "env:$($matches[1].Trim())" -Value $matches[2].Trim()
        }
    }
    Write-Host "[OK] Loaded $ENV_FILE" -ForegroundColor Green
} else {
    Write-Host "[WARN] $ENV_FILE not found - API keys will be missing" -ForegroundColor Yellow
}

$env:LAPTOP_IP = $LAPTOP_IP

# ---------- build env block passed into each new window ----------
$envBlock = @"
`$env:LAPTOP_IP = '$LAPTOP_IP'
`$env:OPENAI_API_KEY = '$env:OPENAI_API_KEY'
`$env:AUDD_API_KEY   = '$env:AUDD_API_KEY'
"@

# ---------- 1. Facial Recognition API (py -3.11, port 5002) ----------
Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
$envBlock
Set-Location '$WS'
Write-Host '--- Facial Recognition API (port 5002) ---' -ForegroundColor Cyan
py -3.11 facial_recognition_api.py
"@

# ---------- 2. ChatGPT API (py -3.11, port 5001) ----------
Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
$envBlock
Set-Location '$WS'
Write-Host '--- ChatGPT API (port 5001) ---' -ForegroundColor Cyan
py -3.11 'flask api.py'
"@

# ---------- 3. Song / AudD API (py -3.11, port 5003) ----------
Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
$envBlock
Set-Location '$WS'
Write-Host '--- Song Recognition API (port 5003) ---' -ForegroundColor Cyan
py -3.11 tone_analysis_api.py
"@

# ---------- 4. NAO main (Python 2.7, port 9559) ----------
Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
$envBlock
Set-Location '$NAO'
Write-Host '--- NAO Main Program (Python 2.7) ---' -ForegroundColor Cyan
python nao_main.py
"@

Write-Host ""
Write-Host "All 4 services launched in separate windows." -ForegroundColor Green
Write-Host "  Laptop IP : $LAPTOP_IP"
Write-Host "  Robot IP  : YOUR_ROBOT_IP"
Write-Host ""
Write-Host "Close this window or press Ctrl+C. The service windows stay open."
