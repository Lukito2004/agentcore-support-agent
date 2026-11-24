# Wrong-tool drill: with the read tools' descriptions swapped, does the agent pick the wrong tool, and do its traces show it?
# Usage: .\scripts\test_wrong_tool.ps1 -Email alex.morgan@example.com [-Sessions 5] [-OutFile docs\evidence\wrong-tool-drill.txt]
# Needs the drill schema deployed: uv run python scripts/toggle_wrong_tool_drill.py on, then agentcore deploy. Switch it off again afterwards.
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [int]$Sessions = 5,
    [string]$Runtime = "support_agent",
    [string]$OutFile
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "agent_client.ps1")

$wrongTool = "customer-orders___get_customer"
$rightTool = "customer-orders___get_order_status"

Initialize-AgentClient -Runtime $Runtime -Email $Email
Write-Log ("Wrong-tool drill, {0}, signed in as CUST-1001, {1} sessions" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Sessions)
Write-Log "The deployed schema swaps the descriptions of get_customer and get_order_status."
Write-Log ""

$ids = @()
for ($i = 1; $i -le $Sessions; $i++) {
    $id = New-SessionId "wrong-tool-$i"
    $ids += $id
    $reply = Invoke-Agent $id '{"prompt": "Why is my order 123 delayed?"}'
    Write-Log "Session ${i}: $id"
    Write-Log "  reply: $reply"
}
Write-Log ""

Write-Host "Waiting 2 minutes for the spans to reach CloudWatch..."
Start-Sleep -Seconds 120

$wrong = 0
foreach ($id in $ids) {
    # Spans can lag; find_traces.py exits non-zero until they arrive.
    for ($try = 1; $try -le 4; $try++) {
        $tree = & uv run python (Join-Path $PSScriptRoot "find_traces.py") $id | Out-String
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 30
    }
    $tools = @([regex]::Matches($tree, "execute_tool (\S+)") | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
    $isWrong = ($tools -contains $wrongTool) -and -not ($tools -contains $rightTool)
    if ($isWrong) { $wrong++ }
    Write-Log ("[{0}] {1}: tools called: {2}" -f ($(if ($isWrong) { "WRONG TOOL" } else { "RIGHT TOOL" })), $id, ($(if ($tools) { $tools -join ", " } else { "none" })))
    if ($isWrong) { foreach ($line in ($tree -split "`r?`n")) { Write-Log "    $line" } }
}
Write-Log ""
Write-Log "Wrong tool selections: $wrong of $Sessions"
Write-Log ""

# Scoring is done by the evaluations (ToolSelectionAccuracy in run_evals.ps1); the traces above are the evidence here.
Complete-AgentTest $OutFile
