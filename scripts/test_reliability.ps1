# Checks that asking for the same refund again does not pay twice: the agent's code reuses the idempotency key.
# Usage: .\scripts\test_reliability.ps1 -Email alex.morgan@example.com [-OutFile docs\evidence\refund-retry-no-duplicate.txt]
# Re-seeds the demo data first so order 124 (25.00 USD) starts with nothing refunded.
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [string]$Runtime = "support_agent",
    [string]$OutFile
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "agent_client.ps1")

function Get-RefundedTotal {
    $raw = & uv run python (Join-Path $PSScriptRoot "invoke_tool.py") get_order_status customer_id=CUST-1001 order_id=124 | Out-String
    $data = ($raw | ConvertFrom-Json).data
    if ($null -eq $data.refunded_total) { return 0 } else { return [double]$data.refunded_total }
}

& uv run python (Join-Path $PSScriptRoot "seed_data.py") | Out-Null
Initialize-AgentClient -Runtime $Runtime -Email $Email

Write-Log ("Refund retry without duplicates, {0}, signed in as CUST-1001" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Log ""

$session = New-SessionId "retry"
$start = Get-RefundedTotal
# Replies are logged as context; only the money check below decides pass or fail.
Assert-Reply "First request answered" $session '{"prompt": "Please refund 5 USD for order 124, the mug arrived chipped."}' { param($r) -not $r.StartsWith("ERROR") }
$afterFirst = Get-RefundedTotal

Assert-Reply "Same request again replays it" $session '{"prompt": "I am not sure that went through. Please do the same refund of 5 USD for order 124 again."}' { param($r) -not $r.StartsWith("ERROR") }
$afterSecond = Get-RefundedTotal

$ok = ($afterFirst - $start -eq 5) -and ($afterSecond -eq $afterFirst)
if (-not $ok) { $script:AgentFailures++ }
Write-Log ("[{0}] Money moved once: refunded_total {1} -> {2} -> {3}" -f ($(if ($ok) { "PASS" } else { "FAIL" })), $start, $afterFirst, $afterSecond)
Write-Log ""

Complete-AgentTest $OutFile
