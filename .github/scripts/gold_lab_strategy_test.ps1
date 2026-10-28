# Gold Intelligence Lab strategy tester smoke/backtest
# Runs only in an isolated MT5 Strategy Tester instance. It never submits live market orders.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Join-Path $env:RUNNER_TEMP "goldlab-mt5"
$terminalRoot = Join-Path $root "terminal"
$terminal = Get-ChildItem -LiteralPath $terminalRoot -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$ea = Join-Path $terminalRoot "MQL5\Experts\GoldIntelligenceLab\GoldIntelligenceLabEA.ex5"
$setDir = Join-Path $terminalRoot "MQL5\Profiles\Tester"
$reportsDir = Join-Path $terminalRoot "reports"
$dist = Join-Path $env:GITHUB_WORKSPACE "dist"
$reportDir = Join-Path $dist "strategy-test-reports"
$summaryPath = Join-Path $dist "strategy-test-summary.txt"
$diagnosticsPath = Join-Path $dist "strategy-test-diagnostics.txt"
New-Item -ItemType Directory -Path $dist,$reportDir,$setDir,$reportsDir -Force | Out-Null
@(
  "Gold Intelligence Lab — Strategy Tester report"
  "Mode: isolated MT5 Strategy Tester; simulated historical trades only"
  "Live order submission: not used"
  "Started UTC: $([DateTime]::UtcNow.ToString('o'))"
) | Set-Content -LiteralPath $summaryPath -Encoding utf8
"Diagnostics: no credential values should be written to this file." | Set-Content -LiteralPath $diagnosticsPath -Encoding utf8

function Stop-ProcessSafely($process) {
  if ($null -ne $process) {
    try {
      if (!$process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    } catch {}
  }
}

$loginProcess = $null
$testProcess = $null
$loginConfig = Join-Path $root "demo-login-private.ini"
$testerConfig = Join-Path $root "tester-private.ini"
try {
  if ($null -eq $terminal) { throw "The isolated MT5 terminal was not found." }
  if (!(Test-Path -LiteralPath $ea) -or (Get-Item -LiteralPath $ea).Length -le 0) {
    throw "The compiled GoldIntelligenceLabEA.ex5 is missing."
  }

  # Parse the existing repository Actions secret without ever printing its value.
  $raw = [string]$env:MT5_CREDENTIALS
  if ([string]::IsNullOrWhiteSpace($raw)) {
    throw "The repository Actions secret 'mt5' is missing; demo authentication and Strategy Tester were not started."
  }

  $accountLogin = ""
  $accountPassword = ""
  $accountServer = "mt5.demo.trade-hw.online"
  $obj = $null
  if ($raw.TrimStart().StartsWith("{")) {
    try { $obj = ConvertFrom-Json -InputObject $raw -ErrorAction Stop } catch { $obj = $null }
  }
  if ($null -ne $obj) {
    $accountLogin = [string]$obj.login
    if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$obj.account }
    $accountPassword = [string]$obj.password
    if (![string]::IsNullOrWhiteSpace([string]$obj.server)) { $accountServer = [string]$obj.server }
  } else {
    $lines = @($raw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
    $fields = @{}
    foreach ($line in $lines) {
      if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$') {
        $fields[$matches[1].ToLowerInvariant()] = $matches[2]
      }
    }
    if ($fields.ContainsKey("login") -or $fields.ContainsKey("account") -or $fields.ContainsKey("password")) {
      $accountLogin = [string]$fields["login"]
      if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$fields["account"] }
      $accountPassword = [string]$fields["password"]
      if (![string]::IsNullOrWhiteSpace([string]$fields["server"])) { $accountServer = [string]$fields["server"] }
    } elseif ($lines.Count -ge 2) {
      $accountLogin = [string]$lines[0]
      $accountPassword = [string]$lines[1]
      if ($lines.Count -ge 3) { $accountServer = [string]$lines[2] }
    }
  }

  # Hard-stop unless the selected server is explicitly a demo/test/practice server.
  if ($accountLogin -notmatch '^\d{4,20}$' -or [string]::IsNullOrWhiteSpace($accountPassword)) {
    throw "The repository demo credential secret has an invalid format; values were not logged."
  }
  if ($accountServer -notmatch '(?i)(demo|practice|trial)') {
    throw "Safety stop: the configured server is not explicitly named as a demo/practice/trial server. No tester was started."
  }
  Write-Output "::add-mask::$accountLogin"
  Write-Output "::add-mask::$accountPassword"
  Write-Output "::add-mask::$accountServer"
  Add-Content -LiteralPath $summaryPath -Value "Server classification: demo/test server only (server/account details redacted)."
  Add-Content -LiteralPath $summaryPath -Value "Compiled EA SHA-256: $((Get-FileHash -LiteralPath $ea -Algorithm SHA256).Hash)"

  # First confirm that this secret authenticates to a demo server. Expert trading is disabled.
  $loginConfigText = @"
[Common]
Login=$accountLogin
Password=$accountPassword
Server=$accountServer
ProxyEnable=0
KeepPrivate=1
NewsEnable=0
CertInstall=0

[Experts]
Enabled=0
AllowLiveTrading=0
AllowDllImport=0

[Charts]
ProfileLast=Default
MaxBars=100000
"@
  [IO.File]::WriteAllText($loginConfig, $loginConfigText, [Text.UTF8Encoding]::new($false))
  $loginStart = Get-Date
  $loginProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", ("/config:" + $loginConfig), ("/login:" + $accountLogin)) -WorkingDirectory $terminalRoot -PassThru
  $loginDeadline = (Get-Date).AddSeconds(120)
  $authorized = $false
  $rejected = $false
  while ((Get-Date) -lt $loginDeadline) {
    $logFiles = @(Get-ChildItem -LiteralPath (Join-Path $terminalRoot "Logs") -Filter "*.log" -File -ErrorAction SilentlyContinue |
      Where-Object { $_.LastWriteTime -ge $loginStart.AddSeconds(-3) } | Sort-Object LastWriteTime -Descending | Select-Object -First 12)
    foreach ($logFile in $logFiles) {
      $logText = ""
      try { $logText = Get-Content -LiteralPath $logFile.FullName -Raw -ErrorAction Stop } catch { continue }
      foreach ($line in ($logText -split "\r?\n")) {
        $isDemoServerLine = $line -match '(?i)(Headway-Demo|mt5\.demo\.trade-hw\.online|demo)'
        if ($isDemoServerLine -and $line -match '(?i)(authorized on|successfully authorized|authorization successful|login successful)' -and
            $line -notmatch '(?i)(failed|invalid|not authorized|authorization error)') {
          $authorized = $true
          break
        }
        if ($isDemoServerLine -and $line -match '(?i)(authorization failed|failed to authorize|invalid account|invalid password|authorization rejected)') {
          $rejected = $true
        }
      }
      if ($authorized -or $rejected) { break }
    }
    if ($authorized -or $rejected) { break }
    if ($loginProcess.HasExited -and ((Get-Date) -gt $loginStart.AddSeconds(15))) { break }
    Start-Sleep -Seconds 3
  }
  Stop-ProcessSafely $loginProcess
  $loginProcess = $null
  Remove-Item -LiteralPath $loginConfig -Force -ErrorAction SilentlyContinue
  if (!$authorized) {
    if ($rejected) { throw "MT5 rejected the configured demo account. No strategy test was run." }
    throw "Could not verify demo-server authorization in fresh terminal logs within 120 seconds. No strategy test was run."
  }
  Add-Content -LiteralPath $summaryPath -Value "Demo authentication: PASS. No live account login attempted."

  # MT5 parameter files use one fixed input value per line. Trading is enabled only
  # in the Strategy Tester simulation; the terminal's live-trading permission stays off.
  $setContent = @(
    "EnableTrading=true"
    "AllowRealAccountTrading=false"
    "RiskPercent=0.50"
    "EstimatedRoundTurnCostPerLot=7.0"
    "FastEMAPeriod=20"
    "SlowEMAPeriod=50"
    "ATRPeriod=14"
    "DonchianPeriod=20"
    "StopATRMultiple=2.0"
    "RewardRiskRatio=2.0"
    "MaxSpreadPoints=80"
    "MaxDailyLossPercent=2.0"
    "MaxEquityDrawdownPercent=15.0"
    "MaxTradesPerDay=3"
    "MagicNumber=28102026"
    "DeviationPoints=30"
  )
  $setPath = Join-Path $setDir "GoldIntelligenceLabEA.set"
  [IO.File]::WriteAllLines($setPath, $setContent, [Text.UTF8Encoding]::new($false))

  $fromDate = "2025.01.01"
  $toDate = (Get-Date).AddDays(-2).ToString("yyyy.MM.dd")
  $periods = @("M1","M5","M15","H1")
  $allPassed = $true

  foreach ($period in $periods) {
    $safeReportName = "GoldIntelligenceLab_$period"
    $summaryEntry = Join-Path $dist ("strategy-" + $period + ".txt")
    Add-Content -LiteralPath $summaryPath -Value ""
    Add-Content -LiteralPath $summaryPath -Value "[$period] Backtest started; symbol=XAUUSD; from=$fromDate; to=$toDate; model=1-minute OHLC; simulated orders only."

    $config = @"
[Common]
Login=$accountLogin
Password=$accountPassword
Server=$accountServer
ProxyEnable=0
KeepPrivate=1
NewsEnable=0
CertInstall=0

[Experts]
Enabled=1
AllowLiveTrading=0
AllowDllImport=0
ShutdownTerminal=1

[Charts]
ProfileLast=Default
MaxBars=100000

[Tester]
Expert=GoldIntelligenceLab\GoldIntelligenceLabEA
ExpertParameters=GoldIntelligenceLabEA.set
Symbol=XAUUSD
Period=$period
Login=$accountLogin
Deposit=10000
Currency=USD
Leverage=1:100
Model=1
ExecutionMode=0
Optimization=0
OptimizationCriterion=0
FromDate=$fromDate
ToDate=$toDate
ForwardMode=0
Report=reports\$safeReportName
ReplaceReport=1
UseCloud=0
Visual=0
"@
    [IO.File]::WriteAllText($testerConfig, $config, [Text.UTF8Encoding]::new($false))
    $freshReportBefore = Get-Date
    $testProcess = $null
    try {
      $testProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", ("/config:" + $testerConfig)) -WorkingDirectory $terminalRoot -PassThru
      if (!$testProcess.WaitForExit(600000)) {
        Stop-ProcessSafely $testProcess
        throw "Strategy Tester timed out after 10 minutes for $period."
      }
      Start-Sleep -Seconds 2
      $candidateReports = @(Get-ChildItem -LiteralPath $reportsDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like ($safeReportName + "*") -and $_.LastWriteTime -ge $freshReportBefore.AddSeconds(-2) } |
        Sort-Object LastWriteTime -Descending)
      if ($candidateReports.Count -eq 0) {
        throw "MetaTrader exited without generating the expected Strategy Tester report for $period."
      }
      $rawReportPath = $candidateReports[0].FullName
      if ((Get-Item -LiteralPath $rawReportPath).Length -lt 800) {
        throw "The Strategy Tester report for $period is unexpectedly small."
      }

      $html = Get-Content -LiteralPath $rawReportPath -Raw
      # Reports go into a public repo's workflow artifact: redact account/server identifiers.
      $html = $html.Replace($accountLogin,"[DEMO LOGIN REDACTED]")
      $html = $html.Replace($accountServer,"[DEMO SERVER]")
      $sanitizedReport = Join-Path $reportDir ($safeReportName + ".html")
      [IO.File]::WriteAllText($sanitizedReport,$html,[Text.UTF8Encoding]::new($false))

      $plain = [regex]::Replace($html,'<[^>]+>',' ')
      $plain = [System.Net.WebUtility]::HtmlDecode($plain)
      $plain = [regex]::Replace($plain,'\s+',' ').Trim()
      $metrics = @()
      foreach ($label in @("Total Net Profit","Profit Factor","Expected Payoff","Total Trades","Maximal Drawdown","Equity Drawdown Maximal")) {
        $idx = $plain.IndexOf($label,[StringComparison]::OrdinalIgnoreCase)
        if ($idx -ge 0) {
          $start = [Math]::Min($plain.Length,$idx + $label.Length)
          $length = [Math]::Min(100,$plain.Length-$start)
          $value = $plain.Substring($start,$length).Trim()
          $value = ($value -split '\s{2,}')[0]
          $metrics += ($label + ": " + $value)
        }
      }
      @(
        "Timeframe: $period"
        "Result: PASS — a non-empty MT5 Strategy Tester report was generated."
        "Symbol: XAUUSD"
        "Date range: $fromDate to $toDate"
        "Model: 1-minute OHLC"
        "Account type verified before test: demo server"
        "Live market orders: none; orders were simulated by Strategy Tester."
        "Report file: $sanitizedReport"
        "Key report fields (verify in HTML; formatting varies by MT5 build):"
        $metrics
      ) | Set-Content -LiteralPath $summaryEntry -Encoding utf8
      Add-Content -LiteralPath $summaryPath -Value "[$period] PASS — report generated ($((Get-Item -LiteralPath $sanitizedReport).Length) bytes)."
      foreach ($metric in $metrics) { Add-Content -LiteralPath $summaryPath -Value "  $metric" }
      Copy-Item -LiteralPath $sanitizedReport -Destination (Join-Path $root "package\$safeReportName.html") -Force
      Copy-Item -LiteralPath $summaryEntry -Destination (Join-Path $root "package\strategy-$period.txt") -Force
    }
    catch {
      $allPassed = $false
      $safeMessage = [string]$_.Exception.Message
      $safeMessage = $safeMessage.Replace($accountLogin,"[DEMO LOGIN REDACTED]").Replace($accountServer,"[DEMO SERVER]")
      Add-Content -LiteralPath $diagnosticsPath -Value ("[$period] " + $safeMessage)
      Add-Content -LiteralPath $summaryPath -Value "[$period] FAIL — $safeMessage"
      @(
        "Timeframe: $period"
        "Result: FAIL"
        "Reason: $safeMessage"
        "Date range: $fromDate to $toDate"
        "No live order was sent by this step."
      ) | Set-Content -LiteralPath $summaryEntry -Encoding utf8
    }
    finally {
      Stop-ProcessSafely $testProcess
      $testProcess = $null
      Remove-Item -LiteralPath $testerConfig -Force -ErrorAction SilentlyContinue
    }
  }

  # Rebuild the distributable archive to include the compiled EA and sanitized reports.
  $packageDir = Join-Path $root "package"
  $distZip = Join-Path $dist "GoldIntelligenceLab-MT5-Windows.zip"
  if (Test-Path -LiteralPath $distZip) { Remove-Item -LiteralPath $distZip -Force }
  Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $distZip -Force
  Add-Content -LiteralPath $summaryPath -Value ""
  Add-Content -LiteralPath $summaryPath -Value "Finished UTC: $([DateTime]::UtcNow.ToString('o'))"
  if ($allPassed) {
    Add-Content -LiteralPath $summaryPath -Value "OVERALL: PASS — all four Strategy Tester timeframes produced reports. This verifies test execution, not profitability."
    Write-Output "STRATEGY_TEST_RESULT=PASS"
  } else {
    Add-Content -LiteralPath $summaryPath -Value "OVERALL: FAIL — one or more timeframe tests did not generate reports. Read per-timeframe files and sanitized diagnostics."
    Write-Output "STRATEGY_TEST_RESULT=FAIL"
  }
  Get-Content -LiteralPath $summaryPath
  if (!$allPassed) { throw "One or more MT5 strategy tests failed. Diagnostic artifacts were saved without account credentials." }
}
catch {
  $safeMessage = [string]$_.Exception.Message
  if ($accountLogin) { $safeMessage = $safeMessage.Replace($accountLogin,"[DEMO LOGIN REDACTED]") }
  if ($accountServer) { $safeMessage = $safeMessage.Replace($accountServer,"[DEMO SERVER]") }
  Add-Content -LiteralPath $diagnosticsPath -Value ("FATAL: " + $safeMessage)
  Add-Content -LiteralPath $summaryPath -Value ("FATAL: " + $safeMessage)
  Write-Output ("STRATEGY_TEST_FATAL: " + $safeMessage)
  throw
}
finally {
  Stop-ProcessSafely $testProcess
  Stop-ProcessSafely $loginProcess
  Remove-Item -LiteralPath $loginConfig,$testerConfig -Force -ErrorAction SilentlyContinue
  # Clear credential strings from script variables before exit.
  $accountPassword = $null
  $raw = $null
  $obj = $null
}
