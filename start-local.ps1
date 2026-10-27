$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendV5 = Join-Path $projectRoot "V5"
$backendMdm = Join-Path $projectRoot "MDM"
$frontend = Join-Path $projectRoot "frontend"

$v5Python = Join-Path $backendV5 ".venv\Scripts\python.exe"
$mdmPython = Join-Path $backendMdm ".venv\Scripts\python.exe"

foreach ($path in @($v5Python, $mdmPython, (Join-Path $frontend "node_modules"))) {
    if (-not (Test-Path $path)) {
        throw "Required dependency path not found: $path. See README.md for setup instructions."
    }
}

function Read-OraclePassword($prompt) {
    $securePassword = Read-Host $prompt -AsSecureString
    if ($securePassword.Length -eq 0) {
        throw "An Oracle password is required to start the database-backed APIs."
    }
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
}

$env:DELTAMAX_ORACLE_USER = if ($env:DELTAMAX_ORACLE_USER) { $env:DELTAMAX_ORACLE_USER } else { "DELTAMAX_V5" }
if (-not $env:DELTAMAX_ORACLE_PASSWORD) {
    $env:DELTAMAX_ORACLE_PASSWORD = Read-OraclePassword "Enter the Oracle password for $($env:DELTAMAX_ORACLE_USER)"
}

$env:DELTAMAX_ORACLE_DSN = if ($env:DELTAMAX_ORACLE_DSN) { $env:DELTAMAX_ORACLE_DSN } else { "localhost:1521/FREEPDB1" }
$env:BQ_PROJECT = if ($env:BQ_PROJECT) { $env:BQ_PROJECT } else { "datatoolunstructured" }
$env:BQ_DATASET = if ($env:BQ_DATASET) { $env:BQ_DATASET } else { "deltamax_migration" }

$dsnMatch = [regex]::Match($env:DELTAMAX_ORACLE_DSN, "^(?<host>.+):(?<port>\d+)/(?<service>[^/]+)$")
if (-not $dsnMatch.Success) {
    throw "Unsupported Oracle DSN '$($env:DELTAMAX_ORACLE_DSN)'. Expected host:port/service."
}

$oracleHost = $dsnMatch.Groups["host"].Value
$oraclePort = [int]$dsnMatch.Groups["port"].Value
$env:MDM_DB_USER = if ($env:MDM_DB_USER) { $env:MDM_DB_USER } else { $env:DELTAMAX_ORACLE_USER }
if ($env:MDM_DB_USER -ieq $env:DELTAMAX_ORACLE_USER) {
    $env:MDM_DB_PASSWORD = $env:DELTAMAX_ORACLE_PASSWORD
}
elseif (-not $env:MDM_DB_PASSWORD) {
    $env:MDM_DB_PASSWORD = Read-OraclePassword "Enter the Oracle password for $($env:MDM_DB_USER)"
}
$env:MDM_DB_HOST = if ($env:MDM_DB_HOST) { $env:MDM_DB_HOST } else { $oracleHost }
$env:MDM_DB_PORT = if ($env:MDM_DB_PORT) { $env:MDM_DB_PORT } else { [string]$oraclePort }
$env:MDM_DB_SERVICE = if ($env:MDM_DB_SERVICE) { $env:MDM_DB_SERVICE } else { $dsnMatch.Groups["service"].Value }

if (-not (Test-NetConnection -ComputerName $oracleHost -Port $oraclePort -InformationLevel Quiet -WarningAction SilentlyContinue)) {
    throw "Oracle is not accepting connections at ${oracleHost}:$oraclePort. Start Oracle/listener, then run this script again."
}

function Get-Listener($port) {
    Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Test-ApiReady($url, $databaseUser) {
    try {
        $response = Invoke-RestMethod -Uri $url -TimeoutSec 4
        return $response.status -eq "ok" -and $response.database_user -ieq $databaseUser
    }
    catch {
        return $false
    }
}

$mdmPort = 8001
$mdmListener = Get-Listener $mdmPort
if ($mdmListener -and -not (Test-ApiReady "http://127.0.0.1:$mdmPort/api/health" $env:MDM_DB_USER)) {
    $mdmPort = $null
    foreach ($candidatePort in 8002..8010) {
        if (Get-Listener $candidatePort) {
            continue
        }
        $probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidatePort)
        try {
            $probe.Start()
            $mdmPort = $candidatePort
            break
        }
        catch {
            continue
        }
        finally {
            $probe.Stop()
        }
    }

    if (-not $mdmPort) {
        throw "MDM port 8001 is occupied and no free replacement port was found between 8002 and 8010."
    }
    Write-Host "Port 8001 is occupied by an unhealthy MDM listener; using port $mdmPort instead."
}

$env:MDM_BACKEND_URL = "http://localhost:$mdmPort"

$services = @(
    [pscustomobject]@{
        Name = "V5 API"
        Port = 8000
        HealthUrl = "http://127.0.0.1:8000/api/health"
        User = $env:DELTAMAX_ORACLE_USER
        Executable = $v5Python
        Arguments = "-m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000"
        WorkingDirectory = $backendV5
    },
    [pscustomobject]@{
        Name = "MDM API"
        Port = $mdmPort
        HealthUrl = "http://127.0.0.1:$mdmPort/api/health"
        User = $env:MDM_DB_USER
        Executable = $mdmPython
        Arguments = "-m uvicorn main:app --reload --host 127.0.0.1 --port $mdmPort"
        WorkingDirectory = $backendMdm
    }
)

$servicesToStart = @()
foreach ($service in $services) {
    $listener = Get-Listener $service.Port
    if ($listener) {
        if (Test-ApiReady $service.HealthUrl $service.User) {
            Write-Host "$($service.Name) is already running and connected to Oracle."
            continue
        }
        $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        throw "Port $($service.Port) is already occupied by PID $($listener.OwningProcess) ($($process.ProcessName)); its $($service.Name) health check failed. Stop that process or inspect its terminal."
    }

    Start-Process `
        -FilePath $service.Executable `
        -ArgumentList $service.Arguments `
        -WorkingDirectory $service.WorkingDirectory |
        Out-Null
    $servicesToStart += $service
    Write-Host "Starting $($service.Name) on port $($service.Port)..."
}

$frontendListener = Get-Listener 5173
if ($frontendListener -and $mdmPort -ne 8001) {
    $frontendProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($frontendListener.OwningProcess)" -ErrorAction SilentlyContinue
    $frontendCommand = if ($frontendProcess) { $frontendProcess.CommandLine } else { "" }
    if (-not $frontendProcess -or $frontendProcess.Name -ne "node.exe" -or
        $frontendCommand -notmatch "vite[\\/]+bin[\\/]+vite\.js" -or
        $frontendCommand -notlike "*$frontend*") {
        throw "MDM is using port $mdmPort, but port 5173 belongs to a process that is not this project's Vite server. Restart the project frontend with MDM_BACKEND_URL=$env:MDM_BACKEND_URL."
    }
    Stop-Process -Id $frontendListener.OwningProcess
    $frontendDeadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $frontendDeadline -and (Get-Listener 5173)) {
        Start-Sleep -Milliseconds 250
    }
    if (Get-Listener 5173) {
        throw "Could not restart the project frontend to use the MDM API on port $mdmPort."
    }
    Write-Host "Restarted the project frontend so its MDM proxy can use port $mdmPort."
    $frontendListener = $null
}

if ($frontendListener) {
    Write-Host "Frontend is already listening on port 5173."
}
else {
    Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList "/k npm run dev" `
        -WorkingDirectory $frontend |
        Out-Null
    Write-Host "Starting frontend on port 5173..."
}

$frontendReady = $false
$frontendError = "No HTTP response was received."
$frontendDeadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $frontendDeadline) {
    try {
        $frontendResponse = Invoke-WebRequest -Uri "http://localhost:5173" -TimeoutSec 4 -UseBasicParsing
        if ($frontendResponse.StatusCode -eq 200) {
            $frontendReady = $true
            break
        }
    }
    catch {
        $frontendError = $_.Exception.Message
    }
    Start-Sleep -Seconds 2
}
if (-not $frontendReady) {
    throw "Frontend did not respond successfully within 45 seconds. Check its console. $frontendError"
}

foreach ($service in $servicesToStart) {
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        if (Test-ApiReady $service.HealthUrl $service.User) {
            Write-Host "$($service.Name) is ready and connected to Oracle."
            break
        }
        Start-Sleep -Seconds 2
    }

    if (-not (Test-ApiReady $service.HealthUrl $service.User)) {
        throw "$($service.Name) did not pass its Oracle health check within 45 seconds. Check its service window for the connection error."
    }
}

Write-Host ""
Write-Host "All services are ready:"
Write-Host "  Frontend: http://localhost:5173"
Write-Host "  V5 API:   http://127.0.0.1:8000/docs"
Write-Host "  MDM API:  http://127.0.0.1:$mdmPort/docs"
Write-Host "Core Engine, Executive AI, Cloud Migration, and Security use the V5 API; MDM uses the MDM API."
Write-Host "Services start without executing data pipelines or changing database contents."
