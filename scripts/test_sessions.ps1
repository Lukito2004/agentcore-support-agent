# Checks runtime session behavior: same session keeps context, a new session does not, bad payloads are rejected.
# Usage: .\scripts\test_sessions.ps1 [-Local] [-OutFile docs\evidence\runtime-session-isolation.txt]
param(
    [switch]$Local,
    [string]$Runtime = "support_agent",
    [string]$OutFile
)

$ErrorActionPreference = "Stop"
$script:log = @()
$script:failures = 0

function Write-Log([string]$Line) {
    Write-Host $Line
    $script:log += $Line
}

function Invoke-Agent([string]$SessionId, [string]$Payload) {
    # Windows PowerShell 5.1 strips inner quotes when calling native programs, so escape them.
    if ($PSVersionTable.PSVersion.Major -lt 7) { $Payload = $Payload.Replace('"', '\"') }
    $cliArgs = @("invoke", "--runtime", $Runtime, "--json", "--session-id", $SessionId, "--payload", $Payload)
    if ($Local) { $cliArgs += "--local" }

    $result = (& agentcore @cliArgs 2>$null | Out-String) | ConvertFrom-Json
    $text = ""
    foreach ($line in ($result.body -split "`n")) {
        if (-not $line.StartsWith("data: ")) { continue }
        $evt = $line.Substring(6) | ConvertFrom-Json
        if ($evt.error) { return "ERROR $($evt.error.code): $($evt.error.message)" }
        $delta = $evt.event.contentBlockDelta.delta.text
        if ($delta) { $text += $delta }
    }
    return $text.Trim()
}

function Assert-Reply([string]$Name, [string]$SessionId, [string]$Payload, [scriptblock]$Check) {
    $reply = Invoke-Agent $SessionId $Payload
    $ok = & $Check $reply
    if (-not $ok) { $script:failures++ }
    Write-Log ("[{0}] {1}" -f ($(if ($ok) { "PASS" } else { "FAIL" })), $Name)
    Write-Log "  session: $SessionId"
    Write-Log "  payload: $Payload"
    Write-Log "  reply:   $reply"
    Write-Log ""
}

$sessionA = "session-a-$([guid]::NewGuid())"
$sessionB = "session-b-$([guid]::NewGuid())"
# An in-scope fact (an order number), since the support agent declines off-topic requests.
$orderRef = "ORD-$(Get-Random -Minimum 1000 -Maximum 9999)"

Write-Log ("Runtime session test, {0}, target: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $(if ($Local) { "local dev server" } else { "deployed runtime" }))
Write-Log ""

$recall = '{"prompt": "Which order number did I mention earlier in this conversation?"}'
Assert-Reply "Session A mentions an order" $sessionA "{`"prompt`": `"Hi, I have a question about my order $orderRef. Please just confirm the order number for now.`"}" { param($r) -not $r.StartsWith("ERROR") }
Assert-Reply "Session A recalls it (same microVM)" $sessionA $recall { param($r) $r -match $orderRef }
Assert-Reply "Session B does not know it (new microVM)" $sessionB $recall { param($r) -not ($r -match $orderRef) -and -not $r.StartsWith("ERROR") }
Assert-Reply "Client-supplied actorId is rejected" $sessionB '{"prompt": "hi", "actorId": "admin"}' { param($r) $r.StartsWith("ERROR INVALID_REQUEST") }
Assert-Reply "Non-string prompt is rejected" $sessionB '{"prompt": 42}' { param($r) $r.StartsWith("ERROR INVALID_REQUEST") }

Write-Log ("Result: {0} failed" -f $script:failures)
if ($OutFile) {
    New-Item -ItemType Directory -Force (Split-Path $OutFile) | Out-Null
    $script:log | Set-Content -Path $OutFile -Encoding utf8
    Write-Host "Saved to $OutFile"
}
exit $script:failures
