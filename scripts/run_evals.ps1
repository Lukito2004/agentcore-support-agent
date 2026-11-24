# Replays evals/scenarios.jsonl against the deployed agent and scores every session with AgentCore Evaluations.
# Usage: .\scripts\run_evals.ps1 -Email alex.morgan@example.com [-OutFile docs\evidence\evals.txt]
# Re-seeds the demo data first. Refunds the run leaves waiting for review are rejected at the end.
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [string]$Dataset = "evals/scenarios.jsonl",
    [string]$OutFile
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

function Get-Output([string]$Stack, [string[]]$Parts) {
    $value = (& uv run python (Join-Path $PSScriptRoot "stack_outputs.py") $Stack @Parts | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "No output in $Stack matching $($Parts -join ', '). Is it deployed?" }
    return $value
}

$agentStack = "AgentCore-SupportAgent-default"
$runtimeId = Get-Output $agentStack @("Runtime", "IdOutput")
$customEvaluator = Get-Output $agentStack @("Evaluator", "RefundArguments", "IdOutput")
$evaluators = @(
    "Builtin.ToolSelectionAccuracy",
    "Builtin.ToolParameterAccuracy",
    "Builtin.TrajectoryInOrderMatch",
    "Builtin.Faithfulness",
    "Builtin.InstructionFollowing",
    "Builtin.Correctness",
    "Builtin.GoalSuccessRate",
    $customEvaluator
)

& uv run python (Join-Path $PSScriptRoot "seed_data.py") | Out-Null
# get_token.py prompts for the password itself; the token stays in memory only.
$token = (& uv run python (Join-Path $PSScriptRoot "get_token.py") --email $Email | Out-String).Trim()
if ($token.Split(".").Count -ne 3) { throw "Sign-in failed, no access token." }

# Windows PowerShell 5.1 strips inner quotes when calling native programs, so escape them.
$template = '{"prompt":"{input}"}'
if ($PSVersionTable.PSVersion.Major -lt 7) { $template = $template.Replace('"', '\"') }

Write-Host "Running $Dataset against $runtimeId. Spans need about 3 minutes before scoring starts..."
$started = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
# Errors go to stderr; capture them as text so a failed run says why. "Continue" because
# Windows PowerShell 5.1 turns redirected native stderr into errors that would stop the script.
$ErrorActionPreference = "Continue"
$scores = & agentcore eval ondemand simulate --runtime-id $runtimeId --bearer-token $token `
    --payload-template $template --dataset $Dataset --evaluators @evaluators 2>&1 |
    ForEach-Object { "$_" } | Out-String
$failed = $LASTEXITCODE
$ErrorActionPreference = "Stop"

# A review left pending would hold money on order 129 and block the other test scripts.
$pending = ((& uv run python (Join-Path $PSScriptRoot "approve_refund.py") list --json | Out-String) | ConvertFrom-Json).refunds
foreach ($refund in @($pending)) {
    if ($refund) { & uv run python (Join-Path $PSScriptRoot "approve_refund.py") reject $refund.refund_id --note "Evaluation run" | Out-Null }
}

$report = @(
    "AgentCore Evaluations, $started, signed in as CUST-1001",
    "Dataset: $Dataset",
    "Evaluators: $($evaluators -join ', ')",
    "",
    $scores.TrimEnd()
)
if ($failed -ne 0) { $report += @("", "RUN FAILED (exit code $failed); nothing was saved.") }
$report | ForEach-Object { Write-Host $_ }
if ($OutFile -and $failed -eq 0) {
    New-Item -ItemType Directory -Force (Split-Path $OutFile) | Out-Null
    $report | Set-Content -Path $OutFile -Encoding utf8
    $summary = $OutFile -replace '\.txt$', '-summary.md'
    & uv run python (Join-Path $PSScriptRoot "summarize_evals.py") $OutFile --out $summary
    Write-Host "Saved to $OutFile and $summary"
}
exit $failed
