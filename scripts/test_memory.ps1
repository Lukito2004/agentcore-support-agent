# Checks AgentCore Memory: a preference told in one session is recalled in a new session, and not by another user.
# Usage: .\scripts\test_memory.ps1 -Email alex.morgan@example.com [-OtherEmail sam.rivera@example.com] [-OutFile docs\evidence\memory-across-sessions.txt]
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [string]$OtherEmail,
    [string]$Region = "eu-west-1",
    [string]$Runtime = "support_agent",
    [int]$MaxWaitSeconds = 180,
    [string]$OutFile
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "agent_client.ps1")
Initialize-AgentClient -Runtime $Runtime -Email $Email

Write-Log ("Memory across sessions, {0}, signed in as {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Email)
Write-Log ""

$question = '{"prompt": "What AWS region do I prefer?"}'
Assert-Reply "Session 1: customer states a preference" (New-SessionId "memory-1") "{`"prompt`": `"Please remember that my preferred AWS region is $Region.`"}" { param($r) -not $r.StartsWith("ERROR") }

# Long-term records are extracted asynchronously, so ask again in fresh sessions until they appear.
$deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
$recalled = $false
while (-not $recalled -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 20
    $reply = Invoke-Agent (New-SessionId "memory-probe") $question
    $recalled = $reply -match [regex]::Escape($Region)
    Write-Host ("  waiting for extraction... recalled={0}" -f $recalled)
}
Assert-Reply "Session 2 (new session): preference is recalled" (New-SessionId "memory-2") $question { param($r) $r -match [regex]::Escape($Region) }

if ($OtherEmail) {
    Initialize-AgentClient -Runtime $Runtime -Email $OtherEmail
    Assert-Reply "Another customer does not get this preference" (New-SessionId "memory-other") $question { param($r) -not ($r -match [regex]::Escape($Region)) -and -not $r.StartsWith("ERROR") }
}

Complete-AgentTest $OutFile
