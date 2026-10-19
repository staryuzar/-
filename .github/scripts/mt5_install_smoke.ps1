# Installs the official MetaTrader 5 terminal into a temporary CI folder and smoke-tests launch.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "aurora-mt5-smoke"
$installDir = Join-Path $root "terminal"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Path $installDir, $logDir -Force | Out-Null
$report = Join-Path $logDir "mt5-smoke-report.txt"
$installer = Join-Path $root "mt5setup.exe"
$terminal = $null
$terminalProcess = $null
$loginConfig = $null

try {
    "Aurora MT5 integration smoke test" | Set-Content -LiteralPath $report -Encoding utf8
    "UTC start: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $report -Encoding utf8
    "Source: official MetaTrader 5 installer (MetaQuotes)" | Add-Content -LiteralPath $report -Encoding utf8

    # Read the GitHub Actions secret only into process memory. Supported formats:
    # JSON {"login":"...","password":"...","server":"..."} or two/three lines:
    # account login, trading password, optional server. Never echo or upload values.
    $credentialRaw = [string]$env:MT5_CREDENTIALS
    if ([string]::IsNullOrWhiteSpace($credentialRaw)) {
        throw "BLOCKED: repository Actions secret 'mt5' is missing. Configure it as JSON or as account-login/password on separate lines."
    }
    $accountLogin = ""
    $accountPassword = ""
    $accountServer = "mt5.demo.trade-hw.online"
    $credentialObject = $null
    if ($credentialRaw.TrimStart().StartsWith("{")) {
        try { $credentialObject = ConvertFrom-Json -InputObject $credentialRaw -ErrorAction Stop } catch { $credentialObject = $null }
    }
    if ($null -ne $credentialObject) {
        $accountLogin = [string]$credentialObject.login
        if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$credentialObject.account }
        $accountPassword = [string]$credentialObject.password
        if (-not [string]::IsNullOrWhiteSpace([string]$credentialObject.server)) { $accountServer = [string]$credentialObject.server }
    } else {
        $credentialLines = @($credentialRaw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
        $namedFields = @{}
        foreach ($line in $credentialLines) {
            if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Compile a harmless sample EA through MetaEditor; this does not log in or place trades.
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MT5 terminal installed but metaeditor64.exe was not found." }
    "MetaEditor path: $($metaEditor.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $expertsDir = Join-Path $installDir "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "AuroraCompileSmoke.mq5"
    $eaBinary = Join-Path $expertsDir "AuroraCompileSmoke.ex5"
    $compileLog = Join-Path $expertsDir "AuroraCompileSmoke.log"
    $eaCode = @'
#property strict
#property version "1.00"
#property description "Aurora CI compile smoke EA"
int OnInit() { return(INIT_SUCCEEDED); }
void OnDeinit(const int reason) {}
void OnTick() {}
'@
    [System.IO.File]::WriteAllText($eaSource, $eaCode, [System.Text.UTF8Encoding]::new($false))
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compilerProcess = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compilerProcess.WaitForExit(60000)) {
        Stop-Process -Id $compilerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor command-line compilation timed out after 60 seconds."
    }
    Start-Sleep -Seconds 1
    if (!(Test-Path $compileLog)) { throw "MetaEditor did not produce the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    "MetaEditor compile log: $($compileText.Trim())" | Add-Content -LiteralPath $report -Encoding utf8
    if (!(Test-Path $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) { throw "MetaEditor did not produce a non-empty AuroraCompileSmoke.ex5 file." }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') { throw "MetaEditor compile log does not confirm zero errors." }
    "RESULT: PASS — MetaEditor compiled a disposable sample EA with zero errors." | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }

    # Verify a real demo-account login using a temporary MT5 config.
    # Trading remains disabled; no EA is attached and no orders are sent.
    $loginConfig = Join-Path $root "mt5-demo-login.ini"
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
    $accountLogin = $null
    $accountPassword = $null
    $credentialRaw = $null
    $credentialObject = $null
    $namedFields = $null
    $credentialLines = $null

    $terminalProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", "/config:$loginConfig") -WorkingDirectory $installDir -PassThru
    "Launched isolated MT5 process for demo authorization check; account details omitted." | Add-Content -LiteralPath $report -Encoding utf8
    $authorizationConfirmed = $false
    $authorizationRejected = $false
    $loginDeadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $loginDeadline) {
        $logFiles = @()
        foreach ($logRoot in @((Join-Path $installDir "Logs"), (Join-Path $installDir "MQL5\Logs"), $installDir)) {
            if (Test-Path $logRoot) {
                $logFiles += @(Get-ChildItem -LiteralPath $logRoot -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 8)
            }
        }
        foreach ($logFile in ($logFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 20)) {
            $logText = ""
            try { $logText = Get-Content -LiteralPath $logFile.FullName -Raw -ErrorAction Stop } catch { continue }
            foreach ($logLine in ($logText -split "\r?\n")) {
                $isServer = $logLine -match '(?i)(Headway-Demo|mt5\.demo\.trade-hw\.online)'
                if ($isServer -and $logLine -match '(?i)(authorized on|successfully authorized|authorization successful|login successful)' -and
                    $logLine -notmatch '(?i)(failed|invalid|not authorized|authorization error)') {
                    $authorizationConfirmed = $true
                    break
                }
                if ($isServer -and $logLine -match '(?i)(authorization failed|failed to authorize|invalid account|invalid password|authorization rejected)') {
                    $authorizationRejected = $true
                }
            }
            if ($authorizationConfirmed) { break }
        }
        if ($authorizationConfirmed) { break }
        if ($authorizationRejected) { break }
        Start-Sleep -Seconds 3
    }
    if ($authorizationConfirmed) {
        "RESULT: PASS — MT5 logs confirmed authorization to the Headway demo server. No orders were placed." | Add-Content -LiteralPath $report -Encoding utf8
    } elseif ($authorizationRejected) {
        throw "MT5 server rejected or could not validate the demo-account authorization. Credential values and raw terminal logs were not written to the report."
    } else {
        throw "MT5 demo authorization was not confirmed within 120 seconds. Check the demo secret format and server connectivity; credential values and raw terminal logs were not written to the report."
    }
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
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
) {
                $namedFields[$matches[1].ToLowerInvariant()] = $matches[2]
            }
        }
        if ($namedFields.ContainsKey("login") -or $namedFields.ContainsKey("account") -or $namedFields.ContainsKey("password")) {
            $accountLogin = [string]$namedFields["login"]
            if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$namedFields["account"] }
            $accountPassword = [string]$namedFields["password"]
            if (-not [string]::IsNullOrWhiteSpace([string]$namedFields["server"])) { $accountServer = [string]$namedFields["server"] }
        } elseif ($credentialLines.Count -ge 2) {
            $accountLogin = [string]$credentialLines[0]
            $accountPassword = [string]$credentialLines[1]
            if ($credentialLines.Count -ge 3) { $accountServer = [string]$credentialLines[2] }
        } else {
            throw "Invalid format for repository Actions secret 'mt5'. Use JSON or at least two separate lines (login and password)."
        }
    }
    if ($accountLogin -notmatch '^\d{4,20}    Invoke-WebRequest -Uri $uri -OutFile $installer -TimeoutSec 180
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Compile a harmless sample EA through MetaEditor; this does not log in or place trades.
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MT5 terminal installed but metaeditor64.exe was not found." }
    "MetaEditor path: $($metaEditor.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $expertsDir = Join-Path $installDir "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "AuroraCompileSmoke.mq5"
    $eaBinary = Join-Path $expertsDir "AuroraCompileSmoke.ex5"
    $compileLog = Join-Path $expertsDir "AuroraCompileSmoke.log"
    $eaCode = @'
#property strict
#property version "1.00"
#property description "Aurora CI compile smoke EA"
int OnInit() { return(INIT_SUCCEEDED); }
void OnDeinit(const int reason) {}
void OnTick() {}
'@
    [System.IO.File]::WriteAllText($eaSource, $eaCode, [System.Text.UTF8Encoding]::new($false))
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compilerProcess = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compilerProcess.WaitForExit(60000)) {
        Stop-Process -Id $compilerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor command-line compilation timed out after 60 seconds."
    }
    Start-Sleep -Seconds 1
    if (!(Test-Path $compileLog)) { throw "MetaEditor did not produce the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    "MetaEditor compile log: $($compileText.Trim())" | Add-Content -LiteralPath $report -Encoding utf8
    if (!(Test-Path $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) { throw "MetaEditor did not produce a non-empty AuroraCompileSmoke.ex5 file." }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') { throw "MetaEditor compile log does not confirm zero errors." }
    "RESULT: PASS — MetaEditor compiled a disposable sample EA with zero errors." | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }
    "LIMIT: no broker login, demo account, Strategy Tester run, or trade was performed; only a disposable sample EA was compiled, not the user’s EA." | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
    throw
}
finally { }
 -or [string]::IsNullOrWhiteSpace($accountPassword)) {
        throw "Invalid account credential format in Actions secret 'mt5'; account/password values were not logged."
    }
    if ($accountLogin -match '[\r\n=]' -or $accountPassword -match '[\r\n]' -or $accountServer -match '[\r\n]') {
        throw "Account credential fields contain unsupported line breaks or delimiters."
    }
    "Demo account secret detected; credential values suppressed." | Add-Content -LiteralPath $report -Encoding utf8

    $uri = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    Invoke-WebRequest -Uri $uri -OutFile $installer -TimeoutSec 180
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Compile a harmless sample EA through MetaEditor; this does not log in or place trades.
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MT5 terminal installed but metaeditor64.exe was not found." }
    "MetaEditor path: $($metaEditor.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $expertsDir = Join-Path $installDir "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "AuroraCompileSmoke.mq5"
    $eaBinary = Join-Path $expertsDir "AuroraCompileSmoke.ex5"
    $compileLog = Join-Path $expertsDir "AuroraCompileSmoke.log"
    $eaCode = @'
#property strict
#property version "1.00"
#property description "Aurora CI compile smoke EA"
int OnInit() { return(INIT_SUCCEEDED); }
void OnDeinit(const int reason) {}
void OnTick() {}
'@
    [System.IO.File]::WriteAllText($eaSource, $eaCode, [System.Text.UTF8Encoding]::new($false))
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compilerProcess = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compilerProcess.WaitForExit(60000)) {
        Stop-Process -Id $compilerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor command-line compilation timed out after 60 seconds."
    }
    Start-Sleep -Seconds 1
    if (!(Test-Path $compileLog)) { throw "MetaEditor did not produce the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    "MetaEditor compile log: $($compileText.Trim())" | Add-Content -LiteralPath $report -Encoding utf8
    if (!(Test-Path $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) { throw "MetaEditor did not produce a non-empty AuroraCompileSmoke.ex5 file." }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') { throw "MetaEditor compile log does not confirm zero errors." }
    "RESULT: PASS — MetaEditor compiled a disposable sample EA with zero errors." | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }
    "LIMIT: no broker login, demo account, Strategy Tester run, or trade was performed; only a disposable sample EA was compiled, not the user’s EA." | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
    throw
}
finally { }
) {
                $namedFields[$matches[1].ToLowerInvariant()] = $matches[2]
            }
        }
        if ($namedFields.ContainsKey("login") -or $namedFields.ContainsKey("account") -or $namedFields.ContainsKey("password")) {
            $accountLogin = [string]$namedFields["login"]
            if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$namedFields["account"] }
            $accountPassword = [string]$namedFields["password"]
            if (-not [string]::IsNullOrWhiteSpace([string]$namedFields["server"])) { $accountServer = [string]$namedFields["server"] }
        } elseif ($credentialLines.Count -ge 2) {
            $accountLogin = [string]$credentialLines[0]
            $accountPassword = [string]$credentialLines[1]
            if ($credentialLines.Count -ge 3) { $accountServer = [string]$credentialLines[2] }
        } else {
            throw "Invalid format for repository Actions secret 'mt5'. Use JSON or at least two separate lines (login and password)."
        }
    }
    if ($accountLogin -notmatch '^\d{4,20}
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Compile a harmless sample EA through MetaEditor; this does not log in or place trades.
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MT5 terminal installed but metaeditor64.exe was not found." }
    "MetaEditor path: $($metaEditor.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $expertsDir = Join-Path $installDir "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "AuroraCompileSmoke.mq5"
    $eaBinary = Join-Path $expertsDir "AuroraCompileSmoke.ex5"
    $compileLog = Join-Path $expertsDir "AuroraCompileSmoke.log"
    $eaCode = @'
#property strict
#property version "1.00"
#property description "Aurora CI compile smoke EA"
int OnInit() { return(INIT_SUCCEEDED); }
void OnDeinit(const int reason) {}
void OnTick() {}
'@
    [System.IO.File]::WriteAllText($eaSource, $eaCode, [System.Text.UTF8Encoding]::new($false))
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compilerProcess = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compilerProcess.WaitForExit(60000)) {
        Stop-Process -Id $compilerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor command-line compilation timed out after 60 seconds."
    }
    Start-Sleep -Seconds 1
    if (!(Test-Path $compileLog)) { throw "MetaEditor did not produce the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    "MetaEditor compile log: $($compileText.Trim())" | Add-Content -LiteralPath $report -Encoding utf8
    if (!(Test-Path $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) { throw "MetaEditor did not produce a non-empty AuroraCompileSmoke.ex5 file." }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') { throw "MetaEditor compile log does not confirm zero errors." }
    "RESULT: PASS — MetaEditor compiled a disposable sample EA with zero errors." | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }

    # Verify a real demo-account login using a temporary MT5 config.
    # Trading remains disabled; no EA is attached and no orders are sent.
    $loginConfig = Join-Path $root "mt5-demo-login.ini"
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
    $accountLogin = $null
    $accountPassword = $null
    $credentialRaw = $null
    $credentialObject = $null
    $namedFields = $null
    $credentialLines = $null

    $terminalProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", "/config:$loginConfig") -WorkingDirectory $installDir -PassThru
    "Launched isolated MT5 process for demo authorization check; account details omitted." | Add-Content -LiteralPath $report -Encoding utf8
    $authorizationConfirmed = $false
    $authorizationRejected = $false
    $loginDeadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $loginDeadline) {
        $logFiles = @()
        foreach ($logRoot in @((Join-Path $installDir "Logs"), (Join-Path $installDir "MQL5\Logs"), $installDir)) {
            if (Test-Path $logRoot) {
                $logFiles += @(Get-ChildItem -LiteralPath $logRoot -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 8)
            }
        }
        foreach ($logFile in ($logFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 20)) {
            $logText = ""
            try { $logText = Get-Content -LiteralPath $logFile.FullName -Raw -ErrorAction Stop } catch { continue }
            foreach ($logLine in ($logText -split "\r?\n")) {
                $isServer = $logLine -match '(?i)(Headway-Demo|mt5\.demo\.trade-hw\.online)'
                if ($isServer -and $logLine -match '(?i)(authorized on|successfully authorized|authorization successful|login successful)' -and
                    $logLine -notmatch '(?i)(failed|invalid|not authorized|authorization error)') {
                    $authorizationConfirmed = $true
                    break
                }
                if ($isServer -and $logLine -match '(?i)(authorization failed|failed to authorize|invalid account|invalid password|authorization rejected)') {
                    $authorizationRejected = $true
                }
            }
            if ($authorizationConfirmed) { break }
        }
        if ($authorizationConfirmed) { break }
        if ($authorizationRejected) { break }
        Start-Sleep -Seconds 3
    }
    if ($authorizationConfirmed) {
        "RESULT: PASS — MT5 logs confirmed authorization to the Headway demo server. No orders were placed." | Add-Content -LiteralPath $report -Encoding utf8
    } elseif ($authorizationRejected) {
        throw "MT5 server rejected or could not validate the demo-account authorization. Credential values and raw terminal logs were not written to the report."
    } else {
        throw "MT5 demo authorization was not confirmed within 120 seconds. Check the demo secret format and server connectivity; credential values and raw terminal logs were not written to the report."
    }
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
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
) {
                $namedFields[$matches[1].ToLowerInvariant()] = $matches[2]
            }
        }
        if ($namedFields.ContainsKey("login") -or $namedFields.ContainsKey("account") -or $namedFields.ContainsKey("password")) {
            $accountLogin = [string]$namedFields["login"]
            if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$namedFields["account"] }
            $accountPassword = [string]$namedFields["password"]
            if (-not [string]::IsNullOrWhiteSpace([string]$namedFields["server"])) { $accountServer = [string]$namedFields["server"] }
        } elseif ($credentialLines.Count -ge 2) {
            $accountLogin = [string]$credentialLines[0]
            $accountPassword = [string]$credentialLines[1]
            if ($credentialLines.Count -ge 3) { $accountServer = [string]$credentialLines[2] }
        } else {
            throw "Invalid format for repository Actions secret 'mt5'. Use JSON or at least two separate lines (login and password)."
        }
    }
    if ($accountLogin -notmatch '^\d{4,20}    Invoke-WebRequest -Uri $uri -OutFile $installer -TimeoutSec 180
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Compile a harmless sample EA through MetaEditor; this does not log in or place trades.
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MT5 terminal installed but metaeditor64.exe was not found." }
    "MetaEditor path: $($metaEditor.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $expertsDir = Join-Path $installDir "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "AuroraCompileSmoke.mq5"
    $eaBinary = Join-Path $expertsDir "AuroraCompileSmoke.ex5"
    $compileLog = Join-Path $expertsDir "AuroraCompileSmoke.log"
    $eaCode = @'
#property strict
#property version "1.00"
#property description "Aurora CI compile smoke EA"
int OnInit() { return(INIT_SUCCEEDED); }
void OnDeinit(const int reason) {}
void OnTick() {}
'@
    [System.IO.File]::WriteAllText($eaSource, $eaCode, [System.Text.UTF8Encoding]::new($false))
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compilerProcess = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compilerProcess.WaitForExit(60000)) {
        Stop-Process -Id $compilerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor command-line compilation timed out after 60 seconds."
    }
    Start-Sleep -Seconds 1
    if (!(Test-Path $compileLog)) { throw "MetaEditor did not produce the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    "MetaEditor compile log: $($compileText.Trim())" | Add-Content -LiteralPath $report -Encoding utf8
    if (!(Test-Path $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) { throw "MetaEditor did not produce a non-empty AuroraCompileSmoke.ex5 file." }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') { throw "MetaEditor compile log does not confirm zero errors." }
    "RESULT: PASS — MetaEditor compiled a disposable sample EA with zero errors." | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }
    "LIMIT: no broker login, demo account, Strategy Tester run, or trade was performed; only a disposable sample EA was compiled, not the user’s EA." | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
    throw
}
finally { }
 -or [string]::IsNullOrWhiteSpace($accountPassword)) {
        throw "Invalid account credential format in Actions secret 'mt5'; account/password values were not logged."
    }
    if ($accountLogin -match '[\r\n=]' -or $accountPassword -match '[\r\n]' -or $accountServer -match '[\r\n]') {
        throw "Account credential fields contain unsupported line breaks or delimiters."
    }
    "Demo account secret detected; credential values suppressed." | Add-Content -LiteralPath $report -Encoding utf8

    $uri = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    Invoke-WebRequest -Uri $uri -OutFile $installer -TimeoutSec 180
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Compile a harmless sample EA through MetaEditor; this does not log in or place trades.
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MT5 terminal installed but metaeditor64.exe was not found." }
    "MetaEditor path: $($metaEditor.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $expertsDir = Join-Path $installDir "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "AuroraCompileSmoke.mq5"
    $eaBinary = Join-Path $expertsDir "AuroraCompileSmoke.ex5"
    $compileLog = Join-Path $expertsDir "AuroraCompileSmoke.log"
    $eaCode = @'
#property strict
#property version "1.00"
#property description "Aurora CI compile smoke EA"
int OnInit() { return(INIT_SUCCEEDED); }
void OnDeinit(const int reason) {}
void OnTick() {}
'@
    [System.IO.File]::WriteAllText($eaSource, $eaCode, [System.Text.UTF8Encoding]::new($false))
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compilerProcess = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compilerProcess.WaitForExit(60000)) {
        Stop-Process -Id $compilerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor command-line compilation timed out after 60 seconds."
    }
    Start-Sleep -Seconds 1
    if (!(Test-Path $compileLog)) { throw "MetaEditor did not produce the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    "MetaEditor compile log: $($compileText.Trim())" | Add-Content -LiteralPath $report -Encoding utf8
    if (!(Test-Path $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) { throw "MetaEditor did not produce a non-empty AuroraCompileSmoke.ex5 file." }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') { throw "MetaEditor compile log does not confirm zero errors." }
    "RESULT: PASS — MetaEditor compiled a disposable sample EA with zero errors." | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }
    "LIMIT: no broker login, demo account, Strategy Tester run, or trade was performed; only a disposable sample EA was compiled, not the user’s EA." | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
    throw
}
finally { }
 -or [string]::IsNullOrWhiteSpace($accountPassword)) {
        throw "Invalid account credential format in Actions secret 'mt5'; account/password values were not logged."
    }
    if ($accountLogin -match '[\r\n=]' -or $accountPassword -match '[\r\n]' -or $accountServer -match '[\r\n]') {
        throw "Account credential fields contain unsupported line breaks or delimiters."
    }
    "Demo account secret detected; credential values suppressed." | Add-Content -LiteralPath $report -Encoding utf8

    $uri = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    Invoke-WebRequest -Uri $uri -OutFile $installer -TimeoutSec 180
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Compile a harmless sample EA through MetaEditor; this does not log in or place trades.
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MT5 terminal installed but metaeditor64.exe was not found." }
    "MetaEditor path: $($metaEditor.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $expertsDir = Join-Path $installDir "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "AuroraCompileSmoke.mq5"
    $eaBinary = Join-Path $expertsDir "AuroraCompileSmoke.ex5"
    $compileLog = Join-Path $expertsDir "AuroraCompileSmoke.log"
    $eaCode = @'
#property strict
#property version "1.00"
#property description "Aurora CI compile smoke EA"
int OnInit() { return(INIT_SUCCEEDED); }
void OnDeinit(const int reason) {}
void OnTick() {}
'@
    [System.IO.File]::WriteAllText($eaSource, $eaCode, [System.Text.UTF8Encoding]::new($false))
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compilerProcess = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compilerProcess.WaitForExit(60000)) {
        Stop-Process -Id $compilerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor command-line compilation timed out after 60 seconds."
    }
    Start-Sleep -Seconds 1
    if (!(Test-Path $compileLog)) { throw "MetaEditor did not produce the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    "MetaEditor compile log: $($compileText.Trim())" | Add-Content -LiteralPath $report -Encoding utf8
    if (!(Test-Path $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) { throw "MetaEditor did not produce a non-empty AuroraCompileSmoke.ex5 file." }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') { throw "MetaEditor compile log does not confirm zero errors." }
    "RESULT: PASS — MetaEditor compiled a disposable sample EA with zero errors." | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }

    # Verify a real demo-account login using a temporary MT5 config.
    # Trading remains disabled; no EA is attached and no orders are sent.
    $loginConfig = Join-Path $root "mt5-demo-login.ini"
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
    $accountLogin = $null
    $accountPassword = $null
    $credentialRaw = $null
    $credentialObject = $null
    $namedFields = $null
    $credentialLines = $null

    $terminalProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", "/config:$loginConfig") -WorkingDirectory $installDir -PassThru
    "Launched isolated MT5 process for demo authorization check; account details omitted." | Add-Content -LiteralPath $report -Encoding utf8
    $authorizationConfirmed = $false
    $authorizationRejected = $false
    $loginDeadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $loginDeadline) {
        $logFiles = @()
        foreach ($logRoot in @((Join-Path $installDir "Logs"), (Join-Path $installDir "MQL5\Logs"), $installDir)) {
            if (Test-Path $logRoot) {
                $logFiles += @(Get-ChildItem -LiteralPath $logRoot -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 8)
            }
        }
        foreach ($logFile in ($logFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 20)) {
            $logText = ""
            try { $logText = Get-Content -LiteralPath $logFile.FullName -Raw -ErrorAction Stop } catch { continue }
            foreach ($logLine in ($logText -split "\r?\n")) {
                $isServer = $logLine -match '(?i)(Headway-Demo|mt5\.demo\.trade-hw\.online)'
                if ($isServer -and $logLine -match '(?i)(authorized on|successfully authorized|authorization successful|login successful)' -and
                    $logLine -notmatch '(?i)(failed|invalid|not authorized|authorization error)') {
                    $authorizationConfirmed = $true
                    break
                }
                if ($isServer -and $logLine -match '(?i)(authorization failed|failed to authorize|invalid account|invalid password|authorization rejected)') {
                    $authorizationRejected = $true
                }
            }
            if ($authorizationConfirmed) { break }
        }
        if ($authorizationConfirmed) { break }
        if ($authorizationRejected) { break }
        Start-Sleep -Seconds 3
    }
    if ($authorizationConfirmed) {
        "RESULT: PASS — MT5 logs confirmed authorization to the Headway demo server. No orders were placed." | Add-Content -LiteralPath $report -Encoding utf8
    } elseif ($authorizationRejected) {
        throw "MT5 server rejected or could not validate the demo-account authorization. Credential values and raw terminal logs were not written to the report."
    } else {
        throw "MT5 demo authorization was not confirmed within 120 seconds. Check the demo secret format and server connectivity; credential values and raw terminal logs were not written to the report."
    }
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
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
) {
                $namedFields[$matches[1].ToLowerInvariant()] = $matches[2]
            }
        }
        if ($namedFields.ContainsKey("login") -or $namedFields.ContainsKey("account") -or $namedFields.ContainsKey("password")) {
            $accountLogin = [string]$namedFields["login"]
            if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$namedFields["account"] }
            $accountPassword = [string]$namedFields["password"]
            if (-not [string]::IsNullOrWhiteSpace([string]$namedFields["server"])) { $accountServer = [string]$namedFields["server"] }
        } elseif ($credentialLines.Count -ge 2) {
            $accountLogin = [string]$credentialLines[0]
            $accountPassword = [string]$credentialLines[1]
            if ($credentialLines.Count -ge 3) { $accountServer = [string]$credentialLines[2] }
        } else {
            throw "Invalid format for repository Actions secret 'mt5'. Use JSON or at least two separate lines (login and password)."
        }
    }
    if ($accountLogin -notmatch '^\d{4,20}    Invoke-WebRequest -Uri $uri -OutFile $installer -TimeoutSec 180
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Compile a harmless sample EA through MetaEditor; this does not log in or place trades.
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MT5 terminal installed but metaeditor64.exe was not found." }
    "MetaEditor path: $($metaEditor.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $expertsDir = Join-Path $installDir "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "AuroraCompileSmoke.mq5"
    $eaBinary = Join-Path $expertsDir "AuroraCompileSmoke.ex5"
    $compileLog = Join-Path $expertsDir "AuroraCompileSmoke.log"
    $eaCode = @'
#property strict
#property version "1.00"
#property description "Aurora CI compile smoke EA"
int OnInit() { return(INIT_SUCCEEDED); }
void OnDeinit(const int reason) {}
void OnTick() {}
'@
    [System.IO.File]::WriteAllText($eaSource, $eaCode, [System.Text.UTF8Encoding]::new($false))
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compilerProcess = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compilerProcess.WaitForExit(60000)) {
        Stop-Process -Id $compilerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor command-line compilation timed out after 60 seconds."
    }
    Start-Sleep -Seconds 1
    if (!(Test-Path $compileLog)) { throw "MetaEditor did not produce the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    "MetaEditor compile log: $($compileText.Trim())" | Add-Content -LiteralPath $report -Encoding utf8
    if (!(Test-Path $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) { throw "MetaEditor did not produce a non-empty AuroraCompileSmoke.ex5 file." }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') { throw "MetaEditor compile log does not confirm zero errors." }
    "RESULT: PASS — MetaEditor compiled a disposable sample EA with zero errors." | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }
    "LIMIT: no broker login, demo account, Strategy Tester run, or trade was performed; only a disposable sample EA was compiled, not the user’s EA." | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
    throw
}
finally { }
 -or [string]::IsNullOrWhiteSpace($accountPassword)) {
        throw "Invalid account credential format in Actions secret 'mt5'; account/password values were not logged."
    }
    if ($accountLogin -match '[\r\n=]' -or $accountPassword -match '[\r\n]' -or $accountServer -match '[\r\n]') {
        throw "Account credential fields contain unsupported line breaks or delimiters."
    }
    "Demo account secret detected; credential values suppressed." | Add-Content -LiteralPath $report -Encoding utf8

    $uri = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    Invoke-WebRequest -Uri $uri -OutFile $installer -TimeoutSec 180
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Compile a harmless sample EA through MetaEditor; this does not log in or place trades.
    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MT5 terminal installed but metaeditor64.exe was not found." }
    "MetaEditor path: $($metaEditor.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $expertsDir = Join-Path $installDir "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "AuroraCompileSmoke.mq5"
    $eaBinary = Join-Path $expertsDir "AuroraCompileSmoke.ex5"
    $compileLog = Join-Path $expertsDir "AuroraCompileSmoke.log"
    $eaCode = @'
#property strict
#property version "1.00"
#property description "Aurora CI compile smoke EA"
int OnInit() { return(INIT_SUCCEEDED); }
void OnDeinit(const int reason) {}
void OnTick() {}
'@
    [System.IO.File]::WriteAllText($eaSource, $eaCode, [System.Text.UTF8Encoding]::new($false))
    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compilerProcess = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory $installDir -PassThru
    if (!$compilerProcess.WaitForExit(60000)) {
        Stop-Process -Id $compilerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor command-line compilation timed out after 60 seconds."
    }
    Start-Sleep -Seconds 1
    if (!(Test-Path $compileLog)) { throw "MetaEditor did not produce the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    "MetaEditor compile log: $($compileText.Trim())" | Add-Content -LiteralPath $report -Encoding utf8
    if (!(Test-Path $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) { throw "MetaEditor did not produce a non-empty AuroraCompileSmoke.ex5 file." }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') { throw "MetaEditor compile log does not confirm zero errors." }
    "RESULT: PASS — MetaEditor compiled a disposable sample EA with zero errors." | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }
    "LIMIT: no broker login, demo account, Strategy Tester run, or trade was performed; only a disposable sample EA was compiled, not the user’s EA." | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
    throw
}
finally { }
