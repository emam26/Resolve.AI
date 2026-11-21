# ResolveAI local voice notifications. Windows PowerShell 5.1; no network or paid APIs.
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
    test    = 'Resolve AI voice notifications are working.'
    done    = "Resolve AI. Milestone $Milestone is verified and ready for your review."
    review  = "Resolve AI needs your approval for milestone $Milestone. Please check Codex."
    blocked = "Resolve AI is blocked on milestone $Milestone and needs your attention."
}

$speaker = $null
try {
    Add-Type -AssemblyName System.Speech -ErrorAction Stop
    $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $speaker.Rate = 0
    $speaker.Volume = 100
    $speaker.Speak($messages[$Event])
    Write-Output "VOICE_OK: $Event ($Milestone)"
}
catch {
    Write-Error "VOICE_FAILED: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($null -ne $speaker) {
        $speaker.Dispose()
    }
}
