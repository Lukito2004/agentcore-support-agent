# Checks human approval: small refunds complete at once, larger ones wait for a reviewer, a rejection gives the money back.
# Usage: .\scripts\test_approval.ps1 -Email alex.morgan@example.com [-OutFile docs\evidence\refund-approval.txt] [-WaitForTimeout]
# Re-seeds the demo data first so order 129 (899.00 USD) starts with nothing refunded.
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [string]$Runtime = "support_agent",
    [string]$OutFile,
    # Also leaves one refund undecided and waits for the review to expire.
    [switch]$WaitForTimeout,
    # Must match the stack's ApprovalTimeoutMinutes output.
    [int]$TimeoutMinutes = 15
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "agent_client.ps1")

$review = Join-Path $PSScriptRoot "approve_refund.py"

function Get-Totals {
    $raw = & uv run python (Join-Path $PSScriptRoot "invoke_tool.py") get_order_status customer_id=CUST-1001 order_id=129 | Out-String
    $data = ($raw | ConvertFrom-Json).data
    return "refunded {0}, pending {1}" -f [double]$data.refunded_total, [double]$data.pending_refund_total
}

function Get-PendingRefunds {
    # The leading comma keeps a one-item list a list; PowerShell 5.1 would unwrap it.
    return ,@(((& uv run python $review list --order 129 --json | Out-String) | ConvertFrom-Json).refunds)
}

function Get-Refund([string]$RefundId) {
    return (& uv run python $review show $RefundId | Out-String) | ConvertFrom-Json
}

function Invoke-Review([string]$Action, [string]$RefundId, [string]$Note) {
    $out = & uv run python $review $Action $RefundId --note $Note | Out-String
    if (-not $out.Trim()) { return [pscustomobject]@{ status = "REVIEW FAILED" } }
    return $out | ConvertFrom-Json
}

function Write-Check([string]$Name, [bool]$Ok, [string]$Detail) {
    if (-not $Ok) { $script:AgentFailures++ }
    Write-Log ("[{0}] {1}" -f ($(if ($Ok) { "PASS" } else { "FAIL" })), $Name)
    Write-Log "  $Detail"
    Write-Log ""
}

# Asks for a refund that needs review, then returns the one pending refund it created.
function Request-ReviewedRefund([string]$Label, [string]$Prompt, [double]$Amount, [string]$ExpectedTotals) {
    Assert-Reply "$Label waits for review" (New-SessionId $Label) $Prompt { param($r) $r -match "review|approv" }
    $pending = Get-PendingRefunds
    $totals = Get-Totals
    $ok = ($pending.Count -eq 1) -and ([double]$pending[0].amount -eq $Amount) -and ($totals -eq $ExpectedTotals)
    Write-Check "$Label is held, not paid" $ok ("{0} pending refund(s), order 129: {1}" -f $pending.Count, $totals)
    if ($pending.Count -eq 1) { return $pending[0].refund_id } else { return $null }
}

# Re-seeding drops held amounts, so an older review ending later would corrupt this run's totals.
if ((Get-PendingRefunds).Count -gt 0) {
    throw "Order 129 has refunds waiting for review. Reject them with approve_refund.py or wait for them to expire."
}
& uv run python (Join-Path $PSScriptRoot "seed_data.py") | Out-Null
Initialize-AgentClient -Runtime $Runtime -Email $Email

Write-Log ("Refund approval, {0}, signed in as CUST-1001, order 129 (899.00 USD)" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Log ""

# 1. Below the threshold: no review.
Assert-Reply "100 USD refund is answered" (New-SessionId "small") '{"prompt": "Please refund 100 USD for order 129, the vacuum arrived scratched."}' { param($r) -not $r.StartsWith("ERROR") }
$totals = Get-Totals
Write-Check "100 USD refund completed right away" (($totals -eq "refunded 100, pending 0") -and ((Get-PendingRefunds).Count -eq 0)) "order 129: $totals"

# 2. 700 USD needs review; the reviewer approves it.
$id = Request-ReviewedRefund "700 USD refund" '{"prompt": "Please refund 700 USD for order 129, the vacuum stopped working after a week."}' 700 "refunded 800, pending 700"
if ($id) {
    $decided = Invoke-Review "approve" $id "Checked the photos"
    $totals = Get-Totals
    Write-Check "Approved refund is completed" (($decided.status -eq "COMPLETED") -and ($totals -eq "refunded 800, pending 0")) "$id is $($decided.status), order 129: $totals"
}

# 3. 50 USD alone is small, but the order's refunds would reach 500 USD, so splitting does not skip review.
$id = Request-ReviewedRefund "50 USD refund after 800 USD" '{"prompt": "Please also refund 50 USD for order 129, the delivery was late."}' 50 "refunded 850, pending 50"
if ($id) {
    $decided = Invoke-Review "reject" $id "Late delivery is not refundable for this order"
    $totals = Get-Totals
    Write-Check "Rejected refund gives the held amount back" (($decided.status -eq "REJECTED") -and ($totals -eq "refunded 800, pending 0")) "$id is $($decided.status), order 129: $totals"
}

# 4. Optional: nobody decides, so the review expires and the held amount is given back.
if ($WaitForTimeout) {
    $id = Request-ReviewedRefund "40 USD refund" '{"prompt": "Please refund 40 USD for order 129, the charging dock is missing."}' 40 "refunded 840, pending 40"
    if ($id) {
        Write-Host "Waiting up to $($TimeoutMinutes + 2) minutes for the review of $id to expire..."
        $deadline = (Get-Date).AddMinutes($TimeoutMinutes + 2)
        do { Start-Sleep -Seconds 30; $refund = Get-Refund $id } while ($refund.status -eq "PENDING_APPROVAL" -and (Get-Date) -lt $deadline)
        $totals = Get-Totals
        Write-Check "Undecided refund expires and gives the held amount back" (($refund.status -eq "EXPIRED") -and ($totals -eq "refunded 800, pending 0")) "$id is $($refund.status) ($($refund.decision_note)), order 129: $totals"
    }
}

Complete-AgentTest $OutFile
