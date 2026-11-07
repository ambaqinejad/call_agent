$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigEnv = Join-Path $env:USERPROFILE '.config\qwaudio\config.env'
if (-not (Test-Path $ConfigEnv)) { throw "فایل تنظیمات پیدا نشد: $ConfigEnv" }
$TokenLine = Get-Content $ConfigEnv | Where-Object { $_ -match '^\s*PHONE_API_TOKEN\s*=' } | Select-Object -Last 1
if (-not $TokenLine) { throw 'PHONE_API_TOKEN در config.env وجود ندارد. ابتدا setup_qwen_phone_mcp.ps1 را اجرا کن.' }
$Token = ($TokenLine -replace '^\s*PHONE_API_TOKEN\s*=\s*', '').Trim().Trim('"').Trim("'")
if ($Token.Length -lt 24) { throw 'PHONE_API_TOKEN نامعتبر است.' }
$PyLine = & py -3 -c 'import sys; print(sys.executable)'
if ($LASTEXITCODE -ne 0 -or -not $PyLine) { throw 'Python 3 پیدا نشد.' }
$PythonExe = ([string]$PyLine | Select-Object -Last 1).Trim()
$env:PHONE_API_TOKEN = $Token
$env:PHONE_SERIAL_PORT = 'COM5'
$env:PHONE_BAUDRATE = '115200'
$env:PHONE_HTTP_HOST = '127.0.0.1'
$env:PHONE_HTTP_PORT = '8787'
& $PythonExe (Join-Path $Root 'phone_service.py')
