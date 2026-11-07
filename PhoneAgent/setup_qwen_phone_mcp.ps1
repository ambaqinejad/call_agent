
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigDir = Join-Path $env:USERPROFILE '.config\qwaudio'
$ConfigEnv = Join-Path $ConfigDir 'config.env'
$McpConfig = Join-Path $Root 'frontend-mcp.json'

# Check required files
$McpServer = Join-Path $Root 'phone_mcp_server.py'
$PhoneService = Join-Path $Root 'phone_service.py'

if (-not (Test-Path $McpServer)) {
    throw "Missing file: $McpServer"
}

if (-not (Test-Path $PhoneService)) {
    throw "Missing file: $PhoneService"
}

# Locate Python
$PyLine = & py -3 -c 'import sys; print(sys.executable)'

if ($LASTEXITCODE -ne 0 -or -not $PyLine) {
    throw 'Python 3 was not found. Install Python 3.10 or newer.'
}

$PythonExe = ([string]($PyLine | Select-Object -Last 1)).Trim()

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

# Install dependencies if necessary
& $PythonExe -c "from mcp.server.fastmcp import FastMCP; import serial; print(1)"

if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing Python dependencies...'

    & $PythonExe -m pip install --upgrade pyserial 'mcp[cli]>=1.0,<2'

    if ($LASTEXITCODE -ne 0) {
        throw 'Python dependency installation failed.'
    }
}

# Create config directory
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

if (-not (Test-Path $ConfigEnv)) {
    New-Item -ItemType File -Path $ConfigEnv | Out-Null
}

$Lines = @(Get-Content $ConfigEnv -ErrorAction SilentlyContinue)

# Read or generate API token
$TokenLine = $Lines |
    Where-Object { $_ -match '^\s*PHONE_API_TOKEN\s*=' } |
    Select-Object -Last 1

if ($TokenLine) {
    $Token = ($TokenLine -replace '^\s*PHONE_API_TOKEN\s*=\s*', '').Trim().Trim('"').Trim("'")
}
else {
    $Bytes = New-Object byte[] 32
    $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $Rng.GetBytes($Bytes)
    $Rng.Dispose()

    $Token = ([BitConverter]::ToString($Bytes)).Replace('-', '').ToLowerInvariant()
}

if ($Token.Length -lt 24) {
    throw 'PHONE_API_TOKEN is too short. Use at least 24 characters.'
}

# Update config.env without removing unrelated settings
function Set-EnvValue {
    param(
        [string[]]$Existing,
        [string]$Name,
        [string]$Value
    )

    $Filtered = @(
        $Existing | Where-Object {
            $_ -notmatch ('^\s*' + [regex]::Escape($Name) + '\s*=')
        }
    )

    return @($Filtered + ($Name + '=' + $Value))
}

$Lines = Set-EnvValue $Lines 'PHONE_API_TOKEN' $Token
$Lines = Set-EnvValue $Lines 'QWEN_AUDIO_FRONTEND_MCP_CONFIG' $McpConfig

Set-Content -Path $ConfigEnv -Value $Lines -Encoding UTF8

# Generate MCP configuration
$Mcp = @{
    version = 1

    servers = @{
        phone = @{
            enabled = $true

            transport = @{
                type = 'stdio'
                command = $PythonExe
                args = @($McpServer)

                env = @{
                    PHONE_SERVICE_URL = 'http://127.0.0.1:8787'
                    PHONE_API_TOKEN = '${PHONE_API_TOKEN}'
                }
            }

            connectTimeoutMs = 15000

            tools = @{
                ping = @{
                    enabled = $true
                    timeoutMs = 15000
                }

                dial = @{
                    enabled = $true
                    timeoutMs = 20000
                }

                answer = @{
                    enabled = $true
                    timeoutMs = 15000
                }

                hangup = @{
                    enabled = $true
                    timeoutMs = 15000
                }

                get_call_status = @{
                    enabled = $true
                    timeoutMs = 15000
                }

                get_recent_call_events = @{
                    enabled = $true
                    timeoutMs = 15000
                }
            }
        }
    }
}

$Mcp |
    ConvertTo-Json -Depth 12 |
    Set-Content -Path $McpConfig -Encoding UTF8

Write-Host ''
Write-Host 'Qwen Phone MCP configuration completed.' -ForegroundColor Green
Write-Host "Python: $PythonExe"
Write-Host "Config: $ConfigEnv"
Write-Host "MCP JSON: $McpConfig"
Write-Host 'Existing PHONE_API_TOKEN was preserved when available.'
Write-Host 'Start phone_service.ps1 and restart Qwen Gateway.'
