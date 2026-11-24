# Stop only ResolveAI local processes recorded by start-local.ps1 and the
# explicitly named PostgreSQL container. Never remove a container or volume.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'ResolveAI\local-runtime'
$containerName = 'resolveai-local-dev-postgres'
$pythonExecutable = Join-Path $repositoryRoot '.venv\Scripts\python.exe'

function Get-ProcessInfo {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
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

function Stop-ManagedProcess {
    param([Parameter(Mandatory = $true)][ValidateSet('backend', 'frontend')][string]$Kind)

    $path = Join-Path $runtimeRoot "$Kind.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Write-Output "${Kind}: no process owned by this lifecycle script."
        return
    }
    try { $state = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json } catch {
        Write-Output "${Kind}: invalid state file; refusing to stop any process."
        return
    }
    if ($state.repository_root -ne $repositoryRoot -or $state.kind -ne $Kind) {
        Write-Output "${Kind}: state ownership mismatch; refusing to stop any process."
        return
    }
    $processId = 0
    if (-not [int]::TryParse([string]$state.process_id, [ref]$processId) -or $processId -le 0) {
        Write-Output "${Kind}: invalid recorded PID; refusing to stop any process."
        return
    }
    $info = Get-ProcessInfo $processId
    if ($null -eq $info) {
        Remove-Item -LiteralPath $path -Force
        Write-Output "${Kind}: already stopped; stale state removed."
        return
    }
    if ([string]::IsNullOrWhiteSpace([string]$state.process_start_utc) -or
        [string]::IsNullOrWhiteSpace([string]$info.StartedUtc) -or
        [string]$state.process_start_utc -ne [string]$info.StartedUtc) {
        Write-Output "${Kind}: recorded PID $processId has a different start time; left untouched."
        return
    }

    $expected = if ($Kind -eq 'backend') {
        $info.CommandLine -match 'uvicorn\s+backend\.app\.main:app' -and $info.CommandLine -match '--port\s+8000'
    }
    else {
        $info.CommandLine -match [regex]::Escape((Join-Path $repositoryRoot 'frontend')) -and $info.CommandLine -match 'vite' -and $info.CommandLine -match '--port\s+5173'
    }
    if (-not $expected) {
        Write-Output "${Kind}: recorded PID $processId no longer matches the expected ResolveAI command; left untouched."
        return
    }
    Stop-Process -Id $processId -ErrorAction Stop
    Remove-Item -LiteralPath $path -Force
    Write-Output "${Kind}: stopped managed PID $processId."
}

function Get-TargetContainer {
    $raw = @(& wsl.exe -d Ubuntu -- docker inspect $containerName 2>$null) -join "`n"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) { return $null }
    try { $items = @($raw | ConvertFrom-Json) } catch { throw 'The targeted Docker container metadata could not be read safely.' }
    if ($items.Count -ne 1 -or $items[0].Name -ne "/$containerName") { throw 'Docker returned unexpected metadata for the targeted container.' }
    return $items[0]
}

Stop-ManagedProcess -Kind frontend
Stop-ManagedProcess -Kind backend

$null = & wsl.exe -d Ubuntu -- docker version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Output 'PostgreSQL: WSL Docker unavailable; no Docker resource was touched.'
    exit 1
}
$container = Get-TargetContainer
if ($null -eq $container) {
    Write-Output "PostgreSQL: $containerName was not found; no Docker resource was created or removed."
    exit 0
}
if ([bool]$container.State.Running) {
    $null = & wsl.exe -d Ubuntu -- docker stop $containerName 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Failed to stop only the targeted container $containerName." }
    Write-Output "PostgreSQL: stopped $containerName. The container and its volume were preserved."
}
else {
    Write-Output "PostgreSQL: $containerName already stopped. The container and its volume were preserved."
}
