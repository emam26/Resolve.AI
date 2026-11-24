# Start the explicitly scoped ResolveAI local services.
#
# This script only starts the existing resolveai-local-dev-postgres container,
# the repository's backend, and the repository's frontend. It never migrates,
# seeds, removes, or recreates Docker resources.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'ResolveAI\local-runtime'
$containerName = 'resolveai-local-dev-postgres'
$databasePort = 55436
$backendPort = 8000
$frontendPort = 5173
$pythonExecutable = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
$npmExecutable = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source

function Invoke-TargetDocker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = @(& wsl.exe -d Ubuntu -- docker @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw 'WSL Docker is unavailable or the targeted Docker command failed.'
    }
    return $output
}

function Get-TargetContainer {
    $raw = @(& wsl.exe -d Ubuntu -- docker inspect $containerName 2>$null) -join "`n"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    try {
        $items = @($raw | ConvertFrom-Json)
    }
    catch {
        throw 'The targeted Docker container metadata could not be read safely.'
    }
    if ($items.Count -ne 1 -or $items[0].Name -ne "/$containerName") {
        throw 'Docker returned unexpected metadata for the targeted container.'
    }
    return $items[0]
}

function Get-TargetPortBindings {
    param([Parameter(Mandatory = $true)]$Container)

    if ($null -eq $Container.HostConfig.PortBindings) {
        return @()
    }
    $bindings = $Container.HostConfig.PortBindings.'5432/tcp'
    if ($null -eq $bindings) {
        return @()
    }
    return @($bindings)
}

function Assert-LocalDatabaseBinding {
    param([Parameter(Mandatory = $true)]$Container)

    $bindings = Get-TargetPortBindings $Container
    $valid = @($bindings | Where-Object {
        ([string]$_.HostPort -eq [string]$databasePort) -and
        ([string]$_.HostIp -eq '127.0.0.1')
    })
    if ($valid.Count -ne 1) {
        throw "The existing $containerName container does not publish PostgreSQL on localhost:$databasePort. Refusing to modify or recreate it."
    }
}

function Get-ContainerEnvironment {
    param([Parameter(Mandatory = $true)]$Container)

    $environment = @{}
    foreach ($entry in @($Container.Config.Env)) {
        $parts = ([string]$entry).Split('=', 2)
        if ($parts.Count -eq 2) {
            $environment[$parts[0]] = $parts[1]
        }
    }
    return $environment
}

function Wait-Database {
    param([Parameter(Mandatory = $true)]$Container)

    $environment = Get-ContainerEnvironment $Container
    $databaseUser = if ($environment.ContainsKey('POSTGRES_USER')) { $environment['POSTGRES_USER'] } else { 'postgres' }
    $databaseName = if ($environment.ContainsKey('POSTGRES_DB')) { $environment['POSTGRES_DB'] } else { 'postgres' }
    if ($databaseUser -notmatch '^[A-Za-z0-9_]+$' -or $databaseName -notmatch '^[A-Za-z0-9_]+$') {
        throw 'The targeted container has an unsafe PostgreSQL identity configuration.'
    }

    for ($attempt = 1; $attempt -le 30; $attempt++) {
        $null = & wsl.exe -d Ubuntu -- docker exec $containerName pg_isready -U $databaseUser -d $databaseName 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Output "PostgreSQL ready at 127.0.0.1:$databasePort (container $containerName)."
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'PostgreSQL did not become ready within 15 seconds.'
}

function Get-PortOwner {
    param([Parameter(Mandatory = $true)][int]$Port)

    $connection = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $connection) {
        return $null
    }
    return [int]$connection.OwningProcess
}

function Get-ProcessInfo {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }
    $started = $null
    try {
        $started = (Get-Process -Id $ProcessId -ErrorAction Stop).StartTime.ToUniversalTime().ToString('o')
    }
    catch { }
    return [pscustomobject]@{
        Id = $ProcessId
        CommandLine = [string]$process.CommandLine
        ExecutablePath = [string]$process.ExecutablePath
        StartedUtc = $started
    }
}

function Test-ExpectedProcess {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [Parameter(Mandatory = $true)][ValidateSet('backend', 'frontend')][string]$Kind
    )

    if ($null -eq $ProcessInfo) { return $false }
    if ($Kind -eq 'backend') {
        # Win32_Process does not include the working directory, and existing
        # local runs may use the system Python. The exact app module/port are
        # the identity check; stop-local still requires its own recorded PID.
        return $ProcessInfo.CommandLine -match 'uvicorn\s+backend\.app\.main:app' -and
            $ProcessInfo.CommandLine -match '--port\s+8000'
    }
    return $ProcessInfo.CommandLine -match [regex]::Escape((Join-Path $repositoryRoot 'frontend')) -and
        $ProcessInfo.CommandLine -match 'vite' -and
        $ProcessInfo.CommandLine -match '--port\s+5173'
}

function Save-ProcessState {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('backend', 'frontend')][string]$Kind,
        [Parameter(Mandatory = $true)]$ProcessInfo
    )

    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    $state = @{
        kind = $Kind
        process_id = $ProcessInfo.Id
        process_start_utc = $ProcessInfo.StartedUtc
        repository_root = $repositoryRoot
    } | ConvertTo-Json
    Set-Content -LiteralPath (Join-Path $runtimeRoot "$Kind.json") -Value $state -Encoding UTF8
}

function Start-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('backend', 'frontend')][string]$Kind,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw "$Kind executable was not found at the configured local path."
    }
    $existingOwner = Get-PortOwner $Port
    if ($null -ne $existingOwner) {
        $existingInfo = Get-ProcessInfo $existingOwner
        if (Test-ExpectedProcess $existingInfo $Kind) {
            Write-Output "$Kind already running on 127.0.0.1:$Port (unmanaged by this invocation; left running)."
            return
        }
        throw "127.0.0.1:$Port is already occupied by another process (PID $existingOwner); refusing to stop or replace it."
    }

    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    $stdoutPath = Join-Path $runtimeRoot "$Kind.out.log"
    $stderrPath = Join-Path $runtimeRoot "$Kind.err.log"
    $null = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru

    for ($attempt = 1; $attempt -le 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        $owner = Get-PortOwner $Port
        if ($null -ne $owner) {
            $info = Get-ProcessInfo $owner
            if (Test-ExpectedProcess $info $Kind) {
                Save-ProcessState $Kind $info
                Write-Output "$Kind ready at http://127.0.0.1:$Port (PID $owner)."
                return
            }
            throw "127.0.0.1:$Port was claimed by an unexpected process; no process was stopped."
        }
    }
    throw "$Kind did not open 127.0.0.1:$Port within 30 seconds. See $runtimeRoot\$Kind.err.log."
}

try {
    if (-not $npmExecutable) {
        throw 'npm.cmd was not found on PATH; the existing Node installation is required.'
    }
    if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
        throw "The existing Python environment was not found at $pythonExecutable."
    }

    $null = & wsl.exe -d Ubuntu -- docker version 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'WSL Docker is unavailable; no Docker resources were changed.'
    }

    $container = Get-TargetContainer
    if ($null -eq $container) {
        throw "The targeted container $containerName was not found; refusing to create a replacement."
    }
    Assert-LocalDatabaseBinding $container
    if (-not [bool]$container.State.Running) {
        $null = Invoke-TargetDocker @('start', $containerName)
        Write-Output "Started existing container $containerName."
    }
    Wait-Database (Get-TargetContainer)

    Start-ManagedProcess -Kind backend -Port $backendPort -FilePath $pythonExecutable -Arguments @('-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', [string]$backendPort) -WorkingDirectory $repositoryRoot
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:$backendPort/healthz" -UseBasicParsing -TimeoutSec 5
    if ($health.StatusCode -ne 200) {
        throw "Backend health check returned HTTP $($health.StatusCode)."
    }
    $readiness = Invoke-WebRequest -Uri "http://127.0.0.1:$backendPort/readyz" -UseBasicParsing -TimeoutSec 5
    if ($readiness.StatusCode -ne 200) {
        throw "Backend readiness check returned HTTP $($readiness.StatusCode). Migrations are not run by this script."
    }

    Start-ManagedProcess -Kind frontend -Port $frontendPort -FilePath $npmExecutable -Arguments @('run', 'dev', '--', '--host', '127.0.0.1', '--port', [string]$frontendPort) -WorkingDirectory (Join-Path $repositoryRoot 'frontend')
    Write-Output 'ResolveAI local services are ready.'
    Write-Output "Frontend: http://127.0.0.1:$frontendPort/"
    Write-Output "Backend:  http://127.0.0.1:$backendPort/"
    Write-Output "Health:   http://127.0.0.1:$backendPort/healthz"
    Write-Output "Ready:    http://127.0.0.1:$backendPort/readyz"
    Write-Output "Logs/PIDs: $runtimeRoot"
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
