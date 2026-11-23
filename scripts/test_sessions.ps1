# Checks runtime auth and session behavior: sign-in is required, same session keeps context, a new session does not, bad payloads are rejected.
# Usage: .\scripts\test_sessions.ps1 -Email alex.morgan@example.com [-CustomerId CUST-1001] [-OutFile docs\evidence\runtime-session-isolation.txt]
#        .\scripts\test_sessions.ps1 -Local   (against `agentcore dev`, which has no authorizer)
param(
    [switch]$Local,
    [string]$Email,
    [string]$CustomerId = "CUST-1001",
    [string]$Runtime = "support_agent",
    [string]$OutFile
)

$ErrorActionPreference = "Stop"
$script:log = @()
$script:failures = 0
$script:token = $null

function Write-Log([string]$Line) {
    Write-Host $Line
    $script:log += $Line
}

function Invoke-Agent([string]$SessionId, [string]$Payload, [switch]$NoToken) {
    # Windows PowerShell 5.1 strips inner quotes when calling native programs, so escape them.
    if ($PSVersionTable.PSVersion.Major -lt 7) { $Payload = $Payload.Replace('"', '\"') }
    $cliArgs = @("invoke", "--runtime", $Runtime, "--json", "--session-id", $SessionId, "--payload", $Payload)
    if ($Local) { $cliArgs += "--local" }
    if ($script:token -and -not $NoToken) { $cliArgs += @("--bearer-token", $script:token) }

    try {
        $result = (& agentcore @cliArgs 2>$null | Out-String) | ConvertFrom-Json
    } catch {
        return "CLI ERROR: request was not accepted"
    }
    if ($result.statusCode -ge 400) { return "HTTP $($result.statusCode): $($result.body)" }
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

function Assert-Reply([string]$Name, [string]$SessionId, [string]$Payload, [scriptblock]$Check, [switch]$NoToken) {
    $reply = Invoke-Agent $SessionId $Payload -NoToken:$NoToken
    $ok = & $Check $reply
    if (-not $ok) { $script:failures++ }
    Write-Log ("[{0}] {1}" -f ($(if ($ok) { "PASS" } else { "FAIL" })), $Name)
    Write-Log "  session: $SessionId"
    Write-Log "  payload: $Payload"
    Write-Log "  reply:   $reply"
    Write-Log ""
}

if (-not $Local) {
    if (-not $Email) { throw "Pass -Email to sign in to the deployed runtime (or -Local for agentcore dev)." }
    # get_token.py prompts for the password itself; the token stays in memory only.
    $script:token = (& uv run python (Join-Path $PSScriptRoot "get_token.py") --email $Email | Out-String).Trim()
    if ($script:token.Split(".").Count -ne 3) { throw "Sign-in failed, no access token." }
}
if ($Local) { $CustomerId = "CUST-1001" }  # the local dev caller

$sessionA = "session-a-$([guid]::NewGuid())"
$sessionB = "session-b-$([guid]::NewGuid())"
# An in-scope fact (an order number), since the support agent declines off-topic requests.
$orderRef = "ORD-$(Get-Random -Minimum 1000 -Maximum 9999)"

Write-Log ("Runtime session test, {0}, target: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $(if ($Local) { "local dev server" } else { "deployed runtime" }))
Write-Log ""

if (-not $Local) {
    Assert-Reply "Call without a sign-in token is rejected" $sessionA '{"prompt": "hi"}' { param($r) $r -match "^(HTTP 40[13]|CLI ERROR)" } -NoToken
}
$recall = '{"prompt": "Which order number did I mention earlier in this conversation?"}'
Assert-Reply "Agent knows the signed-in customer" $sessionA '{"prompt": "Which customer ID am I signed in as?"}' { param($r) $r -match $CustomerId }
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
