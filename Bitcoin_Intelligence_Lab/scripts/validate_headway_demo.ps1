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
    Add-Report "Trading actions are disabled in this CI job; no EA is attached and no orders are sent."

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
            if ($named["server"]) { $server = [string]$named["server"] }
        } elseif ($lines.Count -ge 2) {
            $login = [string]$lines[0]
            $password = [string]$lines[1]
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
    Add-Report "No expert was attached; Algo Trading remained disabled; zero trade requests were sent."
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
