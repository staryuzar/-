#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateRange(5,120)][int]$PollSeconds = 15,
    [ValidateRange(15,300)][int]$ExecutionIntervalSeconds = 30,
    [ValidateRange(0.001,1)][double]$VolumeCap = 0.01,
    [ValidateRange(5,900)][int]$MaxSnapshotAgeSeconds = 90
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$dataRoot = Join-Path $projectRoot 'data'
$logRoot = Join-Path $dataRoot 'logs'
$commonRoot = Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files\BitcoinIntelligenceLab'
$eaStatusPath = Join-Path $commonRoot 'ea_status.tsv'
$snapshotPath = Join-Path $dataRoot 'live_snapshot.json'
$snapshotStatusPath = Join-Path $dataRoot 'live_snapshot_service_status.json'
$supervisorStatusPath = Join-Path $dataRoot 'supervisor_status.json'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Runtime Python is missing: $python"
}
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$invariant = [Globalization.CultureInfo]::InvariantCulture

function Get-BitcoinProcesses([string]$Pattern) {
    return @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -like 'python*.exe' -and $_.CommandLine -like $Pattern
    })
}

function Start-BitcoinProcess([string]$Name, [string[]]$Arguments) {
    $stdout = Join-Path $logRoot ($Name + '.stdout.log')
    $stderr = Join-Path $logRoot ($Name + '.stderr.log')
    return Start-Process -FilePath $python -ArgumentList $Arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
}

function Get-HealthySnapshot {
    $result = [ordered]@{ ready = $false; snapshot_age_seconds = $null; service_age_seconds = $null; reason = 'snapshot_unavailable' }
    try {
        if (-not (Test-Path -LiteralPath $snapshotPath) -or -not (Test-Path -LiteralPath $snapshotStatusPath)) {
            return $result
        }
        $snapshotEnvelope = Get-Content -LiteralPath $snapshotPath -Raw | ConvertFrom-Json
        $service = Get-Content -LiteralPath $snapshotStatusPath -Raw | ConvertFrom-Json
        if ($snapshotEnvelope.schema -ne 'BTCIL-SNAPSHOT1' -or $service.schema -ne 'BTCIL-SNAPSHOT-SERVICE1') {
            $result.reason = 'snapshot_schema_invalid'
            return $result
        }
        $snapshotTime = [DateTimeOffset]::Parse([string]$snapshotEnvelope.snapshot.as_of_utc).ToUniversalTime()
        $serviceTime = [DateTimeOffset]::Parse([string]$service.updated_at_utc).ToUniversalTime()
        $result.snapshot_age_seconds = [math]::Round(([DateTimeOffset]::UtcNow - $snapshotTime).TotalSeconds, 2)
        $result.service_age_seconds = [math]::Round(([DateTimeOffset]::UtcNow - $serviceTime).TotalSeconds, 2)
        if ($service.status -ne 'healthy') {
            $result.reason = 'snapshot_service_unhealthy'
        } elseif ($result.snapshot_age_seconds -lt -5 -or $result.snapshot_age_seconds -gt $MaxSnapshotAgeSeconds) {
            $result.reason = 'snapshot_stale'
        } elseif ($result.service_age_seconds -lt -5 -or $result.service_age_seconds -gt 90) {
            $result.reason = 'snapshot_heartbeat_stale'
        } else {
            $result.ready = $true
            $result.reason = 'ready'
        }
    } catch {
        $result.reason = 'snapshot_read_error: ' + $_.Exception.Message
    }
    return $result
}

function Get-ExecutionGate {
    $gate = [ordered]@{
        ready = $false
        management_ready = $false
        entry_ready = $false
        blockers = @()
        management_blockers = @()
        entry_blockers = @()
        field_count = 0
        symbol = $null
        server = $null
        age_seconds = $null
        equity = $null
        tick_size = $null
        tick_value_loss = $null
        volume_min = $null
        volume_step = $null
        volume_max = $null
        risk_specs_ready = $false
        daily_loss_percent = $null
        daily_loss_limit_percent = $null
        snapshot = $null
    }

    if (-not (Test-Path -LiteralPath $eaStatusPath)) {
        $gate.management_blockers += 'ea_status_missing'
        $gate.entry_blockers += 'ea_status_missing'
        $gate.blockers = @($gate.entry_blockers)
        return $gate
    }

    try {
        $fields = (Get-Content -LiteralPath $eaStatusPath -Raw).Trim().Split([char]'|')
        $gate.field_count = $fields.Length
        # Fifteen fields are sufficient to monitor the current EA and manage
        # its owned positions. The six broker-risk fields authorize new entries only.
        if ($fields.Length -lt 15 -or $fields[0] -ne 'BTCIL1') {
            $gate.management_blockers += 'ea_status_incomplete'
            $gate.entry_blockers += 'ea_status_incomplete'
            $gate.blockers = @($gate.entry_blockers)
            return $gate
        }

        $stamp = [int64]$fields[3]
        $gate.age_seconds = [math]::Round(([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $stamp), 2)
        $gate.symbol = [string]$fields[1]
        $gate.server = [string]$fields[12]
        $gate.daily_loss_percent = [double]::Parse($fields[13], $invariant)
        $gate.daily_loss_limit_percent = [double]::Parse($fields[14], $invariant)

        if ($gate.age_seconds -lt -5 -or $gate.age_seconds -gt 45) { $gate.management_blockers += 'ea_heartbeat_stale' }
        if ($fields[4] -ne 'CONNECTED') { $gate.management_blockers += 'mt5_not_connected' }
        if ($fields[11] -ne 'TRADE_READY') { $gate.management_blockers += 'mt5_trade_not_ready' }
        if ($gate.symbol -notmatch '(?i)BTC') { $gate.management_blockers += 'wrong_mt5_symbol' }
        if ($gate.server -notmatch '(?i)(headway|trade-hw\.online)') { $gate.management_blockers += 'not_headway_server' }
        # Headway broker identity is mandatory; demo/live classification is not
        # an execution gate. Fresh status, real broker specs and daily risk limits
        # remain mandatory for entries; terminal permission remains mandatory
        # for management and broker-side protection.
        if (
            [double]::IsNaN($gate.daily_loss_percent) -or
            [double]::IsInfinity($gate.daily_loss_percent) -or
            $gate.daily_loss_percent -lt 0 -or
            [double]::IsNaN($gate.daily_loss_limit_percent) -or
            [double]::IsInfinity($gate.daily_loss_limit_percent) -or
            $gate.daily_loss_limit_percent -le 0
        ) {
            $gate.management_blockers += 'daily_risk_status_invalid'
        }

        if ($fields.Length -ge 21) {
            try {
                $gate.equity = [double]::Parse($fields[15], $invariant)
                $gate.tick_size = [double]::Parse($fields[16], $invariant)
                $gate.tick_value_loss = [double]::Parse($fields[17], $invariant)
                $gate.volume_min = [double]::Parse($fields[18], $invariant)
                $gate.volume_step = [double]::Parse($fields[19], $invariant)
                $gate.volume_max = [double]::Parse($fields[20], $invariant)
                $riskValues = @($gate.equity, $gate.tick_size, $gate.tick_value_loss, $gate.volume_min, $gate.volume_step, $gate.volume_max)
                $gate.risk_specs_ready = $true
                foreach ($value in $riskValues) {
                    if ([double]::IsNaN($value) -or [double]::IsInfinity($value) -or $value -le 0) {
                        $gate.risk_specs_ready = $false
                    }
                }
                if ($gate.volume_max -lt $gate.volume_min) { $gate.risk_specs_ready = $false }
            } catch {
                $gate.risk_specs_ready = $false
            }
        }

        if (-not $gate.risk_specs_ready) {
            $gate.entry_blockers += 'ea_broker_risk_specs_missing_or_invalid'
        }
        if (
            $gate.daily_loss_percent -ge 0 -and
            $gate.daily_loss_limit_percent -gt 0 -and
            $gate.daily_loss_percent -ge $gate.daily_loss_limit_percent
        ) {
            $gate.entry_blockers += 'daily_loss_limit_reached_or_invalid'
        }

        $terminal = @(Get-CimInstance Win32_Process | Where-Object {
            $_.Name -ieq 'terminal64.exe' -and $_.ExecutablePath -match '(?i)Headway'
        })
        if ($terminal.Count -eq 0) { $gate.management_blockers += 'headway_terminal_not_running' }

        $gate.snapshot = Get-HealthySnapshot
        if (-not $gate.snapshot.ready) { $gate.management_blockers += $gate.snapshot.reason }

        $gate.management_ready = ($gate.management_blockers.Count -eq 0)
        if (-not $gate.management_ready) {
            foreach ($blocker in $gate.management_blockers) {
                if ($gate.entry_blockers -notcontains $blocker) {
                    $gate.entry_blockers += $blocker
                }
            }
        }
        $gate.entry_ready = ($gate.management_ready -and $gate.entry_blockers.Count -eq 0)
        # Keep the historical "ready" field as the stricter new-entry gate.
        $gate.ready = $gate.entry_ready
        $gate.blockers = @($gate.entry_blockers)
    } catch {
        $message = 'ea_status_parse_error: ' + $_.Exception.Message
        $gate.management_blockers += $message
        $gate.entry_blockers += $message
        $gate.blockers = @($gate.entry_blockers)
    }
    return $gate
}

function Write-SupervisorStatus($Payload) {
    $temp = $supervisorStatusPath + '.tmp'
    $json = $Payload | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($temp, $json, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $supervisorStatusPath -Force
}

while ($true) {
    $cycle = [ordered]@{
        schema = 'BTCIL-SUPERVISOR1'
        updated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        status = 'starting'
        snapshot_service = 'unknown'
        collector = 'unknown'
        dashboard_http = $null
        execution = 'not_started'
        gate = $null
        error = $null
    }

    try {
        $collector = Get-BitcoinProcesses '*bitcoinlab.market_stream*'
        if ($collector.Count -eq 0) {
            [void](Start-BitcoinProcess 'market_stream' @('-m','bitcoinlab.market_stream','--symbol','BTCUSDT','--venues','binance,bybit,okx','--depth','50','--db','data/market_stream.sqlite'))
            $cycle.collector = 'start_requested'
        } else {
            $cycle.collector = 'running'
        }

        $snapshotProcesses = Get-BitcoinProcesses '*bitcoinlab.snapshot_runtime*'
        if ($snapshotProcesses.Count -eq 0) {
            [void](Start-BitcoinProcess 'snapshot_service' @('-m','bitcoinlab.snapshot_runtime','--interval-seconds','45','--symbol','BTCUSDT','--interval','1m','--snapshot-path','data/live_snapshot.json','--status-path','data/live_snapshot_service_status.json','--refresh-request-path','data/snapshot_refresh.request.json'))
            $cycle.snapshot_service = 'start_requested'
        } else {
            $cycle.snapshot_service = 'running'
        }

        $health = $null
        try { $health = [int](Invoke-WebRequest -Uri 'http://127.0.0.1:8502/_stcore/health' -UseBasicParsing -TimeoutSec 4).StatusCode } catch {}
        $cycle.dashboard_http = $health
        if ($health -ne 200) {
            $streamlit = Get-BitcoinProcesses '*streamlit*run*app.py*'
            if ($streamlit.Count -eq 0) {
                [void](Start-BitcoinProcess 'streamlit' @('-m','streamlit','run','app.py','--server.address','127.0.0.1','--server.port','8502','--browser.gatherUsageStats','false'))
                $cycle.dashboard_http = 'start_requested'
            } else {
                $cycle.dashboard_http = 'process_exists_health_failed'
            }
        }

        $gate = Get-ExecutionGate
        $cycle.gate = $gate
        $execution = Get-BitcoinProcesses '*bitcoinlab.execution_loop*'
        # Start the loop when safe position management is possible. The Python
        # bridge independently blocks every new entry without valid broker
        # risk specs or when the daily-loss limit has been reached.
        if ($gate.management_ready -and $execution.Count -eq 0) {
            $previousFlag = $env:BTCIL_ENABLE_EXECUTION
            try {
                $env:BTCIL_ENABLE_EXECUTION = '1'
                [void](Start-BitcoinProcess 'execution_loop' @('-m','bitcoinlab.execution_loop','--interval-seconds',"$ExecutionIntervalSeconds",'--volume',"$VolumeCap",'--snapshot-path',$snapshotPath))
            } finally {
                if ($null -eq $previousFlag) { Remove-Item Env:BTCIL_ENABLE_EXECUTION -ErrorAction SilentlyContinue }
                else { $env:BTCIL_ENABLE_EXECUTION = $previousFlag }
            }
            $cycle.execution = 'start_requested'
        } elseif ($execution.Count -gt 0) {
            $cycle.execution = 'running'
        } else {
            $cycle.execution = 'waiting_for_position_management_readiness'
        }

        if ($gate.entry_ready) {
            $cycle.status = 'execution_authorized_and_supervised'
        } elseif ($gate.management_ready) {
            $cycle.status = 'position_management_supervised_entry_blocked'
        } else {
            $cycle.status = 'waiting_for_readiness'
        }
    } catch {
        $cycle.status = 'supervisor_error'
        $cycle.error = $_.Exception.Message
    }

    try { Write-SupervisorStatus $cycle } catch {}
    Start-Sleep -Seconds $PollSeconds
}
