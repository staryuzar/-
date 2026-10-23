$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "tv26-strategy-backtest"
$install = Join-Path $root "terminal"
$reports = Join-Path $PWD "tv26-strategy-results"
$installer = Join-Path $root "mt5setup.exe"
$source = Join-Path $PWD "trading-lab\tv26\TV26_FiveTF_Arabic_CANDIDATE.mq5"
$config = Join-Path $root "tv26-backtest.ini"
$summary = Join-Path $reports "strategy-backtest-summary.txt"
$testFrom = [string]$env:TV26_TEST_FROM
$testTo = [string]$env:TV26_TEST_TO
if ([string]::IsNullOrWhiteSpace($testFrom)) { $testFrom = "2026.09.01" }
if ([string]::IsNullOrWhiteSpace($testTo)) { $testTo = "2026.09.04" }
$culture = [Globalization.CultureInfo]::InvariantCulture
$startDate = [datetime]::ParseExact($testFrom,"yyyy.MM.dd",$culture)
$endDate = [datetime]::ParseExact($testTo,"yyyy.MM.dd",$culture)
if ($endDate -le $startDate) { throw "TV26_TEST_TO must be later than TV26_TEST_FROM; ToDate is exclusive." }
$rangeLabelStart = $startDate.ToString("yyyy-MM-dd",$culture)
$rangeLabelEnd = $endDate.AddDays(-1).ToString("yyyy-MM-dd",$culture)
New-Item -ItemType Directory -Path $root,$install,$reports -Force | Out-Null

# Credentials exist only in the configured GitHub Actions secret.
$credentialRaw = [string]$env:MT5_CREDENTIALS
if ([string]::IsNullOrWhiteSpace($credentialRaw)) {
  "STRATEGY BACKTEST NOT RUN: GitHub Actions secret mt5 is missing." | Set-Content -LiteralPath $summary -Encoding utf8
  throw "Missing secret mt5; no tester run attempted."
}
$accountLogin = ""; $accountPassword = ""; $accountServer = "mt5.demo.trade-hw.online"
$credentialObject = $null
if ($credentialRaw.TrimStart().StartsWith("{")) {
  try { $credentialObject = ConvertFrom-Json -InputObject $credentialRaw -ErrorAction Stop } catch { $credentialObject = $null }
}
if ($null -ne $credentialObject) {
  $accountLogin = [string]$credentialObject.login
  if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$credentialObject.account }
  $accountPassword = [string]$credentialObject.password
  if (![string]::IsNullOrWhiteSpace([string]$credentialObject.server)) { $accountServer = [string]$credentialObject.server }
} else {
  $lines = @($credentialRaw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  $fields = @{}
  foreach ($line in $lines) {
    if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$') { $fields[$matches[1].ToLowerInvariant()] = $matches[2] }
  }
  if ($fields.ContainsKey("login") -or $fields.ContainsKey("account") -or $fields.ContainsKey("password")) {
    $accountLogin = [string]$fields["login"]
    if (!$accountLogin) { $accountLogin = [string]$fields["account"] }
    $accountPassword = [string]$fields["password"]
    if ($fields["server"]) { $accountServer = [string]$fields["server"] }
  } elseif ($lines.Count -ge 2) {
    $accountLogin = [string]$lines[0]; $accountPassword = [string]$lines[1]
    if ($lines.Count -ge 3) { $accountServer = [string]$lines[2] }
  }
}
if ($accountLogin -notmatch '^\d{4,20}$' -or [string]::IsNullOrWhiteSpace($accountPassword)) {
  throw "Invalid MT5 secret format; expected JSON login/password/server or separate lines. Values suppressed."
}
Write-Output "::add-mask::$accountLogin"
Write-Output "::add-mask::$accountPassword"
Write-Output "::add-mask::$accountServer"
$credentialRaw = $null; $credentialObject = $null; $fields = $null; $lines = $null

@(
  "TV26 Strategy Tester backtest; simulated trades are allowed only inside this isolated tester run. InpTesterOnly=true blocks execution outside Strategy Tester.",
  "Symbol XAUUSD, tester timeframe M1, ratings M1/M5/M15/M30/H1.",
  "Range $rangeLabelStart to $rangeLabelEnd inclusive; MT5 Tester ToDate=$testTo (exclusive end date).",
  "Model 1 (1-minute OHLC), deposit 500 USD, leverage 1:1000.",
  "This is a preliminary historical strategy simulation. It is not a live account run, and it does not prove future profitability.",
  "UTC start: $([DateTime]::UtcNow.ToString('o'))"
) | Set-Content -LiteralPath $summary -Encoding utf8

try {
  if (!(Test-Path -LiteralPath $source)) { throw "TV26 source is missing." }
  Invoke-WebRequest -Uri "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" -OutFile $installer -TimeoutSec 180
  if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) { throw "Invalid official MT5 installer download." }
  $installerProc = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:$install") -PassThru -Wait
  $terminal = Get-ChildItem -LiteralPath $install -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  $editor = Get-ChildItem -LiteralPath $install -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if (!$terminal -or !$editor) { throw "MT5 terminal or MetaEditor not found after installer run (exit $($installerProc.ExitCode))." }
  "MT5 product version: $((Get-Item $terminal.FullName).VersionInfo.ProductVersion)" | Add-Content -LiteralPath $summary -Encoding utf8

  $expertDir = Join-Path $install "MQL5\Experts\TV26"
  New-Item -ItemType Directory -Path $expertDir -Force | Out-Null
  $eaPath = Join-Path $expertDir "TV26_FiveTF_Arabic_CANDIDATE.mq5"
  Copy-Item -LiteralPath $source -Destination $eaPath -Force
  $compile = Start-Process -FilePath $editor.FullName -ArgumentList ('/compile:"' + $eaPath + '" /log') -WorkingDirectory $install -PassThru
  if (!$compile.WaitForExit(120000)) {
    Stop-Process -Id $compile.Id -Force -ErrorAction SilentlyContinue
    throw "MetaEditor compilation timed out."
  }
  Start-Sleep -Seconds 2
  $ex5 = Join-Path $expertDir "TV26_FiveTF_Arabic_CANDIDATE.ex5"
  if (!(Test-Path $ex5)) { throw "MetaEditor did not produce the TV26 EX5." }
  $compileText = ""
  foreach ($lf in @(Get-ChildItem -LiteralPath $expertDir -Filter "*.log" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)) {
    $compileText += (Get-Content -LiteralPath $lf.FullName -Raw -ErrorAction SilentlyContinue) + [Environment]::NewLine
  }
  $safeCompile = $compileText -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]" -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
  $safeCompile | Set-Content -LiteralPath (Join-Path $reports "metaeditor-compile-log.txt") -Encoding utf8
  if ($compileText -match '(?i)\b[1-9]\d*\s+errors?\b' -or $compileText -match '(?i)\b[1-9]\d*\s+warnings?\b') {
    throw "MetaEditor log reports errors or warnings."
  }
  "EA compile: EX5 generated; no non-zero errors/warnings found in fresh logs." | Add-Content -LiteralPath $summary -Encoding utf8
  "Source SHA-256: $((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant())" | Add-Content -LiteralPath $summary -Encoding utf8

  $setDir = Join-Path $install "MQL5\Profiles\Tester"
  New-Item -ItemType Directory -Path $setDir -Force | Out-Null
  $setName = "TV26_StrategyBacktest.set"
  $setContent = @"
InpEnableTrading=true||true||0||true||N
InpDemoOnly=true||true||0||true||N
InpTesterOnly=true||true||0||true||N
InpMagic=26102327||26102327||1||26102327||N
InpRiskPercent=0.50||0.50||0.10||0.50||N
InpATRPeriod=14||14||1||14||N
InpStopATR=2.0||2.0||0.5||2.0||N
InpTargetATR=3.0||3.0||0.5||3.0||N
InpMaxSpreadPoints=100.0||100.0||10.0||100.0||N
InpDeviationPoints=20||20||1||20||N
InpTF1=1||1||1||1||N
InpTF2=5||5||1||5||N
InpTF3=15||15||1||15||N
InpTF4=30||30||1||30||N
InpTF5=16385||16385||1||16385||N
"@
  [System.IO.File]::WriteAllText((Join-Path $setDir $setName),$setContent,[System.Text.UTF8Encoding]::new($false))
  $reportBase = "TV26_StrategyBacktest_{0}_to_{1}" -f $rangeLabelStart,$rangeLabelEnd
  $ini = @"
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
AllowLiveTrading=1
AllowDllImport=0

[Tester]
Expert=TV26\TV26_FiveTF_Arabic_CANDIDATE.ex5
ExpertParameters=$setName
Symbol=XAUUSD
Period=M1
Model=1
ExecutionMode=0
Optimization=0
FromDate=$testFrom
ToDate=$testTo
ForwardMode=0
Deposit=500
Currency=USD
Leverage=1:1000
Report=$reportBase
ReplaceReport=1
ShutdownTerminal=1
UseLocal=1
UseRemote=0
UseCloud=0
Visual=0
"@
  [System.IO.File]::WriteAllText($config,$ini,[System.Text.UTF8Encoding]::new($false))
  "Tester configured: M1 chart; date range $rangeLabelStart to $rangeLabelEnd; InpEnableTrading=true; InpDemoOnly=true; InpTesterOnly=true. Orders are simulated inside MT5 Strategy Tester only." | Add-Content -LiteralPath $summary -Encoding utf8
  $env:MT5_CREDENTIALS = $null
  $accountPasswordForRedaction = $accountPassword
  $accountPassword = $null
  $tester = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", "/config:$config") -WorkingDirectory $install -PassThru
  if (!$tester.WaitForExit(900000)) {
    Stop-Process -Id $tester.Id -Force -ErrorAction SilentlyContinue
    throw "MT5 tester exceeded 15 minutes."
  }
  "Tester process exit code: $($tester.ExitCode)" | Add-Content -LiteralPath $summary -Encoding utf8

  $roots = @($install,(Join-Path $env:APPDATA "MetaQuotes\Terminal"),
             (Join-Path $env:LOCALAPPDATA "MetaQuotes\Terminal"))
  $candidates = @()
  foreach ($r in $roots) {
    if (Test-Path $r) {
      $candidates += @(Get-ChildItem -LiteralPath $r -Filter "TV26_Audit_XAUUSD_26102327.csv" -File -Recurse -ErrorAction SilentlyContinue)
    }
  }
  $audit = $candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (!$audit) {
    $diag = Join-Path $reports "diagnostics"
    New-Item -ItemType Directory -Path $diag -Force | Out-Null
    $i = 0
    foreach ($r in $roots) {
      if (!(Test-Path $r)) { continue }
      Get-ChildItem -LiteralPath $r -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 8 | ForEach-Object {
          try {
            $txt = Get-Content -LiteralPath $_.FullName -Raw
            $txt = $txt -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]"
            $txt = $txt -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
            if (![string]::IsNullOrWhiteSpace($accountPasswordForRedaction)) {
              $txt = $txt -replace [regex]::Escape($accountPasswordForRedaction), "[PASSWORD REDACTED]"
            }
            $txt = $txt -replace '(?i)(password|passwd)\s*[:=]\s*\S+', '$1=[REDACTED]'
            $i++; $txt | Set-Content -LiteralPath (Join-Path $diag ("mt5-log-" + $i + ".txt")) -Encoding utf8
          } catch {}
        }
    }
    throw "Tester ended but audit CSV was not found; diagnostics saved. Incomplete run, not parity evidence."
  }

  $auditOut = Join-Path $reports "TV26_Audit_XAUUSD_26102327.csv"
  Copy-Item -LiteralPath $audit.FullName -Destination $auditOut -Force
  "Audit CSV bytes: $((Get-Item $auditOut).Length)" | Add-Content -LiteralPath $summary -Encoding utf8
  "Audit CSV SHA-256: $((Get-FileHash -LiteralPath $auditOut -Algorithm SHA256).Hash.ToLowerInvariant())" | Add-Content -LiteralPath $summary -Encoding utf8
  $historyCandidates = @()
  foreach ($historyRoot in @($install,(Join-Path $env:APPDATA "MetaQuotes\Terminal"),(Join-Path $env:LOCALAPPDATA "MetaQuotes\Terminal"))) {
    if (Test-Path $historyRoot) {
      $historyCandidates += @(Get-ChildItem -LiteralPath $historyRoot -Filter "TV26_OHLC_History_XAUUSD.csv" -File -Recurse -ErrorAction SilentlyContinue)
    }
  }
  $history = $historyCandidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (!$history) { throw "Required OHLCV warmup history CSV was not exported." }
  $historyOut = Join-Path $reports "TV26_OHLC_History_XAUUSD.csv"
  Copy-Item -LiteralPath $history.FullName -Destination $historyOut -Force
  "Reference OHLCV CSV bytes: $((Get-Item $historyOut).Length)" | Add-Content -LiteralPath $summary -Encoding utf8
  "Reference OHLCV SHA-256: $((Get-FileHash -LiteralPath $historyOut -Algorithm SHA256).Hash.ToLowerInvariant())" | Add-Content -LiteralPath $summary -Encoding utf8
  $rows = @(Import-Csv -LiteralPath $auditOut)
  $summaryRows = @($rows | Where-Object { $_.component -eq "SUMMARY" })
  if ($summaryRows.Count -lt 1000) { throw "Coverage gate failed: fewer than 1000 summary rows across the timeframes." }
  foreach ($tf in @("د1","د5","د15","د30","س1")) {
    $tfRows = @($summaryRows | Where-Object { $_.timeframe -eq $tf })
    $ready = @($tfRows | Where-Object { $_.readiness -eq "OK" }).Count
    "$tf summary rows: $($tfRows.Count); complete: $ready; incomplete: $($tfRows.Count - $ready)" | Add-Content -LiteralPath $summary -Encoding utf8
    if ($tfRows.Count -eq 0) { throw "Coverage gate failed: no summary row for $tf." }
  }
  $htmlCandidates = @()
  foreach ($r in @($install,$PWD)) {
    if (Test-Path $r) {
      $htmlCandidates += @(Get-ChildItem -LiteralPath $r -Filter ($reportBase + ".htm*") -File -Recurse -ErrorAction SilentlyContinue)
    }
  }
  if ($htmlCandidates.Count -gt 0) {
    $html = Get-Content -LiteralPath $htmlCandidates[0].FullName -Raw
    $html = $html -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]"
    $html = $html -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
    [System.IO.File]::WriteAllText((Join-Path $reports "strategy-tester-report.html"),$html,[System.Text.UTF8Encoding]::new($false))
  $expectedInputs = @(
    '(?is)InpEnableTrading=true</b>',
    '(?is)InpDemoOnly=true</b>',
    '(?is)InpTesterOnly=true</b>',
    '(?is)InpMagic=26102327</b>'
  )
  foreach ($pattern in $expectedInputs) {
    if ($html -notmatch $pattern) {
      throw "Tester report does not confirm required safe backtest input pattern: $pattern"
    }
  }
  "Input verification: PASS (trading enabled only for tester; demo guard on; tester-only guard on; magic 26102327)." | Add-Content -LiteralPath $summary -Encoding utf8
  function Get-TesterMetric([string]$ReportHtml,[string]$Label) {
    $pattern = '(?is)<td[^>]*>\s*' + [regex]::Escape($Label) + '\s*</td>\s*<td[^>]*>\s*<b>(.*?)</b>'
    $match = [regex]::Match($ReportHtml,$pattern)
    if ($match.Success) { return (($match.Groups[1].Value -replace '<[^>]+>','').Trim()) }
    return "NOT FOUND"
  }
  foreach ($label in @("Initial Deposit:","Total Net Profit:","Gross Profit:","Gross Loss:","Profit Factor:",
                        "Expected Payoff:","Balance Drawdown Maximal:","Equity Drawdown Maximal:",
                        "Total Trades:","Profit Trades (% of total):","Loss Trades (% of total):",
                        "Short Trades (won %):","Long Trades (won %):")) {
    "$label $(Get-TesterMetric -ReportHtml $html -Label $label)" | Add-Content -LiteralPath $summary -Encoding utf8
  }
  $tradesRaw = Get-TesterMetric -ReportHtml $html -Label "Total Trades:"
  $tradeCount = 0
  if ($tradesRaw -match '^\d+') { $tradeCount = [int]$matches[0] }
  if ($tradeCount -eq 0) {
    "Trade assessment: NO_TRADES in this date range. The run is a valid result but cannot establish strategy quality." | Add-Content -LiteralPath $summary -Encoding utf8
  } else {
    "Trade assessment: $tradeCount simulated trades. Review profit, drawdown, win/loss distribution and tester logs; a positive net profit alone is not a pass." | Add-Content -LiteralPath $summary -Encoding utf8
  }

    "Tester HTML report saved." | Add-Content -LiteralPath $summary -Encoding utf8
  } else {
    throw "MT5 tester report HTML not found; refusing to classify the run as a completed backtest."
  }
  # Preserve MT5 Journal/Experts/Tester logs and redact credentials before artifact upload.
  $logsOut = Join-Path $reports "diagnostic-logs"
  New-Item -ItemType Directory -Path $logsOut -Force | Out-Null
  $logCandidates = @()
  foreach ($logRoot in @($install,(Join-Path $env:APPDATA "MetaQuotes\Terminal"),(Join-Path $env:LOCALAPPDATA "MetaQuotes\Terminal"))) {
    if (Test-Path $logRoot) {
      $logCandidates += @(Get-ChildItem -LiteralPath $logRoot -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue)
    }
  }
  $logCandidates = @($logCandidates | Sort-Object LastWriteTime -Descending | Select-Object -First 30)
  $logIndex = 0
  foreach ($logFile in $logCandidates) {
    try {
      $rawLog = Get-Content -LiteralPath $logFile.FullName -Raw -ErrorAction Stop
      $rawLog = $rawLog -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]"
      $rawLog = $rawLog -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
      if (![string]::IsNullOrWhiteSpace($accountPasswordForRedaction)) {
        $rawLog = $rawLog -replace [regex]::Escape($accountPasswordForRedaction), "[PASSWORD REDACTED]"
      }
      $rawLog = $rawLog -replace '(?i)(password|passwd)\s*[:=]\s*\S+', '$1=[REDACTED]'
      $logIndex++
      $dest = Join-Path $logsOut ("mt5-log-{0:D2}.txt" -f $logIndex)
      Set-Content -LiteralPath $dest -Value $rawLog -Encoding utf8
    } catch { }
  }
  "Diagnostic logs preserved (redacted): $logIndex" | Add-Content -LiteralPath $summary -Encoding utf8
  $diagText = ""
  foreach ($safeLog in @(Get-ChildItem -LiteralPath $logsOut -Filter "*.txt" -File -ErrorAction SilentlyContinue)) {
    try { $diagText += (Get-Content -LiteralPath $safeLog.FullName -Raw -ErrorAction Stop) + [Environment]::NewLine } catch {}
  }
  $diagnosticPatterns = [ordered]@{
    "consensus_signal_bars" = 'TV26_CONSENSUS;signal='
    "blocked_min_volume_risk_cap" = 'reason=MIN_VOLUME_RISK_CAP'
    "blocked_spread" = 'reason=SPREAD'
    "blocked_same_signal_latch" = 'reason=SAME_SIGNAL_LATCH'
    "blocked_demo_guard" = 'reason=NOT_DEMO_ACCOUNT'
    "accepted_orders" = 'TV26_ORDER_ACCEPTED;'
    "rejected_orders" = 'TV26_ORDER_REJECTED;'
    "blocked_invalid_atr" = 'reason=ATR_NOT_READY'
  }
  foreach ($metric in $diagnosticPatterns.Keys) {
    $count = [regex]::Matches($diagText,[regex]::Escape($diagnosticPatterns[$metric])).Count
    "$metric=$count" | Add-Content -LiteralPath $summary -Encoding utf8
  }
  "UTC finish: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $summary -Encoding utf8
  "Classification: STRATEGY_TESTER_SIMULATION. Results apply only to $rangeLabelStart through $rangeLabelEnd under the 1-minute OHLC model; no live orders are permitted by the tester-only guard." | Add-Content -LiteralPath $summary -Encoding utf8
  Get-Content -LiteralPath $summary
}
finally {
  $env:MT5_CREDENTIALS = $null
  $accountPassword = $null
  $accountPasswordForRedaction = $null
  if (Test-Path -LiteralPath $config) { Remove-Item -LiteralPath $config -Force -ErrorAction SilentlyContinue }
}
