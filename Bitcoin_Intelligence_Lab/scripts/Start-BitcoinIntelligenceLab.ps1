#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$EnableExecution,
    [switch]$OpenBrowser,
    [ValidateRange(0.001,100)][double]$Volume = 0.01,
    [ValidateRange(15,300)][int]$ExecutionIntervalSeconds = 30,
    [ValidateRange(1024,65535)][int]$Port = 8502
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$dataRoot = Join-Path $projectRoot 'data'
$logRoot = Join-Path $dataRoot 'logs'
$commonRoot = Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files\BitcoinIntelligenceLab'
$dashboardUrl = "http://127.0.0.1:$Port"
$healthUrl = "$dashboardUrl/_stcore/health"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual-environment Python is missing: $python. Install the project dependencies first."
}
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

function Get-BitcoinProcesses([string]$Pattern) {
    return @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -like 'python*.exe' -and $_.CommandLine -like $Pattern
    } | ForEach-Object {
        [ordered]@{
            pid = [int]$_.ProcessId
            parent_pid = [int]$_.ParentProcessId
            name = $_.Name
            command_line = $_.CommandLine
        }
    })
}

function Get-HttpStatus([string]$Uri) {
    try {
        return [int](Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5).StatusCode
    } catch {
        return $null
    }
}

function Start-ProjectProcess(
    [string]$Name,
    [string[]]$Arguments,
    [string]$StdoutPath,
    [string]$StderrPath
) {
    if (Test-Path -LiteralPath $StdoutPath) { Remove-Item -LiteralPath $StdoutPath -Force }
    if (Test-Path -LiteralPath $StderrPath) { Remove-Item -LiteralPath $StderrPath -Force }
    return Start-Process -FilePath $python -ArgumentList $Arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath
}

$bootstrap = [ordered]@{
    schema_version = 1
    started_at_utc = [DateTime]::UtcNow.ToString('o')
    project_root = $projectRoot
    data_collector = [ordered]@{ status = 'unknown'; existing_processes = @(); started_pid = $null }
    dashboard = [ordered]@{ status = 'unknown'; url = $dashboardUrl; http_status = $null; existing_processes = @(); started_pid = $null }
    mt5 = [ordered]@{ status = 'not_checked'; reason = $null }
    execution_loop = [ordered]@{ status = 'disabled_by_default'; existing_processes = @(); started_pid = $null }
    trading_activation_requested = [bool]$EnableExecution
    notes = @()
}

# Reuse the currently running collector. Matching parent/child Python
# processes are one collector instance, not independent collectors.
$collector = Get-BitcoinProcesses '*bitcoinlab.market_stream*'
$bootstrap.data_collector.existing_processes = @($collector)
if ($collector.Count -gt 0) {
    $bootstrap.data_collector.status = 'already_running'
} else {
    $stdout = Join-Path $logRoot 'market_stream.stdout.log'
    $stderr = Join-Path $logRoot 'market_stream.stderr.log'
    $started = Start-ProjectProcess -Name 'market_stream' -Arguments @('-m','bitcoinlab.market_stream','--symbol','BTCUSDT','--venues','binance,bybit,okx','--depth','50','--db','data/market_stream.sqlite') -StdoutPath $stdout -StderrPath $stderr
    $bootstrap.data_collector.started_pid = [int]$started.Id
    Start-Sleep -Seconds 2
    $collector = Get-BitcoinProcesses '*bitcoinlab.market_stream*'
    $bootstrap.data_collector.existing_processes = @($collector)
    $bootstrap.data_collector.status = if ($collector.Count -gt 0) { 'started' } else { 'start_requested' }
}

# Reuse a healthy Streamlit server. Never launch a second server on the same port.
$dashboardCode = Get-HttpStatus $healthUrl
$streamlit = Get-BitcoinProcesses '*streamlit*run*app.py*'
$bootstrap.dashboard.http_status = $dashboardCode
$bootstrap.dashboard.existing_processes = @($streamlit)
if ($dashboardCode -eq 200) {
    $bootstrap.dashboard.status = 'already_healthy'
} elseif ($streamlit.Count -gt 0) {
    $bootstrap.dashboard.status = 'process_exists_but_health_failed'
    $bootstrap.notes += 'A Streamlit process exists, but its health endpoint did not return HTTP 200; no duplicate server was started.'
} else {
    $stdout = Join-Path $logRoot 'streamlit.stdout.log'
    $stderr = Join-Path $logRoot 'streamlit.stderr.log'
    $started = Start-ProjectProcess -Name 'streamlit' -Arguments @('-m','streamlit','run','app.py','--server.address','127.0.0.1','--server.port',"$Port",'--browser.gatherUsageStats','false') -StdoutPath $stdout -StderrPath $stderr
    $bootstrap.dashboard.started_pid = [int]$started.Id
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 750
        $dashboardCode = Get-HttpStatus $healthUrl
        if ($dashboardCode -eq 200) { break }
    } while ((Get-Date) -lt $deadline)
    $bootstrap.dashboard.http_status = $dashboardCode
    $bootstrap.dashboard.status = if ($dashboardCode -eq 200) { 'started_and_healthy' } else { 'start_requested_health_pending' }
}

# The live dashboard and data collector are independent from trading execution.
# Execution is never enabled unless the caller passes -EnableExecution.
$execution = Get-BitcoinProcesses '*bitcoinlab.execution_loop*'
$bootstrap.execution_loop.existing_processes = @($execution)
if ($execution.Count -gt 0) {
    $bootstrap.execution_loop.status = 'already_running'
} elseif ($EnableExecution) {
    $eaPath = Join-Path $commonRoot 'ea_status.tsv'
    if (-not (Test-Path -LiteralPath $eaPath)) {
        throw "Trading execution was requested, but the MT5 EA status file is missing: $eaPath"
    }
    $fields = (Get-Content -LiteralPath $eaPath -Raw).Trim().Split([char]'|')
    if ($fields.Length -lt 15 -or $fields[0] -ne 'BTCIL1') {
        throw 'Trading execution was requested, but the MT5 EA status record is malformed or outdated.'
    }
    $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [int64]$fields[3]
    $server = [string]$fields[12]
    $headway = $server.ToLower().Contains('headway') -or $server.ToLower().Contains('trade-hw.online')
    $ready = ($age -ge -5 -and $age -le 45 -and $fields[4] -eq 'CONNECTED' -and $fields[11] -eq 'TRADE_READY' -and $headway -and $fields[1].ToUpper().Contains('BTC'))
    $bootstrap.mt5 = [ordered]@{
        status = if ($ready) { 'ready' } else { 'not_ready' }
        symbol = $fields[1]
        server = $server
        age_seconds = $age
        trade_ready = ($fields[11] -eq 'TRADE_READY')
        headway_server_ok = $headway
    }
    if (-not $ready) {
        throw "Trading execution was requested, but MT5 Headway status is not ready: $($bootstrap.mt5 | ConvertTo-Json -Compress)"
    }

    $previousFlag = $env:BTCIL_ENABLE_EXECUTION
    try {
        $env:BTCIL_ENABLE_EXECUTION = '1'
        $stdout = Join-Path $logRoot 'execution_loop.stdout.log'
        $stderr = Join-Path $logRoot 'execution_loop.stderr.log'
        $started = Start-ProjectProcess -Name 'execution_loop' -Arguments @('-m','bitcoinlab.execution_loop','--interval-seconds',"$ExecutionIntervalSeconds",'--volume',"$Volume") -StdoutPath $stdout -StderrPath $stderr
        $bootstrap.execution_loop.started_pid = [int]$started.Id
        Start-Sleep -Seconds 2
        $execution = Get-BitcoinProcesses '*bitcoinlab.execution_loop*'
        $bootstrap.execution_loop.existing_processes = @($execution)
        $bootstrap.execution_loop.status = if ($execution.Count -gt 0) { 'started' } else { 'start_requested' }
    } finally {
        if ($null -eq $previousFlag) { Remove-Item Env:BTCIL_ENABLE_EXECUTION -ErrorAction SilentlyContinue }
        else { $env:BTCIL_ENABLE_EXECUTION = $previousFlag }
    }
} else {
    $bootstrap.execution_loop.status = 'disabled_by_default'
    $bootstrap.notes += 'The execution loop was not started. Pass -EnableExecution only when you explicitly want automatic trade execution.'
}

if ($OpenBrowser -and $bootstrap.dashboard.http_status -eq 200) {
    Start-Process -FilePath $dashboardUrl
    $bootstrap.notes += 'Opened the healthy dashboard URL in the Windows default browser.'
}

$bootstrap.completed_at_utc = [DateTime]::UtcNow.ToString('o')
$reportPath = Join-Path $dataRoot 'system_bootstrap_last.json'
$bootstrap | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
$bootstrap | ConvertTo-Json -Depth 8
Write-Output "BOOTSTRAP_REPORT=$reportPath"
