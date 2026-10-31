$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Join-Path $env:RUNNER_TEMP "bitcoin-intelligence-lab-mt5"
$installDir = Join-Path $root "terminal"
$expertsDir = Join-Path $installDir "MQL5\Experts"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Path $installDir,$expertsDir,$logDir -Force | Out-Null
$report = Join-Path $logDir "bitcoin-headway-demo-report.txt"
$terminalProcess = $null
$loginConfig = $null
$runtimeConfig = $null
$rawPasswordForRuntime = $null
$login = ""
$server = "mt5.demo.trade-hw.online"

function Add-Report([string]$Line) {
    $Line | Add-Content -LiteralPath $report -Encoding utf8
}
function Mask-Text([string]$Text) {
    $value = [string]$Text
    if ($login) { $value = $value.Replace($login,"[LOGIN REDACTED]") }
    $value = $value -replace '(?i)(password|passwd)\s*[:=]\s*\S+', '$1=[REDACTED]'
    $value = $value -replace '\b\d{4,20}\b', '[NUMBER REDACTED]'
    if ($value.Length -gt 260) { $value = $value.Substring(0,260) }
    return $value
}

try {
    "Bitcoin Intelligence Lab — Headway DEMO validation" | Set-Content -LiteralPath $report -Encoding utf8
    Add-Report "UTC start: $([DateTime]::UtcNow.ToString('o'))"
    Add-Report "The real BitcoinIntelligenceLabEA will be attached to a Headway BTC demo chart. Terminal automated trading is disabled; the only test command must be rejected before OrderSend."

    # Reuse the existing GitHub Actions secret named mt5 from the previous Headway setup.
    $raw = [string]$env:MT5_CREDENTIALS
    if ([string]::IsNullOrWhiteSpace($raw)) { throw "GitHub Actions secret 'mt5' is missing." }
    $password = ""
    $obj = $null
    if ($raw.TrimStart().StartsWith("{")) {
        try { $obj = ConvertFrom-Json -InputObject $raw -ErrorAction Stop } catch { throw "Secret JSON format is invalid; values suppressed." }
    }
    if ($null -ne $obj) {
        $login = [string]$obj.login
        if (!$login) { $login = [string]$obj.account }
        $password = [string]$obj.password
        $rawPasswordForRuntime = $password
        if ($obj.server) { $server = [string]$obj.server }
    } else {
        $lines = @($raw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        $named = @{}
        foreach ($line in $lines) {
            if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$') {
                $named[$matches[1].ToLowerInvariant()] = $matches[2]
            }
        }
        if ($named.ContainsKey("login") -or $named.ContainsKey("account")) {
            $login = [string]$named["login"]
            if (!$login) { $login = [string]$named["account"] }
            $password = [string]$named["password"]
            $rawPasswordForRuntime = $password
            if ($named["server"]) { $server = [string]$named["server"] }
        } elseif ($lines.Count -ge 2) {
            $login = [string]$lines[0]
            $password = [string]$lines[1]
            $rawPasswordForRuntime = $password
            if ($lines.Count -ge 3) { $server = [string]$lines[2] }
        } else {
            throw "Secret format invalid. Expected JSON or separate login/password lines; values suppressed."
        }
    }
    if ($login -notmatch '^\d{4,20}$' -or !$password -or $login -match '[\r\n=]' -or $password -match '[\r\n]' -or $server -match '[\r\n]') {
        throw "Secret fields failed validation; values suppressed."
    }
    Write-Output "::add-mask::$login"
    Write-Output "::add-mask::$password"
    Write-Output "::add-mask::$server"
    Add-Report "Existing Headway account secret was found and parsed; credential values are suppressed."
    Add-Report "Server selected: Headway demo endpoint."

    $installer = Join-Path $root "mt5setup.exe"
    $installerUrl = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    Invoke-WebRequest -Uri $installerUrl -OutFile $installer -TimeoutSec 180
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) { throw "Official MT5 installer download failed validation." }
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    Add-Report "Installer exit code: $($install.ExitCode) (installed files are independently checked)."

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse | Select-Object -First 1
    $meta = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse | Select-Object -First 1
    if (!$terminal -or !$meta) { throw "Installed terminal64.exe or metaeditor64.exe was not found." }
    Add-Report "Terminal product version: $((Get-Item $terminal.FullName).VersionInfo.ProductVersion)"

    $source = Join-Path $PWD "Bitcoin_Intelligence_Lab\mql5\BitcoinIntelligenceLabEA.mq5"
    if (!(Test-Path $source)) { throw "BitcoinIntelligenceLabEA.mq5 is missing from repository checkout." }
    $ea = Join-Path $expertsDir "BitcoinIntelligenceLabEA.mq5"
    Copy-Item -LiteralPath $source -Destination $ea -Force
    $compileLog = Join-Path $expertsDir "BitcoinIntelligenceLabEA.log"
    $ex5 = Join-Path $expertsDir "BitcoinIntelligenceLabEA.ex5"
    Remove-Item -LiteralPath $compileLog,$ex5 -Force -ErrorAction SilentlyContinue
    $includeRoot = Join-Path $installDir "MQL5"
    $compileArg = '/compile:"' + $ea + '"'
    $includeArg = '/include:"' + $includeRoot + '"'
    Add-Report "Compiler executable: $($meta.FullName)"
    Add-Report "Source file: $ea"
    Add-Report "Include root: $includeRoot"
    $compiler = Start-Process -FilePath $meta.FullName -ArgumentList @($compileArg,$includeArg,"/log") -WorkingDirectory $installDir -PassThru -WindowStyle Hidden
    if (!$compiler.WaitForExit(90000)) {
        Stop-Process -Id $compiler.Id -Force -ErrorAction SilentlyContinue
        throw "Bitcoin EA compilation timed out."
    }
    Add-Report "MetaEditor process exit code: $($compiler.ExitCode)"
    Start-Sleep -Seconds 3
    if (!(Test-Path -LiteralPath $compileLog)) {
        $foundLog = Get-ChildItem -LiteralPath $installDir -Filter "BitcoinIntelligenceLabEA.log" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($foundLog) { Copy-Item -LiteralPath $foundLog.FullName -Destination $compileLog -Force }
    }
    if (!(Test-Path -LiteralPath $ex5)) {
        $foundEx5 = Get-ChildItem -LiteralPath $installDir -Filter "BitcoinIntelligenceLabEA.ex5" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($foundEx5) { Copy-Item -LiteralPath $foundEx5.FullName -Destination $ex5 -Force }
    }
    if (!(Test-Path -LiteralPath $compileLog) -or !(Test-Path -LiteralPath $ex5)) {
        $recent = @(Get-ChildItem -LiteralPath $installDir -Filter "BitcoinIntelligenceLabEA.*" -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 12 | ForEach-Object { $_.FullName })
        foreach ($item in $recent) { Add-Report "Compiler artifact: $item" }
        throw "MetaEditor did not create both the EA compile log and EX5 binary."
    }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    Add-Report "MetaEditor compile summary: $((Get-Content -LiteralPath $compileLog -Tail 8) -join ' | ')"
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -notmatch '(?i)0 warnings') {
        throw "Bitcoin EA compile log did not prove zero errors and zero warnings."
    }
    Add-Report "RESULT: EA_COMPILE_PASS — BitcoinIntelligenceLabEA compiled with zero errors and zero warnings."

    # Login-only config; expert automation and live trading remain disabled.
    $loginConfig = Join-Path $root "headway-demo-login.ini"
    $ini = @"
[Common]
Login=$login
Password=$password
Server=$server
ProxyEnable=0
KeepPrivate=0
NewsEnable=0
CertInstall=0

[Experts]
Enabled=0
AllowLiveTrading=0
AllowDllImport=0

[Charts]
ProfileLast=Default
MaxBars=10000
"@
    [IO.File]::WriteAllText($loginConfig,$ini,[Text.UTF8Encoding]::new($false))
    $loginForRedaction = $login
    $password = $null
    $raw = $null
    $obj = $null
    $loginStart = Get-Date
    $terminalProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable","/config:$loginConfig","/login:$loginForRedaction") -WorkingDirectory $installDir -PassThru
    Add-Report "Isolated MT5 terminal launched; waiting up to 120 seconds for a fresh Headway authorization log."
    $confirmed = $false
    $rejected = $false
    $deadline = (Get-Date).AddSeconds(120)
    $diagnostics = New-Object System.Collections.Generic.List[string]
    while ((Get-Date) -lt $deadline) {
        $logs = @(Get-ChildItem -LiteralPath $installDir -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $loginStart.AddSeconds(-3) } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 20)
        foreach ($file in $logs) {
            $body = ""
            try { $body = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction Stop } catch { continue }
            foreach ($line in ($body -split "\r?\n")) {
                $isHeadway = $line -match '(?i)(Headway-Demo|mt5\.demo\.trade-hw\.online)'
                if ($isHeadway -and $line -match '(?i)(authorized on|successfully authorized|authorization successful|login successful)' -and
                    $line -notmatch '(?i)(failed|invalid|not authorized|authorization error)') { $confirmed=$true; break }
                if ($isHeadway -and $line -match '(?i)(authorization failed|failed to authorize|invalid account|invalid password|authorization rejected)') { $rejected=$true }
                if ($diagnostics.Count -lt 8 -and $line -match '(?i)(Headway|authoriz|login|connect|network|server|failed|error|timeout|socket|resolve)') {
                    $safe = Mask-Text $line
                    if (!$diagnostics.Contains($safe)) { [void]$diagnostics.Add($safe) }
                }
            }
            if ($confirmed -or $rejected) { break }
        }
        if ($confirmed -or $rejected) { break }
        Start-Sleep -Seconds 3
    }
    if ($confirmed) {
        Add-Report "RESULT: HEADWAY_AUTH_PASS — fresh MT5 logs confirmed authorization to the Headway demo server."
    } elseif ($rejected) {
        foreach ($line in $diagnostics) { Add-Report "Sanitized diagnostic: $line" }
        throw "Headway rejected demo authorization; credentials were not logged."
    } else {
        foreach ($line in $diagnostics) { Add-Report "Sanitized diagnostic: $line" }
        throw "Headway demo authorization was not confirmed within 120 seconds."
    }
    Add-Report "RESULT: HEADWAY_AUTH_PASS — fresh MT5 logs confirmed authorization to the Headway demo server."

    # Connect through the official MetaTrader5 Python package to discover the exact broker BTC symbol.
    $probeScript = Join-Path $PWD "Bitcoin_Intelligence_Lab\\scripts\\mt5_runtime_probe.py"
    if (!(Test-Path -LiteralPath $probeScript)) { throw "Read-only MT5 runtime probe is missing." }
    $env:BTCIL_MT5_TERMINAL = $terminal.FullName
    $env:BTCIL_MT5_LOGIN = $loginForRedaction
    $env:BTCIL_MT5_PASSWORD = $rawPasswordForRuntime
    $env:BTCIL_MT5_SERVER = $server
    try {
        $probeOutput = @(& python $probeScript 2>&1)
        $probeExit = $LASTEXITCODE
    } finally {
        Remove-Item Env:BTCIL_MT5_TERMINAL,Env:BTCIL_MT5_LOGIN,Env:BTCIL_MT5_PASSWORD,Env:BTCIL_MT5_SERVER -ErrorAction SilentlyContinue
    }
    if ($probeExit -ne 0) {
        foreach ($line in $probeOutput) { Add-Report ("MT5 runtime probe: " + (Mask-Text ([string]$line))) }
        throw "Read-only MetaTrader5 runtime probe failed."
    }
    try { $probe = ($probeOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "MetaTrader5 runtime probe did not return valid JSON." }
    if ($probe.status -ne "ok" -or !$probe.symbol -or !$probe.common_data_path) {
        throw "MetaTrader5 runtime probe returned incomplete account/symbol metadata."
    }
    $btcSymbol = [string]$probe.symbol
    if ($btcSymbol -notmatch '^[A-Za-z0-9._-]{3,32}}
catch {
    Add-Report "RESULT: FAIL — $($_.Exception.Message)"
    Get-Content -LiteralPath $report
    throw
}
finally {
    if ($terminalProcess -and !$terminalProcess.HasExited) {
        Stop-Process -Id $terminalProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($runtimeConfig -and (Test-Path -LiteralPath $runtimeConfig)) {
        Remove-Item -LiteralPath $runtimeConfig -Force -ErrorAction SilentlyContinue
    }
    if ($runtimeConfig -and (Test-Path -LiteralPath $runtimeConfig)) {
        Remove-Item -LiteralPath $runtimeConfig -Force -ErrorAction SilentlyContinue
    }
    if ($loginConfig -and (Test-Path -LiteralPath $loginConfig)) {
        Remove-Item -LiteralPath $loginConfig -Force -ErrorAction SilentlyContinue
    }
}
 -or $btcSymbol -notmatch '(?i)BTC') {
        throw "Broker BTC symbol failed safe-name validation."
    }
    if ([bool]$probe.terminal_trade_allowed) {
        throw "Safety gate failed: terminal automated trading must remain disabled."
    }
    Add-Report "Read-only terminal probe PASS: connected Headway DEMO; BTC symbol selected: $btcSymbol; terminal trade_allowed=false."
    Add-Report "BTC contract: digits=$($probe.digits), point=$($probe.point), volume_min=$($probe.volume_min), volume_step=$($probe.volume_step), trade_mode=$($probe.trade_mode)."

    # Stop the login-only instance before restarting with the real EA attached.
    if ($terminalProcess -and !$terminalProcess.HasExited) {
        Stop-Process -Id $terminalProcess.Id -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $terminalProcess.Id -Timeout 20 -ErrorAction SilentlyContinue
    }
    $terminalProcess = $null
    Start-Sleep -Seconds 2

    $commonFiles = Join-Path ([string]$probe.common_data_path) "Files"
    $eaCommonFolder = Join-Path $commonFiles "BitcoinIntelligenceLab"
    if (Test-Path -LiteralPath $eaCommonFolder) {
        Remove-Item -LiteralPath $eaCommonFolder -Recurse -Force
    }
    New-Item -ItemType Directory -Path $eaCommonFolder -Force | Out-Null

    # Start the actual EA on the broker's BTC chart. EA execution is enabled,
    # but AllowLiveTrading=0 is a terminal-wide hard block checked inside the EA.
    $runtimeConfig = Join-Path $root "headway-demo-ea-runtime.ini"
    $runtimeIni = @"
[Common]
Login=$loginForRedaction
Password=$rawPasswordForRuntime
Server=$server
ProxyEnable=0
KeepPrivate=0
NewsEnable=0
CertInstall=0

[Experts]
Enabled=1
AllowLiveTrading=0
AllowDllImport=0
Account=0
Profile=0

[Charts]
ProfileLast=Default
MaxBars=10000

[StartUp]
Expert=BitcoinIntelligenceLabEA
Symbol=$btcSymbol
Period=M1
"@
    [IO.File]::WriteAllText($runtimeConfig,$runtimeIni,[Text.UTF8Encoding]::new($false))
    $rawPasswordForRuntime = $null
    $runtimeStart = Get-Date
    $terminalProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable","/config:$runtimeConfig") -WorkingDirectory $installDir -PassThru
    Add-Report "Runtime integration: launched terminal with BitcoinIntelligenceLabEA on $btcSymbol M1 and AllowLiveTrading=0."

    $statusPath = Join-Path $eaCommonFolder "ea_status.tsv"
    $positionsPath = Join-Path $eaCommonFolder "positions.tsv"
    $statusFields = @()
    $statusReady = $false
    $runtimeDeadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $runtimeDeadline) {
        if (Test-Path -LiteralPath $statusPath) {
            try {
                $statusRaw = Get-Content -LiteralPath $statusPath -Raw -ErrorAction Stop
                $statusFields = @($statusRaw.Trim() -split "\\|")
                if ($statusFields.Count -ge 14 -and $statusFields[0] -eq "BTCIL1" -and
                    $statusFields[1] -eq $btcSymbol -and $statusFields[4] -eq "CONNECTED" -and
                    $statusFields[11] -eq "TRADE_BLOCKED" -and
                    $statusFields[12] -match '(?i)(Headway-Demo|trade-hw.online)' -and
                    $statusFields[13].Trim() -eq "0") {
                    $statusReady = $true
                    break
                }
            } catch {}
        }
        if ($terminalProcess.HasExited) { throw "MT5 terminal exited before the Bitcoin EA published its status file." }
        Start-Sleep -Seconds 2
    }
    if (!$statusReady) {
        Add-Report "EA status file expected at: $statusPath"
        if (Test-Path -LiteralPath $statusPath) {
            Add-Report ("EA status observed: " + (Mask-Text (Get-Content -LiteralPath $statusPath -Raw)))
        }
        throw "BitcoinIntelligenceLabEA did not publish fresh connected Headway DEMO status with trading blocked."
    }
    Add-Report "RESULT: EA_RUNTIME_PASS — actual EA attached to $btcSymbol M1; status heartbeat reports CONNECTED, Headway DEMO, and TRADE_BLOCKED."

    # Submit a deliberately valid OPEN envelope. The EA must consume and reject it at
    # the terminal-permission gate before any OrderSend call can be reached.
    $nowUtc = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $commandId = "BTCIL-CI-GATE-$nowUtc"
    $expiresUtc = $nowUtc + 120
    $volume = [Math]::Max(0.01,[double]$probe.volume_min)
    $bid = [double]$probe.bid
    $ask = [double]$probe.ask
    if ($bid -le 0 -or $ask -le 0 -or $ask -lt $bid) {
        $bid = 50000.0
        $ask = 50001.0
    }
    $stopLoss = [Math]::Round([Math]::Max(1.0,$bid-1000.0),8)
    $takeProfit = [Math]::Round($ask+1000.0,8)
    $command = "BTCIL1|$commandId|$nowUtc|$expiresUtc|BTC|OPEN|BUY|$($volume.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture))|$($stopLoss.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture))|$($takeProfit.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture))|0"
    $commandPath = Join-Path $eaCommonFolder "trade_command.txt"
    [IO.File]::WriteAllText($commandPath,$command,[Text.Encoding]::ASCII)

    $ackPath = Join-Path $eaCommonFolder "trade_command_ack.txt"
    $ack = $null
    $ackDeadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $ackDeadline) {
        if (Test-Path -LiteralPath $ackPath) {
            try {
                $candidate = Get-Content -LiteralPath $ackPath -Raw | ConvertFrom-Json -ErrorAction Stop
                if ($candidate.id -eq $commandId) { $ack = $candidate; break }
            } catch {}
        }
        if ($terminalProcess.HasExited) { throw "MT5 terminal exited while waiting for the EA command acknowledgment." }
        Start-Sleep -Milliseconds 500
    }
    if ($null -eq $ack) { throw "Bitcoin EA did not acknowledge the guarded test command within 30 seconds." }
    if ($ack.status -ne "REJECTED" -or $ack.action -ne "OPEN" -or
        ([string]$ack.detail) -notmatch 'BLOCKED: Headway DEMO/terminal permission gate') {
        throw "EA did not reject the test OPEN command at the expected terminal trading-permission gate."
    }
    Add-Report "RESULT: COMMAND_PIPELINE_PASS — EA consumed the BTC OPEN test envelope and returned REJECTED at the terminal-permission gate."

    if (!(Test-Path -LiteralPath $positionsPath)) { throw "EA did not publish positions.tsv." }
    $positionLines = @(Get-Content -LiteralPath $positionsPath)
    if ($positionLines.Count -gt 1) {
        throw "Safety check failed: the isolated test EA reported one or more owned positions."
    }
    $finalStatus = Get-Content -LiteralPath $statusPath -Raw
    $finalFields = @($finalStatus.Trim() -split "\\|")
    if ($finalFields.Count -lt 14 -or $finalFields[11] -ne "TRADE_BLOCKED") {
        throw "Safety check failed: terminal trading permission was not blocked in the final EA heartbeat."
    }
    Add-Report "SAFETY PASS — AllowLiveTrading=0; test command rejected; no order was sent; no EA-owned position was created."
    Add-Report "Runtime elapsed seconds: $([Math]::Round(((Get-Date)-$runtimeStart).TotalSeconds,1))"
    Add-Report "RESULT: HEADWAY_BTC_EA_INTEGRATION_PASS"
    Get-Content -LiteralPath $report
}
catch {
    Add-Report "RESULT: FAIL — $($_.Exception.Message)"
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
}
