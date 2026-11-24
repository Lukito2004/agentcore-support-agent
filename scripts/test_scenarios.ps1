# Checks the business scenarios end to end: Runtime -> Gateway (MCP) -> Lambda tools -> DynamoDB.
# Usage: .\scripts\test_scenarios.ps1 -Email alex.morgan@example.com [-OutFile docs\evidence\gateway-tools.txt]
# Expects the seeded data and a user linked to CUST-1001 (Alex Morgan).
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [string]$Runtime = "support_agent",
    [string]$OutFile
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "agent_client.ps1")
Initialize-AgentClient -Runtime $Runtime -Email $Email

Write-Log ("Gateway tool scenarios, {0}, signed in as CUST-1001" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Log ""

$session = New-SessionId "scenarios"
# A fresh key each run, so the refund check creates a new refund instead of replaying an old one.
$refundKey = "operation-$([guid]::NewGuid().ToString('N').Substring(0, 12))"

Assert-Reply "Agent checks an order (delay reason from DynamoDB)" $session '{"prompt": "Why is my order 123 delayed?"}' { param($r) $r -match "warehouse zone 4" }
Assert-Reply "Agent retrieves customer information" $session '{"prompt": "What is my membership tier?"}' { param($r) $r -match "gold" }
Assert-Reply "Another customer's order is not revealed" (New-SessionId "foreign") '{"prompt": "What is the status of order 125?"}' { param($r) -not ($r -match "1299|1,299|laptop|FedEx") }
Assert-Reply "Agent processes a small refund" (New-SessionId "refund") "{`"prompt`": `"Please refund 5 USD for order 124, the mug arrived chipped. Use idempotency key $refundKey.`"}" { param($r) $r -match "RF-|refund(ed)?" -and -not $r.StartsWith("ERROR") }

Complete-AgentTest $OutFile
