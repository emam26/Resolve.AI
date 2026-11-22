# ResolveAI voice notifications for Windows PowerShell 5.1.
# Each exact spoken sentence is announced at most once, across runs and reboots.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('test', 'done', 'review', 'blocked')]
    [string]$Event,

    [ValidatePattern('^[A-Za-z0-9_-]{1,30}$')]
    [string]$Milestone = 'ResolveAI'
)

$ErrorActionPreference = 'Stop'
$messages = @{
    test    = "Resolve AI voice test for $Milestone."
    done    = "Resolve AI. Milestone $Milestone is verified and ready for your review."
    review  = "Resolve AI needs your approval for milestone $Milestone. Please check Codex."
    blocked = "Resolve AI is blocked on milestone $Milestone and needs your attention."
}
$message = $messages[$Event]

# Store permanent deduplication state in the user's local application data.
$stateDir = Join-Path $env:LOCALAPPDATA 'ResolveAI\voice-history'
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($message))
    $fingerprint = [System.BitConverter]::ToString($bytes).Replace('-', '')
}
finally { $sha.Dispose() }

$mutex = New-Object System.Threading.Mutex($false, 'Local\ResolveAI_Voice_Notifier')
$locked = $false
$speaker = $null
try {
    $locked = $mutex.WaitOne(15000)
    if (-not $locked) { throw 'Voice notifier is busy.' }

    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $stamp = Join-Path $stateDir "$fingerprint.stamp"
    if (Test-Path -LiteralPath $stamp) {
        Write-Output "VOICE_SKIPPED_ALREADY_SAID: $Event ($Milestone)"
        return
    }

    Add-Type -AssemblyName System.Speech -ErrorAction Stop
    $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $speaker.Speak($message)
    # Record only after speech succeeds so a failed notification can be retried.
    Set-Content -LiteralPath $stamp -Value $message -Encoding UTF8
    Write-Output "VOICE_OK: $Event ($Milestone)"
}
catch {
    Write-Error "VOICE_FAILED: $($_.Exception.Message). A claimed sentence is not automatically retried."
    exit 1
}
finally {
    if ($null -ne $speaker) { $speaker.Dispose() }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
