# Read-only status for the explicitly scoped ResolveAI local services.
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

function Get-TargetContainer {
    $raw = @(& wsl.exe -d Ubuntu -- docker inspect $containerName 2>$null) -join "`n"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) { return $null }
    try { $items = @($raw | ConvertFrom-Json) } catch { throw 'The targeted Docker container metadata could not be read safely.' }
    if ($items.Count -ne 1 -or $items[0].Name -ne "/$containerName") { throw 'Docker returned unexpected metadata for the targeted container.' }
    return $items[0]
}

function Get-PortBinding {
    param([Parameter(Mandatory = $true)]$Container)
    if ($null -eq $Container.HostConfig.PortBindings) { return @() }
    $bindings = $Container.HostConfig.PortBindings.'5432/tcp'
    if ($null -eq $bindings) { return @() }
    return @($bindings)
}

function Get-ContainerEnvironment {
    param([Parameter(Mandatory = $true)]$Container)
    $environment = @{}
    foreach ($entry in @($Container.Config.Env)) {
        $parts = ([string]$entry).Split('=', 2)
        if ($parts.Count -eq 2) { $environment[$parts[0]] = $parts[1] }
    }
    return $environment
}

function Get-PortOwner {
    param([Parameter(Mandatory = $true)][int]$Port)
    $connection = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $connection) { return $null }
    return [int]$connection.OwningProcess
}

function Get-ProcessInfo {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    return [pscustomobject]@{
        Id = $ProcessId
        CommandLine = [string]$process.CommandLine
        ExecutablePath = [string]$process.ExecutablePath
    }
}

function Test-ExpectedProcess {
    param(
        [Parameter(Mandatory = $true)]$ProcessInfo,
        [Parameter(Mandatory = $true)][ValidateSet('backend', 'frontend')][string]$Kind
    )
    if ($null -eq $ProcessInfo) { return $false }
    if ($Kind -eq 'backend') {
        return $ProcessInfo.CommandLine -match 'uvicorn\s+backend\.app\.main:app' -and
            $ProcessInfo.CommandLine -match '--port\s+8000'
    }
    return $ProcessInfo.CommandLine -match [regex]::Escape((Join-Path $repositoryRoot 'frontend')) -and
        $ProcessInfo.CommandLine -match 'vite' -and
        $ProcessInfo.CommandLine -match '--port\s+5173'
}

function Get-ManagedState {
    param([Parameter(Mandatory = $true)][ValidateSet('backend', 'frontend')][string]$Kind)
    $path = Join-Path $runtimeRoot "$Kind.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    try {
        $state = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
        if ($state.repository_root -ne $repositoryRoot -or $state.kind -ne $Kind) { return $null }
        return $state
    }
    catch { return $null }
}

function Get-ProcessStatus {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('backend', 'frontend')][string]$Kind,
        [Parameter(Mandatory = $true)][int]$Port
    )
    $owner = Get-PortOwner $Port
    if ($null -eq $owner) {
        return [pscustomobject]@{
            Message = ("{0}: STOPPED (http://127.0.0.1:{1}/)" -f $Kind, $Port)
            Ready = $false
        }
    }
    $info = Get-ProcessInfo $owner
    $managed = Test-ExpectedProcess $info $Kind
    $state = Get-ManagedState $Kind
    if ($managed -and $null -ne $state -and [int]$state.process_id -eq $owner) {
        return [pscustomobject]@{
            Message = ("{0}: RUNNING, managed PID {1} (http://127.0.0.1:{2}/)" -f $Kind, $owner, $Port)
            Ready = $true
        }
    }
    if ($managed) {
        return [pscustomobject]@{
            Message = ("{0}: RUNNING, unmanaged PID {1}; stop will leave it untouched (http://127.0.0.1:{2}/)" -f $Kind, $owner, $Port)
            Ready = $true
        }
    }
    return [pscustomobject]@{
        Message = ("{0}: OCCUPIED by unrelated PID {1}; left untouched (port {2})" -f $Kind, $owner, $Port)
        Ready = $false
    }
}

$allReady = $true
Write-Output 'ResolveAI local status (read-only)'
Write-Output "URLs: frontend http://127.0.0.1:$frontendPort/ | backend http://127.0.0.1:$backendPort/"

$dockerAvailable = $true
$null = & wsl.exe -d Ubuntu -- docker version 2>$null
if ($LASTEXITCODE -ne 0) {
    $dockerAvailable = $false
    Write-Output 'PostgreSQL: UNKNOWN (WSL Docker unavailable)'
    $allReady = $false
}
else {
    $container = Get-TargetContainer
    if ($null -eq $container) {
        Write-Output "PostgreSQL: ABSENT ($containerName; no resource created)"
        $allReady = $false
    }
    else {
        $state = [string]$container.State.Status
        $bindings = Get-PortBinding $container
        $bindingText = @($bindings | ForEach-Object { "{0}:{1}" -f $_.HostIp, $_.HostPort }) -join ', '
        if ([string]::IsNullOrWhiteSpace($bindingText)) { $bindingText = 'no published port' }
        Write-Output "PostgreSQL: $state ($containerName; $bindingText)"
        $hasLocalBinding = @($bindings | Where-Object { [string]$_.HostIp -eq '127.0.0.1' -and [string]$_.HostPort -eq [string]$databasePort }).Count -eq 1
        if (-not $hasLocalBinding) {
            Write-Output "PostgreSQL readiness: NOT READY (expected localhost:$databasePort; no Docker changes made)"
            $allReady = $false
        }
        elseif (-not [bool]$container.State.Running) {
            Write-Output 'PostgreSQL readiness: NOT READY (container is stopped)'
            $allReady = $false
        }
        else {
            $environment = Get-ContainerEnvironment $container
            $databaseUser = if ($environment.ContainsKey('POSTGRES_USER')) { $environment['POSTGRES_USER'] } else { 'postgres' }
            $databaseName = if ($environment.ContainsKey('POSTGRES_DB')) { $environment['POSTGRES_DB'] } else { 'postgres' }
            $null = & wsl.exe -d Ubuntu -- docker exec $containerName pg_isready -U $databaseUser -d $databaseName 2>$null
            if ($LASTEXITCODE -eq 0) { Write-Output "PostgreSQL readiness: READY on localhost:$databasePort" }
            else { Write-Output 'PostgreSQL readiness: NOT READY (pg_isready failed)'; $allReady = $false }
        }
    }
}

$backendStatus = Get-ProcessStatus -Kind backend -Port $backendPort
$frontendStatus = Get-ProcessStatus -Kind frontend -Port $frontendPort
Write-Output $backendStatus.Message
Write-Output $frontendStatus.Message
$backendReady = [bool]$backendStatus.Ready
$frontendReady = [bool]$frontendStatus.Ready
if (-not $backendReady -or -not $frontendReady) { $allReady = $false }

if ($backendReady) {
    try {
        $health = Invoke-WebRequest -Uri "http://127.0.0.1:$backendPort/healthz" -UseBasicParsing -TimeoutSec 3
        Write-Output "Backend health: HTTP $($health.StatusCode)"
        if ($health.StatusCode -ne 200) { $allReady = $false }
    }
    catch { Write-Output 'Backend health: UNAVAILABLE'; $allReady = $false }
    try {
        $readiness = Invoke-WebRequest -Uri "http://127.0.0.1:$backendPort/readyz" -UseBasicParsing -TimeoutSec 3
        Write-Output "Backend readiness: HTTP $($readiness.StatusCode)"
        if ($readiness.StatusCode -ne 200) { $allReady = $false }
    }
    catch { Write-Output 'Backend readiness: UNAVAILABLE'; $allReady = $false }
}

Write-Output "Runtime state/logs: $runtimeRoot"
if (-not $allReady) { exit 1 }
