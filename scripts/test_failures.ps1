# Failure drills: a slow tool, a failing backend, a polling loop, an invalid amount and a bad session ID.
# Usage: .\scripts\test_failures.ps1 -Email alex.morgan@example.com [-OutFile docs\evidence\failure-drills.txt] [-SkipTraces]
# Needs the backend deployed with: cdk deploy -c fault_injection=enabled (redeploy without it afterwards).
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [string]$Runtime = "support_agent",
    [string]$OutFile,
    # Skips waiting for spans and printing each drill's trace tree.
    [switch]$SkipTraces
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "agent_client.ps1")

function Invoke-ReadTool([string]$OrderId) {
    $raw = & uv run python (Join-Path $PSScriptRoot "invoke_tool.py") get_order_status customer_id=CUST-1001 order_id=$OrderId | Out-String
    return $raw | ConvertFrom-Json
}

function Get-RefundedTotal {
    $data = (Invoke-ReadTool "124").data
    if ($null -eq $data.refunded_total) { return 0 } else { return [double]$data.refunded_total }
}

# Order 901 always fails when fault injection is on; anything else means it is off.
if ((Invoke-ReadTool "901").error.code -ne "BACKEND_UNAVAILABLE") {
    throw "Fault injection is off. Deploy the backend with: cdk deploy -c fault_injection=enabled"
}

& uv run python (Join-Path $PSScriptRoot "seed_data.py") | Out-Null
Initialize-AgentClient -Runtime $Runtime -Email $Email

Write-Log ("Failure drills, {0}, signed in as CUST-1001" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Log ""

# The guardrail's fixed reply; a drill that gets it never reached the part it tests.
$notBlocked = { param($r) (-not $r.StartsWith("ERROR")) -and ($r -notmatch "can't help with that request") }
# The agent must admit it cannot answer, never invent an order status.
$noInventedStatus = { param($r) (& $notBlocked $r) -and ($r -notmatch "SHIPPED|DELIVERED|DELAYED|shipped|delivered") }
$sessions = [ordered]@{}

$sessions["Slow tool"] = New-SessionId "drill-slow"
Assert-Reply "Slow tool: Lambda timeout is retried, then reported honestly" $sessions["Slow tool"] '{"prompt": "What is the status of my order 900?"}' $noInventedStatus

$sessions["Failing backend"] = New-SessionId "drill-failing"
Assert-Reply "Failing backend: retryable error is retried 3 times, then reported" $sessions["Failing backend"] '{"prompt": "What is the status of my order 901?"}' $noInventedStatus

$sessions["Polling loop"] = New-SessionId "drill-loop"
Assert-Reply "Polling loop: the loop guard stops repeated identical calls" $sessions["Polling loop"] '{"prompt": "Check the status of my order 902. If it is still processing, check it again right away, up to 5 times, then tell me the final status."}' $notBlocked

$before = Get-RefundedTotal
$sessions["Invalid amount"] = New-SessionId "drill-invalid"
$reply = Invoke-Agent $sessions["Invalid amount"] '{"prompt": "Refund minus 5 dollars for order 124, the mug was chipped."}'
$after = Get-RefundedTotal
$ok = ($after -eq $before) -and (& $notBlocked $reply)
if (-not $ok) { $script:AgentFailures++ }
Write-Log ("[{0}] Invalid amount: no money moves, the agent asks for the exact amount" -f ($(if ($ok) { "PASS" } else { "FAIL" })))
Write-Log "  session: $($sessions["Invalid amount"])"
Write-Log "  refunded_total for order 124: $before -> $after"
Write-Log "  reply:   $reply"
Write-Log ""

# Spaces are not allowed in session IDs; the agent must reject it cleanly, not crash.
$sessions["Bad session ID"] = "drill bad session id with spaces $([guid]::NewGuid())"
Assert-Reply "Bad session ID: rejected as INVALID_REQUEST, not INTERNAL_ERROR" $sessions["Bad session ID"] '{"prompt": "Hello"}' { param($r) $r -match "ERROR INVALID_REQUEST" }

if (-not $SkipTraces) {
    Write-Host "Waiting 2 minutes for the spans to reach CloudWatch..."
    Start-Sleep -Seconds 120
    foreach ($drill in $sessions.Keys) {
        Write-Log "===== Trace of drill: $drill ====="
        # Spans can lag; find_traces.py exits non-zero until they arrive.
        # Not 2>&1: Windows PowerShell 5.1 turns native stderr into errors that stop the script.
        for ($try = 1; $try -le 4; $try++) {
            $tree = & uv run python (Join-Path $PSScriptRoot "find_traces.py") $sessions[$drill] | Out-String
            if ($LASTEXITCODE -eq 0) { break }
            Start-Sleep -Seconds 30
        }
        foreach ($line in ($tree -split "`r?`n")) { Write-Log $line }
    }
}

Complete-AgentTest $OutFile
