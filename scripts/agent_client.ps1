# Shared helpers for the agent test scripts: sign in, invoke the runtime, check replies, save a log.
# Dot-source it: . (Join-Path $PSScriptRoot "agent_client.ps1")

# Read CLI output as UTF-8, otherwise non-ASCII characters in replies get garbled.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$script:AgentRuntime = "support_agent"
$script:AgentLocal = $false
$script:AgentToken = $null
$script:AgentLog = @()
$script:AgentFailures = 0

function Initialize-AgentClient([string]$Runtime = "support_agent", [switch]$Local, [string]$Email) {
    $script:AgentRuntime = $Runtime
    $script:AgentLocal = [bool]$Local
    if ($Local) { return }
    if (-not $Email) { throw "Pass -Email to sign in to the deployed runtime (or -Local for agentcore dev)." }
    # get_token.py prompts for the password itself; the token stays in memory only.
    $script:AgentToken = (& uv run python (Join-Path $PSScriptRoot "get_token.py") --email $Email | Out-String).Trim()
    if ($script:AgentToken.Split(".").Count -ne 3) { throw "Sign-in failed, no access token." }
}

function Write-Log([string]$Line) {
    Write-Host $Line
    $script:AgentLog += $Line
}

function Invoke-Agent([string]$SessionId, [string]$Payload, [switch]$NoToken) {
    # Windows PowerShell 5.1 strips inner quotes when calling native programs, so escape them.
    if ($PSVersionTable.PSVersion.Major -lt 7) { $Payload = $Payload.Replace('"', '\"') }
    $cliArgs = @("invoke", "--runtime", $script:AgentRuntime, "--json", "--session-id", $SessionId, "--payload", $Payload)
    if ($script:AgentLocal) { $cliArgs += "--local" }
    if ($script:AgentToken -and -not $NoToken) { $cliArgs += @("--bearer-token", $script:AgentToken) }

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
    if (-not $ok) { $script:AgentFailures++ }
    Write-Log ("[{0}] {1}" -f ($(if ($ok) { "PASS" } else { "FAIL" })), $Name)
    Write-Log "  session: $SessionId"
    Write-Log "  payload: $Payload"
    Write-Log "  reply:   $reply"
    Write-Log ""
}

# Memory only accepts letters, digits, - and _ in session IDs, so other characters become -.
# Promises no tool can back: when money arrives, or that someone will get in touch.
$script:PromisePattern = "should appear|will appear|appear in your account|reflected in your account|business days|be notified|hear back"

function Test-NoPromise([string]$Reply) { return $Reply -notmatch $script:PromisePattern }

# The session's trace tree from CloudWatch; spans arrive a minute or two after a request.
function Get-SessionTrace([string]$SessionId, [int]$Tries = 6) {
    for ($try = 1; $try -le $Tries; $try++) {
        # Not 2>&1: Windows PowerShell 5.1 turns native stderr into errors that stop the script.
        $tree = & uv run python (Join-Path $PSScriptRoot "find_traces.py") $SessionId | Out-String
        if ($LASTEXITCODE -eq 0) { return $tree }
        Start-Sleep -Seconds 30
    }
    return "no spans found for $SessionId"
}

function New-SessionId([string]$Label) { "session-$($Label -replace '[^A-Za-z0-9_-]', '-')-$([guid]::NewGuid())" }

function Complete-AgentTest([string]$OutFile) {
    if (-not $script:AgentLocal) {
        # Stamps the log with the deployed version it tested.
        Write-Log ("Tested: " + (& uv run python (Join-Path $PSScriptRoot "runtime_version.py") | Out-String).Trim())
    }
    Write-Log ("Result: {0} failed" -f $script:AgentFailures)
    if ($OutFile) {
        New-Item -ItemType Directory -Force (Split-Path $OutFile) | Out-Null
        $script:AgentLog | Set-Content -Path $OutFile -Encoding utf8
        Write-Host "Saved to $OutFile"
    }
    exit $script:AgentFailures
}
