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
. (Join-Path $PSScriptRoot "agent_client.ps1")
Initialize-AgentClient -Runtime $Runtime -Local:$Local -Email $Email
if ($Local) { $CustomerId = "CUST-1001" }  # the local dev caller

$sessionA = New-SessionId "a"
$sessionB = New-SessionId "b"
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

Complete-AgentTest $OutFile
