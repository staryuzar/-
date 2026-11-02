#requires -Version 5.1
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$root = Join-Path $env:RUNNER_TEMP 'mirsad-mt5-observer-check'
$installDir = Join-Path $root 'terminal'
$evidence = Join-Path $root 'evidence'
New-Item -ItemType Directory -Path $installDir, $evidence -Force | Out-Null
$report = Join-Path $evidence 'mirsad-observer-report.txt'
$installer = Join-Path $root 'mt5setup.exe'
$loginConfig = $null
$terminalProcess = $null
$credentialRaw = [string]$env:MT5_CREDENTIALS
$accountPassword = $null

function Add-Report([string]$Line) {
    $Line | Add-Content -LiteralPath $report -Encoding utf8
}

function Get-CommonObserverDirectory {
    $candidates = @(
        (Join-Path $installDir 'Common\Files\MirsadBTC\observer'),
        (Join-Path $installDir 'Terminal\Common\Files\MirsadBTC\observer'),
        (Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC\observer'),
        (Join-Path $env:LOCALAPPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC\observer')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }

    $roots = @(
        (Join-Path $installDir 'Common\Files'),
        (Join-Path $installDir 'Terminal\Common\Files'),
        (Join-Path $env:APPDATA 'MetaQuotes\Terminal'),
        (Join-Path $env:LOCALAPPDATA 'MetaQuotes\Terminal')
    ) | Where-Object { Test-Path -LiteralPath $_ }

    foreach ($searchRoot in $roots) {
        $found = Get-ChildItem -LiteralPath $searchRoot -Filter 'capture_*.json' -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Directory.Name -eq 'observer' -and $_.Directory.Parent.Name -eq 'MirsadBTC' } |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($found) { return $found.Directory.FullName }
    }
    return $null
}

try {
    'Mirsad Chart Observer — isolated MT5 demo connection test' | Set-Content -LiteralPath $report -Encoding utf8
    Add-Report ("UTC start: {0}" -f [DateTime]::UtcNow.ToString('o'))
    Add-Report 'Mode: read-only Observer EA only. No execution EA, no trading commands, no MIR1 writes.'

    if ([string]::IsNullOrWhiteSpace($credentialRaw)) {
        throw "Repository Actions secret 'mt5' is unavailable."
    }

    $login = ''
    $accountPassword = ''
    $server = 'mt5.demo.trade-hw.online'
    $obj = $null
    if ($credentialRaw.TrimStart().StartsWith('{')) {
        try { $obj = ConvertFrom-Json -InputObject $credentialRaw -ErrorAction Stop }
        catch { throw 'MT5 secret JSON is invalid.' }
    }

    if ($null -ne $obj) {
        $login = [string]$obj.login
        if ([string]::IsNullOrWhiteSpace($login)) { $login = [string]$obj.account }
        $accountPassword = [string]$obj.password
        if (-not [string]::IsNullOrWhiteSpace([string]$obj.server)) { $server = [string]$obj.server }
    }
    else {
        $lines = @($credentialRaw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
        $fields = @{}
        foreach ($line in $lines) {
            if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$') {
                $fields[$matches[1].ToLowerInvariant()] = $matches[2]
            }
        }
        if ($fields.ContainsKey('login') -or $fields.ContainsKey('account') -or $fields.ContainsKey('password')) {
            $login = [string]$fields['login']
            if ([string]::IsNullOrWhiteSpace($login)) { $login = [string]$fields['account'] }
            $accountPassword = [string]$fields['password']
            if (-not [string]::IsNullOrWhiteSpace([string]$fields['server'])) { $server = [string]$fields['server'] }
        }
        elseif ($lines.Count -ge 2) {
            $login = [string]$lines[0]
            $accountPassword = [string]$lines[1]
            if ($lines.Count -ge 3) { $server = [string]$lines[2] }
        }
        else {
            throw 'MT5 secret format is not recognized.'
        }
    }

    if ($login -notmatch '^\d{4,20}$' -or [string]::IsNullOrWhiteSpace($accountPassword)) {
        throw 'MT5 demo credentials are incomplete.'
    }
    if ($server -notmatch '(?i)(headway-demo|mt5\.demo\.trade-hw\.online)' -or $server -match '(?i)(live|real)') {
        throw 'Safety stop: only the configured Headway demo server is accepted.'
    }
    Write-Output "::add-mask::$login"
    Write-Output "::add-mask::$accountPassword"
    Write-Output "::add-mask::$server"
    Add-Report 'Demo server accepted. Login values and password are masked and excluded from evidence.'

    $download = 'https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe'
    Invoke-WebRequest -Uri $download -OutFile $installer -TimeoutSec 240
    if (!(Test-Path -LiteralPath $installer) -or (Get-Item -LiteralPath $installer).Length -lt 100000) {
        throw 'Official MT5 installer download failed.'
    }

    $installArg = '/path:"' + $installDir + '"'
    $install = Start-Process -FilePath $installer -ArgumentList @('/auto', $installArg) -PassThru -Wait
    Add-Report ("MT5 installer process exit code: {0}" -f $install.ExitCode)

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter 'terminal64.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (!$terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter 'terminal.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    $editor = Get-ChildItem -LiteralPath $installDir -Filter 'metaeditor64.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (!$terminal -or !$editor) { throw 'MT5 terminal or MetaEditor was not found after installer verification.' }
    Add-Report ("MetaTrader version: {0}" -f $terminal.VersionInfo.ProductVersion)

    $source = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\mt5\Mirsad_ChartObserver.mq5'
    if (!(Test-Path -LiteralPath $source)) { throw 'Mirsad Chart Observer source is missing.' }
    $sourceText = Get-Content -LiteralPath $source -Raw
    if ($sourceText -match '(?i)\b(OrderSend|OrderSendAsync|CTrade|PositionOpen|PositionClose)\s*\(') {
        throw 'Safety stop: read-only Observer source contains a trading API.'
    }
    if ($sourceText -match '(?im)^\s*#import\b') {
        throw 'Safety stop: Observer must not import external DLL functions.'
    }

    $expertsDir = Join-Path $installDir 'MQL5\Experts'
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir 'Mirsad_ChartObserver.mq5'
    $eaBinary = Join-Path $expertsDir 'Mirsad_ChartObserver.ex5'
    $compileLog = Join-Path $expertsDir 'Mirsad_ChartObserver.log'
    Copy-Item -LiteralPath $source -Destination $eaSource -Force

    $compiler = Start-Process -FilePath $editor.FullName -ArgumentList ('/compile:"' + $eaSource + '" /log') -WorkingDirectory $installDir -PassThru
    if (!$compiler.WaitForExit(90000)) {
        Stop-Process -Id $compiler.Id -Force -ErrorAction SilentlyContinue
        throw 'MetaEditor Observer compilation timed out.'
    }
    Start-Sleep -Seconds 2
    if (!(Test-Path -LiteralPath $compileLog) -or !(Test-Path -LiteralPath $eaBinary)) {
        throw 'MetaEditor did not create the Observer compile log and EX5 binary.'
    }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    $compileText | Set-Content -LiteralPath (Join-Path $evidence 'Mirsad_ChartObserver_compile.log') -Encoding utf8
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') {
        throw 'MetaEditor did not report zero Observer compile errors.'
    }
    if ($compileText -notmatch '(?i)0 warnings' -or $compileText -match '(?i)[1-9][0-9]* warnings') {
        throw 'MetaEditor did not report zero Observer compile warnings.'
    }
    Copy-Item -LiteralPath $eaBinary -Destination (Join-Path $evidence 'Mirsad_ChartObserver.ex5') -Force
    Add-Report ("PASS — Observer compiled with zero errors and zero warnings; EX5 bytes={0}." -f (Get-Item -LiteralPath $eaBinary).Length)

    $loginConfig = Join-Path $root 'mt5-observer-demo.ini'
    $ini = @"
[Common]
Login=$login
Password=$accountPassword
Server=$server
ProxyEnable=0
KeepPrivate=0
NewsEnable=0
CertInstall=0

[Experts]
Enabled=1
AllowLiveTrading=0
AllowDllImport=0

[Charts]
ProfileLast=Default
MaxBars=50000

[StartUp]
Expert=Mirsad_ChartObserver
Symbol=BTC
Period=M1
"@
    [IO.File]::WriteAllText($loginConfig, $ini, [Text.UTF8Encoding]::new($false))
    $accountPassword = $null
    $credentialRaw = $null
    $obj = $null

    $terminalProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @('/portable', "/config:$loginConfig", "/login:$login") -WorkingDirectory $installDir -PassThru
    Add-Report 'MT5 terminal launched with the read-only Observer on BTC,M1. Automated trading permission is disabled.'
    $loginStarted = Get-Date
    $authorized = $false
    $observerDir = $null
    $manifestFile = $null
    $deadline = (Get-Date).AddSeconds(180)

    while ((Get-Date) -lt $deadline) {
        $logDir = Join-Path $installDir 'Logs'
        if (Test-Path -LiteralPath $logDir) {
            $logs = Get-ChildItem -LiteralPath $logDir -Filter '*.log' -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 12
            foreach ($log in $logs) {
                if ($log.LastWriteTime -lt $loginStarted.AddSeconds(-3)) { continue }
                $txt = ''
                try { $txt = Get-Content -LiteralPath $log.FullName -Raw } catch { continue }
                foreach ($line in ($txt -split "\r?\n")) {
                    if ($line -match '(?i)(Headway-Demo|mt5\.demo\.trade-hw\.online)' -and
                        $line -match '(?i)(authorized on|successfully authorized|authorization successful|login successful)' -and
                        $line -notmatch '(?i)(failed|invalid|not authorized|authorization error)') {
                        $authorized = $true
                    }
                }
            }
        }

        $observerDir = Get-CommonObserverDirectory
        if ($observerDir) {
            $manifestFile = Get-ChildItem -LiteralPath $observerDir -Filter 'capture_*.json' -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        }

        if ($authorized -and $manifestFile) { break }
        if ($terminalProcess.HasExited) {
            Add-Report 'Terminal exited before demo authorization and Observer capture were both confirmed.'
            break
        }
        Start-Sleep -Seconds 3
    }

    if (!$authorized) { throw 'MT5 authorization on the Headway demo server was not confirmed.' }
    Add-Report 'PASS — MT5 authorized on the configured Headway demo server.'
    if (!$manifestFile -or !$observerDir) {
        throw 'MT5 started, but no Observer capture manifest appeared within 180 seconds.'
    }

    $manifest = Get-Content -LiteralPath $manifestFile.FullName -Raw | ConvertFrom-Json -ErrorAction Stop
    if ($manifest.schema -ne 'MIR-CHART-OBSERVATION-1') { throw 'Observer manifest schema is not MIR-CHART-OBSERVATION-1.' }
    if ([string]$manifest.chart.symbol -ne 'BTC' -or [string]$manifest.chart.timeframe -ne 'M1') {
        throw 'Observer captured a different symbol or timeframe than the requested BTC,M1 chart.'
    }
    if (@($manifest.bars).Count -lt 30 -or [int]$manifest.bars_copied -ne @($manifest.bars).Count) {
        throw 'Observer OHLC bar count is incomplete or inconsistent.'
    }
    if ([bool]$manifest.bars[-1].is_closed) { throw 'Newest MT5 bar must be marked as forming.' }
    if ($manifest.bars[0].time_server_ms -ge $manifest.bars[-1].time_server_ms) {
        throw 'Observer bars are not in oldest-to-newest order.'
    }

    $imagePath = Join-Path (Join-Path $observerDir 'images') ([string]$manifest.image_file)
    if (!(Test-Path -LiteralPath $imagePath)) { throw 'Observer manifest exists but its PNG image is missing.' }
    $imageBytes = [IO.File]::ReadAllBytes($imagePath)
    if ($imageBytes.Length -ne [int64]$manifest.image_size_bytes) { throw 'Observer PNG size does not match its manifest.' }
    if ($imageBytes.Length -lt 8 -or $imageBytes[0] -ne 137 -or $imageBytes[1] -ne 80 -or
        $imageBytes[2] -ne 78 -or $imageBytes[3] -ne 71) {
        throw 'Observer image does not have a PNG signature.'
    }
    $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    if (($nowMs - [int64]$manifest.capture_at_utc_ms) -gt 180000) {
        throw 'Observer capture is stale.'
    }
    $skew = [int64]$manifest.capture_at_utc_ms - [int64]$manifest.rates_snapshot_at_utc_ms
    if ($skew -lt 0 -or $skew -gt 2000) { throw 'Image and OHLC snapshot are not sufficiently time-aligned.' }

    Copy-Item -LiteralPath $manifestFile.FullName -Destination (Join-Path $evidence 'observer-capture.json') -Force
    Copy-Item -LiteralPath $imagePath -Destination (Join-Path $evidence 'observer-capture.png') -Force
    $safe = [ordered]@{
        schema = $manifest.schema
        capture_id = $manifest.capture_id
        capture_at_utc_ms = $manifest.capture_at_utc_ms
        rates_snapshot_at_utc_ms = $manifest.rates_snapshot_at_utc_ms
        capture_data_skew_ms = $skew
        symbol = $manifest.chart.symbol
        timeframe = $manifest.chart.timeframe
        image_width_px = $manifest.image_width_px
        image_height_px = $manifest.image_height_px
        image_size_bytes = $imageBytes.Length
        bars_copied = @($manifest.bars).Count
        newest_bar_is_forming = (-not [bool]$manifest.bars[-1].is_closed)
        broker_server_time_basis = $manifest.bars_time_basis
        read_only = $true
        trading_permission_enabled = $false
    }
    $safe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'observer-live-capture-summary.json') -Encoding utf8
    Add-Report ("PASS — Observer capture received from live MT5 Demo: {0} {1}." -f $manifest.chart.symbol, $manifest.chart.timeframe)
    Add-Report ("PASS — PNG signature and byte size verified: {0} bytes." -f $imageBytes.Length)
    Add-Report ("PASS — OHLC bars verified: {0}; newest bar is forming." -f @($manifest.bars).Count)
    Add-Report ("PASS — Image/OHLC request skew: {0} ms." -f $skew)
    Add-Report 'Safety — Observer only; no execution EA attached; automated trading permission disabled; no MIR1 command created.'
    Add-Report ("UTC finish: {0}" -f [DateTime]::UtcNow.ToString('o'))
    Get-Content -LiteralPath $report
}
catch {
    Add-Report ("FAIL — {0}" -f $_.Exception.Message)
    Add-Report ("UTC finish: {0}" -f [DateTime]::UtcNow.ToString('o'))
    Get-Content -LiteralPath $report
    throw
}
finally {
    if ($terminalProcess -and !$terminalProcess.HasExited) {
        Stop-Process -Id $terminalProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($loginConfig -and (Test-Path -LiteralPath $loginConfig)) {
        Remove-Item -LiteralPath $loginConfig -Force -ErrorAction SilentlyContinue
    }
    $accountPassword = $null
    $credentialRaw = $null
}
