# Checks that asking for the same refund again does not pay twice: the agent's code reuses the idempotency key,
# and that the brief's own key, operation-123, sent twice through the Gateway, returns one refund.
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
Assert-Reply "First request answered" $session '{"prompt": "Please refund 5 USD for order 124, the mug arrived chipped."}' { param($r) (-not $r.StartsWith("ERROR")) -and (Test-NoPromise $r) }
$afterFirst = Get-RefundedTotal

Assert-Reply "Same request again replays it" $session '{"prompt": "I am not sure that went through. Please do the same refund of 5 USD for order 124 again."}' { param($r) (-not $r.StartsWith("ERROR")) -and (Test-NoPromise $r) }
$afterSecond = Get-RefundedTotal

$ok = ($afterFirst - $start -eq 5) -and ($afterSecond -eq $afterFirst)
if (-not $ok) { $script:AgentFailures++ }
Write-Log ("[{0}] Money moved once: refunded_total {1} -> {2} -> {3}" -f ($(if ($ok) { "PASS" } else { "FAIL" })), $start, $afterFirst, $afterSecond)
Write-Log ""

# The brief's example: the same operation with idempotency_key "operation-123", retried, skipping the LLM.
function Invoke-BriefRefund {
    $raw = & uv run python (Join-Path $PSScriptRoot "call_gateway.py") refunds___refund_customer customer_id=CUST-1001 order_id=124 amount=5 amount_cents=500 reason=Brief-example idempotency_key=operation-123 | Out-String
    return (($raw | ConvertFrom-Json).result.content[0].text | ConvertFrom-Json)
}
$beforeBrief = Get-RefundedTotal
$first = Invoke-BriefRefund
$afterBrief1 = Get-RefundedTotal
$retry = Invoke-BriefRefund
$afterBrief2 = Get-RefundedTotal
$ok = $first.ok -and $retry.ok -and ($first.data.refund_id -eq $retry.data.refund_id) -and ($retry.data.replayed -eq $true) -and ($afterBrief1 - $beforeBrief -eq 5) -and ($afterBrief2 -eq $afterBrief1)
if (-not $ok) { $script:AgentFailures++ }
Write-Log ("[{0}] operation-123 sent twice: one refund, the retry replays it" -f ($(if ($ok) { "PASS" } else { "FAIL" })))
Write-Log ("  first: {0}, replayed={1} | retry: {2}, replayed={3}" -f $first.data.refund_id, $first.data.replayed, $retry.data.refund_id, $retry.data.replayed)
Write-Log ("  refunded_total {0} -> {1} -> {2}" -f $beforeBrief, $afterBrief1, $afterBrief2)
Write-Log ""

Complete-AgentTest $OutFile
