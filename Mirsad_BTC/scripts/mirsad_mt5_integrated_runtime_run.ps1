#requires -Version 5.1
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$root = Join-Path $env:RUNNER_TEMP 'mirsad-mt5-integrated-runtime'
$readyFile = Join-Path $root 'observer-ready.json'
$stopFile = Join-Path $root 'observer-stop.signal'
$observerStdout = Join-Path $root 'observer-stdout.log'
$observerStderr = Join-Path $root 'observer-stderr.log'
$executionLog = Join-Path $root 'execution-runtime.log'
New-Item -ItemType Directory -Path $root -Force | Out-Null

$observerProcess = $null
$observerCommonFiles = $null
$success = $false

function Write-RunLog([string]$Message) {
    Write-Output ("[{0}] {1}" -f [DateTime]::UtcNow.ToString('o'), $Message)
}

function Request-ObserverStop {
    if (!$observerProcess) { return }
    $observerProcess.Refresh()
    if (!$observerProcess.HasExited) {
        New-Item -ItemType File -Path $stopFile -Force | Out-Null
        $stopDeadline = [DateTime]::UtcNow.AddSeconds(120)
        do {
            Start-Sleep -Seconds 2
            $observerProcess.Refresh()
        } while (!$observerProcess.HasExited -and [DateTime]::UtcNow -lt $stopDeadline)
    }
}

try {
    Remove-Item -LiteralPath $readyFile, $stopFile, $observerStdout, $observerStderr, $executionLog -Force -ErrorAction SilentlyContinue

    $observerScript = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\mirsad_mt5_direct_feed_run.ps1'
    $executionScript = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\mirsad_mt5_execution_run.ps1'
    if (!(Test-Path -LiteralPath $observerScript)) { throw 'Native OHLC Observer runner is missing.' }
    if (!(Test-Path -LiteralPath $executionScript)) { throw 'MIR1 ExecutionBridge runner is missing.' }

    $env:MIRSAD_KEEP_OBSERVER_TERMINAL = 'true'
    $env:MIRSAD_OBSERVER_READY_FILE = $readyFile
    $env:MIRSAD_OBSERVER_STOP_FILE = $stopFile

    Write-RunLog 'Starting the read-only native MT5 Observer; it will keep its terminal alive after publishing the shared feeds.'
    $observerProcess = Start-Process -FilePath 'pwsh.exe' -ArgumentList @(
        '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $observerScript
    ) -PassThru -RedirectStandardOutput $observerStdout -RedirectStandardError $observerStderr

    $readyDeadline = [DateTime]::UtcNow.AddMinutes(10)
    while ([DateTime]::UtcNow -lt $readyDeadline -and !(Test-Path -LiteralPath $readyFile)) {
        $observerProcess.Refresh()
        if ($observerProcess.HasExited) {
            throw ("Read-only Observer exited before ready signal (exit {0})." -f $observerProcess.ExitCode)
        }
        Start-Sleep -Seconds 3
    }
    if (!(Test-Path -LiteralPath $readyFile)) {
        throw 'Native Observer did not publish its ready signal within ten minutes.'
    }

    $ready = Get-Content -LiteralPath $readyFile -Raw | ConvertFrom-Json -ErrorAction Stop
    if ($ready.status -ne 'READY' -or [string]::IsNullOrWhiteSpace([string]$ready.common_files_root)) {
        throw ("Native Observer did not become ready: {0}" -f ($ready | ConvertTo-Json -Compress))
    }
    $observerCommonFiles = [IO.Path]::GetFullPath([string]$ready.common_files_root)
    foreach ($relative in @(
        'MirsadBTC\market.json',
        'MirsadBTC\observer\candles.json',
        'MirsadBTC\observer\indicators.json'
    )) {
        if (!(Test-Path -LiteralPath (Join-Path $observerCommonFiles $relative))) {
            throw ("Observer ready signal was published before feed {0} existed." -f $relative)
        }
    }
    Write-RunLog ("Observer ready. Shared Common Files root: {0}" -f $observerCommonFiles)

    $env:MIRSAD_EXPECTED_COMMON_FILES = $observerCommonFiles
    $env:MIRSAD_RUN_LIVE_RUNTIME_CYCLE = '1'
    $env:MIRSAD_RUN_BROKER_ACCEPTANCE = '0'
    $env:MIRSAD_ENABLE_ORDER_PUBLISH = '1'

    Write-RunLog 'Starting ExecutionBridge in a separate MT5 terminal, linked to the Observer Common Files directory.'
    $executionOutput = & $executionScript 2>&1
    $executionOutput | ForEach-Object { Write-Output $_ }
    $executionOutput | Set-Content -LiteralPath $executionLog -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        throw ("MIR1 ExecutionBridge runner returned exit code {0}." -f $LASTEXITCODE)
    }

    $integrationReport = Join-Path $env:RUNNER_TEMP 'mirsad-mt5-execution-check\evidence\mirsad-live-runtime-integration.json'
    if (!(Test-Path -LiteralPath $integrationReport)) {
        throw 'Integrated runtime checker did not write its evidence report.'
    }
    $summary = Get-Content -LiteralPath $integrationReport -Raw | ConvertFrom-Json -ErrorAction Stop
    if ($summary.schema -ne 'MIRSAD-LIVE-RUNTIME-INTEGRATION-1' -or $summary.status -ne 'PASS') {
        throw 'Five-engine shared-feed runtime integration did not report PASS.'
    }
    Write-RunLog ("PASS — one live runtime cycle completed: Engine1={0}; Engine2={1}; Engine3={2}; Engine4={3}; Engine5={4}; action={5}; validated MIR1 envelopes={6}." -f $summary.engines.engine1.status, $summary.engines.engine2.status, $summary.engines.engine3.calculated_status, $summary.engines.engine4.status, $summary.engines.engine5.status, $summary.engines.engine4.action, @($summary.validated_mir1_envelopes).Count)

    Request-ObserverStop
    $observerProcess.Refresh()
    if (!$observerProcess.HasExited) {
        throw 'Read-only Observer host did not stop after the integrated runtime was complete.'
    }
    if ($observerProcess.ExitCode -ne 0) {
        throw ("Read-only Observer host exited with code {0} during cleanup." -f $observerProcess.ExitCode)
    }
    Write-RunLog 'PASS — both MT5 terminals completed; no broker acceptance order was sent by this integration harness.'
    $success = $true
}
catch {
    Write-RunLog ("FAIL — {0}" -f $_.Exception.Message)
    if (Test-Path -LiteralPath $observerStdout) {
        Write-Output '--- Observer stdout ---'
        Get-Content -LiteralPath $observerStdout -Tail 120
    }
    if (Test-Path -LiteralPath $observerStderr) {
        Write-Output '--- Observer stderr ---'
        Get-Content -LiteralPath $observerStderr -Tail 120
    }
    throw
}
finally {
    if (!$success) {
        try { Request-ObserverStop } catch { Write-RunLog ("Observer cleanup warning: {0}" -f $_.Exception.Message) }
    }
    if ($observerProcess) {
        $observerProcess.Refresh()
        if (!$observerProcess.HasExited) {
            Write-RunLog 'Observer did not stop on signal within two minutes; terminating its PowerShell host.'
            Stop-Process -Id $observerProcess.Id -Force -ErrorAction SilentlyContinue
        }
        elseif (!$success -and $observerProcess.ExitCode -ne 0) {
            Write-RunLog ("Observer exited with code {0} while reporting failure." -f $observerProcess.ExitCode)
        }
    }
    Remove-Item Env:MIRSAD_KEEP_OBSERVER_TERMINAL -ErrorAction SilentlyContinue
    Remove-Item Env:MIRSAD_OBSERVER_READY_FILE -ErrorAction SilentlyContinue
    Remove-Item Env:MIRSAD_OBSERVER_STOP_FILE -ErrorAction SilentlyContinue
    Remove-Item Env:MIRSAD_EXPECTED_COMMON_FILES -ErrorAction SilentlyContinue
    Remove-Item Env:MIRSAD_RUN_LIVE_RUNTIME_CYCLE -ErrorAction SilentlyContinue
    Remove-Item Env:MIRSAD_RUN_BROKER_ACCEPTANCE -ErrorAction SilentlyContinue
    Remove-Item Env:MIRSAD_ENABLE_ORDER_PUBLISH -ErrorAction SilentlyContinue
    if (!$success) {
        Write-RunLog 'Integrated MT5 run did not complete; broker acceptance was explicitly disabled.'
    }
}
