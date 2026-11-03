#requires -Version 5.1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$root = Join-Path $env:RUNNER_TEMP 'mirsad-mt5-demo-check'
$installDir = Join-Path $root 'terminal'
$logDir = Join-Path $root 'evidence'
New-Item -ItemType Directory -Path $installDir, $logDir -Force | Out-Null
$report = Join-Path $logDir 'mirsad-mt5-report.txt'
$installer = Join-Path $root 'mt5setup.exe'
$loginConfig = $null
$terminalProcess = $null
$accountPassword = $null
$credentialRaw = [string]$env:MT5_CREDENTIALS

function Add-Report([string]$Line) {
    $Line | Add-Content -LiteralPath $report -Encoding utf8
}

try {
    'Mirsad BTC — MetaTrader 5 demo validation' | Set-Content -LiteralPath $report -Encoding utf8
    Add-Report ("UTC start: {0}" -f [DateTime]::UtcNow.ToString('o'))
    Add-Report 'Purpose: compile the real read-only Mirsad EA and verify demo-server authorization.'
    Add-Report 'Safety: no EA is attached, automated trading is disabled, and no order API is called.'

    if ([string]::IsNullOrWhiteSpace($credentialRaw)) {
        throw "BLOCKED: repository Actions secret 'mt5' is not available to this workflow."
    }

    $accountLogin = ''
    $accountPassword = ''
    $accountServer = 'mt5.demo.trade-hw.online'
    $credentialObject = $null
    if ($credentialRaw.TrimStart().StartsWith('{')) {
        try { $credentialObject = ConvertFrom-Json -InputObject $credentialRaw -ErrorAction Stop } catch { throw 'The stored MT5 credential secret is not valid JSON.' }
    }
    if ($null -ne $credentialObject) {
        $accountLogin = [string]$credentialObject.login
        if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$credentialObject.account }
        $accountPassword = [string]$credentialObject.password
        if (-not [string]::IsNullOrWhiteSpace([string]$credentialObject.server)) { $accountServer = [string]$credentialObject.server }
    } else {
        $credentialLines = @($credentialRaw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
        $namedFields = @{}
        foreach ($line in $credentialLines) {
            if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$') {
                $namedFields[$matches[1].ToLowerInvariant()] = $matches[2]
            }
        }
        if ($namedFields.ContainsKey('login') -or $namedFields.ContainsKey('account') -or $namedFields.ContainsKey('password')) {
            $accountLogin = [string]$namedFields['login']
            if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$namedFields['account'] }
            $accountPassword = [string]$namedFields['password']
            if (-not [string]::IsNullOrWhiteSpace([string]$namedFields['server'])) { $accountServer = [string]$namedFields['server'] }
        } elseif ($credentialLines.Count -ge 2) {
            $accountLogin = [string]$credentialLines[0]
            $accountPassword = [string]$credentialLines[1]
            if ($credentialLines.Count -ge 3) { $accountServer = [string]$credentialLines[2] }
        } else {
            throw "Invalid format for repository Actions secret 'mt5'."
        }
    }

    if ($accountLogin -notmatch '^\d{4,20}$' -or [string]::IsNullOrWhiteSpace($accountPassword)) {
        throw 'Stored demo-account credential format is invalid; values were not logged.'
    }
    if ($accountServer -notmatch '(?i)(headway-demo|mt5\.demo\.trade-hw\.online)' -or $accountServer -match '(?i)(live|real)') {
        throw 'Safety stop: this workflow accepts only the configured Headway demo server.'
    }
    Write-Output "::add-mask::$accountLogin"
    Write-Output "::add-mask::$accountPassword"
    Write-Output "::add-mask::$accountServer"
    Add-Report 'Repository MT5 secret detected; all account fields were masked and suppressed.'
    Add-Report 'Server guard: Headway demo server accepted.'

    $downloadUrl = 'https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe'
    Invoke-WebRequest -Uri $downloadUrl -OutFile $installer -TimeoutSec 240
    if (!(Test-Path -LiteralPath $installer) -or (Get-Item -LiteralPath $installer).Length -lt 100000) {
        throw 'Official MetaTrader 5 installer download is missing or unexpectedly small.'
    }
    Add-Report ("Official installer downloaded: {0} bytes" -f (Get-Item -LiteralPath $installer).Length)

    $installArg = '/path:"' + $installDir + '"'
    $install = Start-Process -FilePath $installer -ArgumentList @('/auto', $installArg) -PassThru -Wait
    Add-Report ("Installer exit code: {0}" -f $install.ExitCode)
    $terminal = Get-ChildItem -LiteralPath $installDir -Filter 'terminal64.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) { $terminal = Get-ChildItem -LiteralPath $installDir -Filter 'terminal.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if ($null -eq $terminal) { throw 'MT5 installation completed without terminal64.exe/terminal.exe.' }
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter 'metaeditor64.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw 'MetaEditor was not found in the isolated MT5 installation.' }
    Add-Report ("MT5 product version: {0}" -f (Get-Item -LiteralPath $terminal.FullName).VersionInfo.ProductVersion)

    $source = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\mt5\BitcoinIntelligence_ReadOnlyBridge.mq5'
    if (!(Test-Path -LiteralPath $source)) { throw 'The Mirsad read-only EA source file was not found in the checkout.' }
    $sourceText = Get-Content -LiteralPath $source -Raw
    if ($sourceText -match '(?i)\b(OrderSend|OrderSendAsync|PositionOpen|PositionClose|Buy|Sell)\s*\(') {
        throw 'Safety stop: the Mirsad EA source contains a trading function.'
    }
    $expertsDir = Join-Path $installDir 'MQL5\Experts'
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir 'Mirsad_BTC_ReadOnlyBridge.mq5'
    $eaBinary = Join-Path $expertsDir 'Mirsad_BTC_ReadOnlyBridge.ex5'
    $compileLog = Join-Path $expertsDir 'Mirsad_BTC_ReadOnlyBridge.log'
    Copy-Item -LiteralPath $source -Destination $eaSource -Force
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compiler = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compiler.WaitForExit(90000)) {
        Stop-Process -Id $compiler.Id -Force -ErrorAction SilentlyContinue
        throw 'MetaEditor compilation timed out after 90 seconds.'
    }
    Start-Sleep -Seconds 2
    if (!(Test-Path -LiteralPath $compileLog)) { throw 'MetaEditor did not create the Mirsad EA compile log.' }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    $compileText | Set-Content -LiteralPath (Join-Path $logDir 'mirsad-ea-compile.log') -Encoding utf8
    if (!(Test-Path -LiteralPath $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) {
        throw 'MetaEditor did not produce the compiled Mirsad .ex5 file.'
    }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') {
        throw 'MetaEditor did not report zero compile errors.'
    }
    Copy-Item -LiteralPath $eaBinary -Destination (Join-Path $logDir 'Mirsad_BTC_ReadOnlyBridge.ex5') -Force
    Add-Report 'RESULT: PASS — the actual Mirsad read-only EA compiled with zero errors.'
    Add-Report ("Compiled EA size: {0} bytes" -f (Get-Item -LiteralPath $eaBinary).Length)

    $loginConfig = Join-Path $root 'mt5-demo-login.ini'
    $configText = @"
[Common]
Login=$accountLogin
Password=$accountPassword
Server=$accountServer
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
    [System.IO.File]::WriteAllText($loginConfig, $configText, [System.Text.UTF8Encoding]::new($false))
    $loginForRedaction = [string]$accountLogin
    $accountPassword = $null
    $credentialRaw = $null
    $credentialObject = $null
    $namedFields = $null
    $credentialLines = $null

    $loginStart = Get-Date
    $terminalProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @('/portable', "/config:$loginConfig", "/login:$loginForRedaction") -WorkingDirectory $installDir -PassThru
    Add-Report 'MT5 terminal launched for demo authorization verification; account details suppressed.'
    $authorized = $false
    $rejected = $false
    $deadline = (Get-Date).AddSeconds(150)
    while ((Get-Date) -lt $deadline) {
        $logs = @(Get-ChildItem -LiteralPath (Join-Path $installDir 'Logs') -Filter '*.log' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 12)
        foreach ($file in $logs) {
            if ($file.LastWriteTime -lt $loginStart.AddSeconds(-3)) { continue }
            $logText = ''
            try { $logText = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction Stop } catch { continue }
            foreach ($line in ($logText -split "\r?\n")) {
                $isHeadway = $line -match '(?i)(Headway-Demo|mt5\.demo\.trade-hw\.online)'
                if ($isHeadway -and $line -match '(?i)(authorized on|successfully authorized|authorization successful|login successful)' -and $line -notmatch '(?i)(failed|invalid|not authorized|authorization error)') { $authorized = $true; break }
                if ($isHeadway -and $line -match '(?i)(authorization failed|failed to authorize|invalid account|invalid password|authorization rejected)') { $rejected = $true }
            }
            if ($authorized -or $rejected) { break }
        }
        if ($authorized -or $rejected) { break }
        if ($terminalProcess.HasExited) { Add-Report 'Terminal process exited before demo authorization was confirmed.'; break }
        Start-Sleep -Seconds 3
    }
    if ($authorized) {
        Add-Report 'RESULT: PASS — MT5 confirmed authorization to the Headway demo server.'
        Add-Report 'Trading safeguards: automated trading disabled; no EA attached; zero orders sent by this workflow.'
    } elseif ($rejected) {
        throw 'The Headway demo server rejected the stored account authorization; credential values were not logged.'
    } else {
        throw 'Headway demo authorization was not confirmed within the verification window; no order was attempted.'
    }

    Add-Report ("UTC finish: {0}" -f [DateTime]::UtcNow.ToString('o'))
    Get-Content -LiteralPath $report
}
catch {
    Add-Report ("RESULT: FAIL — {0}" -f $_.Exception.Message)
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
