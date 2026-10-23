$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "goldlab-mt5"
$install = Join-Path $root "terminal"
$reports = Join-Path $PWD "goldlab-results"
New-Item -ItemType Directory -Path $install,$reports -Force | Out-Null
$installer = Join-Path $root "mt5setup.exe"
$summary = Join-Path $reports "run-summary.txt"
$credentialRaw = [string]$env:MT5_CREDENTIALS
if ([string]::IsNullOrWhiteSpace($credentialRaw)) { throw "Missing Actions secret 'mt5'; no MT5 tester run attempted." }

$accountLogin = ""; $accountPassword = ""; $accountServer = "mt5.demo.trade-hw.online"
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
  $lines = @($credentialRaw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
  $fields = @{}
  foreach ($line in $lines) {
    if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$') { $fields[$matches[1].ToLowerInvariant()] = $matches[2] }
  }
  if ($fields.ContainsKey("login") -or $fields.ContainsKey("account") -or $fields.ContainsKey("password")) {
    $accountLogin = [string]$fields["login"]
    if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$fields["account"] }
    $accountPassword = [string]$fields["password"]
    if (-not [string]::IsNullOrWhiteSpace([string]$fields["server"])) { $accountServer = [string]$fields["server"] }
  } elseif ($lines.Count -ge 2) {
    $accountLogin = [string]$lines[0]; $accountPassword = [string]$lines[1]
    if ($lines.Count -ge 3) { $accountServer = [string]$lines[2] }
  }
}
if ($accountLogin -notmatch '^\d{4,20}$' -or [string]::IsNullOrWhiteSpace($accountPassword)) {
  throw "Invalid MT5 secret format. Expected JSON login/password/server or separate login and password lines; values suppressed."
}
Write-Output "::add-mask::$accountLogin"
Write-Output "::add-mask::$accountPassword"
Write-Output "::add-mask::$accountServer"
$accountPasswordForConfig = $accountPassword
$credentialRaw = $null; $credentialObject = $null; $fields = $null; $lines = $null

"GoldLab MT5 Strategy Tester run" | Set-Content -LiteralPath $summary -Encoding utf8
"Test period: 2026-09-01 through 2026-10-19 (short-side-only diagnostic)" | Add-Content -LiteralPath $summary -Encoding utf8
"EA: GoldLabEA; Symbol XAUUSD; timeframe M5; model 1 (1-minute OHLC diagnostic; not real-tick validation)" | Add-Content -LiteralPath $summary -Encoding utf8
"Parameter experiment: risk=0.50%, stop=0.45 ATR, max spread=100 points, max ADX=40, long entries disabled for one-sided diagnostic. OHLC only, not production validation." | Add-Content -LiteralPath $summary -Encoding utf8
"Deposit: 500 USD; leverage 1:1000; trade mode is tester only; no live orders are authorized." | Add-Content -LiteralPath $summary -Encoding utf8
"UTC start: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $summary -Encoding utf8

try {
  $url = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
  Invoke-WebRequest -Uri $url -OutFile $installer -TimeoutSec 180
  if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) { throw "Official MT5 installer missing or too small." }
  $proc = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$install`"") -PassThru -Wait
  $terminal = Get-ChildItem -LiteralPath $install -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  $editor = Get-ChildItem -LiteralPath $install -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if (!$terminal -or !$editor) { throw "MT5 terminal or MetaEditor not found after install (installer exit $($proc.ExitCode))." }
  "MT5 version: $((Get-Item $terminal.FullName).VersionInfo.ProductVersion)" | Add-Content -LiteralPath $summary -Encoding utf8

  $expertDir = Join-Path $install "MQL5\Experts\GoldLab"
  New-Item -ItemType Directory -Path $expertDir -Force | Out-Null
  $source = Join-Path $PWD "trading-lab\gold-xauusd\GoldLabEA.mq5"
  if (!(Test-Path $source)) { throw "GoldLabEA.mq5 source missing." }
  $eaPath = Join-Path $expertDir "GoldLabEA.mq5"
  Copy-Item -LiteralPath $source -Destination $eaPath -Force
  $compileLog = Join-Path $expertDir "GoldLabEA.log"
  $compile = Start-Process -FilePath $editor.FullName -ArgumentList ('/compile:"' + $eaPath + '" /log') -WorkingDirectory $install -PassThru
  if (!$compile.WaitForExit(90000)) { Stop-Process -Id $compile.Id -Force -ErrorAction SilentlyContinue; throw "MetaEditor compile timed out." }
  Start-Sleep -Seconds 2
  if (!(Test-Path $compileLog)) { throw "MetaEditor compile log not produced." }
  $compileText = Get-Content -LiteralPath $compileLog -Raw
  $compileTotals = [regex]::Match($compileText, '(?im)^\s*Result:\s*(\d+)\s+errors,\s*(\d+)\s+warnings')
  if (!$compileTotals.Success) { throw "MetaEditor result counts could not be parsed; see compile-log.txt." }
  $compileErrorCount = [int]$compileTotals.Groups[1].Value
  $compileWarningCount = [int]$compileTotals.Groups[2].Value
  $safeCompile = $compileText -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]" -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
  $safeCompile | Set-Content -LiteralPath (Join-Path $reports "compile-log.txt") -Encoding utf8
  if (!(Test-Path (Join-Path $expertDir "GoldLabEA.ex5")) -or $compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') {
    throw "EA compilation did not confirm zero errors. See sanitized compile-log.txt."
  }
  "Compile result: PASS ($compileErrorCount errors, $compileWarningCount warnings)" | Add-Content -LiteralPath $summary -Encoding utf8

  $config = Join-Path $root "goldlab-tester.ini"
  $reportRelative = "goldlab-results\GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-10-19"
  New-Item -ItemType Directory -Path (Join-Path $install "goldlab-results") -Force | Out-Null

  # Controlled execution-safety verification at 0.50% risk and 0.45 ATR stop. Spread guard/quote-side stops are code safety fixes; strategy performance still requires separate review.
  $setDir = Join-Path $install "MQL5\Profiles\Tester"
  New-Item -ItemType Directory -Path $setDir -Force | Out-Null
  $setName = "GoldLabShortOnlyADX40Stop045.set"
  $setPath = Join-Path $setDir $setName
  $setContent = @"
InpMagic=2026102101||2026102101||1||2026102101||N
InpEntryTF=5||5||1||5||N
InpBiasTF=16385||16385||1||16385||N
InpRiskPercent=0.5||0.5||0.1||0.5||N
InpFastEMA=20||20||1||20||N
InpSlowEMA=50||50||1||50||N
InpBiasFastEMA=50||50||1||50||N
InpBiasSlowEMA=200||200||1||200||N
InpRSIPeriod=14||14||1||14||N
InpRSIMidline=50.0||50.0||1.0||50.0||N
InpADXPeriod=14||14||1||14||N
InpMinADX=18.0||18.0||1.0||18.0||N
InpMaxADX=40.0||40.0||1.0||40.0||N
InpAllowLong=false||true||0||true||N
InpATRPeriod=14||14||1||14||N
InpStopATR=0.45||0.45||0.05||0.45||N
InpMaxSpreadPoints=100.0||100.0||10.0||100.0||N
InpTargetATR=2.4||2.4||0.1||2.4||N
InpTrailATR=1.4||1.4||0.1||1.4||N
InpCloseOnOpposite=true||false||0||true||N
InpWriteTradeCSV=true||false||0||true||N
"@
  [System.IO.File]::WriteAllText($setPath,$setContent,[System.Text.UTF8Encoding]::new($false))
  $setContent | Set-Content -LiteralPath (Join-Path $reports $setName) -Encoding utf8
  "Tester parameter file: $setName (risk=0.50%, stop=0.45 ATR, max spread=100 points, ADX 18-40, long entries disabled)" | Add-Content -LiteralPath $summary -Encoding utf8
  $ini = @"
[Common]
Login=$accountLogin
Password=$accountPasswordForConfig
Server=$accountServer
ProxyEnable=0
KeepPrivate=1
NewsEnable=0
CertInstall=0

[Experts]
Enabled=1
AllowLiveTrading=0
AllowDllImport=0

[Tester]
Expert=GoldLab\GoldLabEA.ex5
ExpertParameters=$setName
Symbol=XAUUSD
Period=M5
Model=1
ExecutionMode=0
Optimization=0
FromDate=2026.09.01
ToDate=2026.10.19
ForwardMode=0
Deposit=500
Currency=USD
Leverage=1:1000
Report=$reportRelative
ReplaceReport=1
ShutdownTerminal=1
UseLocal=1
UseRemote=0
UseCloud=0
Visual=0
"@
  [System.IO.File]::WriteAllText($config,$ini,[System.Text.UTF8Encoding]::new($false))
  $env:MT5_CREDENTIALS = $null
  $accountPasswordForConfig = $null
  $terminalProc = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", "/config:$config") -WorkingDirectory $install -PassThru
  if (!$terminalProc.WaitForExit(300000)) {
    Stop-Process -Id $terminalProc.Id -Force -ErrorAction SilentlyContinue
    throw "Isolated forced-path Strategy Tester run exceeded 5 minutes; no completed result accepted."
  }
  $possibleReports = @(
    (Join-Path $install ($reportRelative + ".htm")),
    (Join-Path $install ($reportRelative + ".html")),
    (Join-Path $PWD ($reportRelative + ".htm")),
    (Join-Path $PWD ($reportRelative + ".html"))
  )
  "Tester terminal exit code: $($terminalProc.ExitCode)" | Add-Content -LiteralPath $summary -Encoding utf8
  $foundReport = $possibleReports | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (!$foundReport) {
    $foundReport = Get-ChildItem -LiteralPath $install -Filter "GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19.htm" -File -Recurse -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty FullName -First 1
  }
  if (!$foundReport) {
    "Tester report: NOT FOUND in expected or recursive install paths" | Add-Content -LiteralPath $summary -Encoding utf8
    "This is a failed/incomplete test, not a zero-trade result." | Add-Content -LiteralPath $summary -Encoding utf8

    # Preserve diagnostics before failing so a missing report can be explained.
    $diagDir = Join-Path $reports "diagnostics"
    New-Item -ItemType Directory -Path $diagDir -Force | Out-Null
    $candidateRoots = @($install, (Join-Path $env:APPDATA "MetaQuotes\Terminal"))
    $idx = 0
    foreach ($candidateRoot in $candidateRoots) {
      if (!(Test-Path $candidateRoot)) { continue }
      Get-ChildItem -LiteralPath $candidateRoot -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 12 | ForEach-Object {
          try {
            $raw = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction Stop
            $raw = $raw -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]"
            $raw = $raw -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
            $raw = $raw -replace '(?i)(password|passwd)\s*[:=]\s*\S+', '$1=[REDACTED]'
            $idx++
            $raw | Set-Content -LiteralPath (Join-Path $diagDir ("diagnostic-log-{0:D2}.txt" -f $idx)) -Encoding utf8
          } catch { }
        }
    }
    $reportCandidates = Get-ChildItem -LiteralPath $install -File -Recurse -ErrorAction SilentlyContinue |
      Where-Object { $_.Extension -in @(".htm", ".html", ".xml", ".ini") -and $_.Name -match "(?i)(report|tester|goldlab|config)" } |
      Select-Object -First 100 FullName,Length,LastWriteTime
    $reportCandidates | Format-Table -AutoSize | Out-String | Set-Content -LiteralPath (Join-Path $diagDir "candidate-files.txt") -Encoding utf8
    "Diagnostic logs preserved: $idx" | Add-Content -LiteralPath $summary -Encoding utf8
    throw "MT5 did not produce the expected Strategy Tester report. Diagnostic logs were preserved."
  }
  $html = Get-Content -LiteralPath $foundReport -Raw
  $html = $html -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]"
  $html = $html -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
  $safeReport = Join-Path $reports "GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19.htm"
  [System.IO.File]::WriteAllText($safeReport,$html,[System.Text.UTF8Encoding]::new($false))
  "Tester report: produced at $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $summary -Encoding utf8
  "Report size: $((Get-Item $safeReport).Length) bytes" | Add-Content -LiteralPath $summary -Encoding utf8

  # Copy candidate logs/reports, but redact account identifier before artifact upload.
  $logCandidates = @()
  $logCandidates += Get-ChildItem -LiteralPath $install -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue
  $logCandidates += Get-ChildItem -LiteralPath (Join-Path $env:APPDATA "MetaQuotes\Terminal") -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue
  $logsOut = Join-Path $reports "logs"
  New-Item -ItemType Directory -Path $logsOut -Force | Out-Null
  $auditFiles = @(Get-ChildItem -LiteralPath $install -Filter "GoldLab_trade_audit.csv" -File -Recurse -ErrorAction SilentlyContinue)
  if ($auditFiles.Count -gt 0) {
    $auditOut = Join-Path $reports "trade-audit"
    New-Item -ItemType Directory -Path $auditOut -Force | Out-Null
    $n=0
    foreach ($af in $auditFiles) {
      $n++
      Copy-Item -LiteralPath $af.FullName -Destination (Join-Path $auditOut ("GoldLab_trade_audit-{0:D2}.csv" -f $n)) -Force
    }
    "Trade audit CSV files found: $($auditFiles.Count)" | Add-Content -LiteralPath $summary -Encoding utf8
  } else {
    "Trade audit CSV: not produced (possible zero trades, tester files path variation, or EA execution issue; inspect report/logs)." | Add-Content -LiteralPath $summary -Encoding utf8
  }
  $idx=0
  foreach ($lf in ($logCandidates | Sort-Object LastWriteTime -Descending | Select-Object -First 20)) {
    try {
      $raw = Get-Content -LiteralPath $lf.FullName -Raw -ErrorAction Stop
      $raw = $raw -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]"
      $raw = $raw -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
      $raw = $raw -replace '(?i)(password|passwd)\s*[:=]\s*\S+', '$1=[REDACTED]'
      $idx++; $raw | Set-Content -LiteralPath (Join-Path $logsOut ("mt5-log-{0:D2}.txt" -f $idx)) -Encoding utf8
    } catch { }
  }
  "UTC finish: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $summary -Encoding utf8
  "IMPORTANT: only the generated tester report and journal can establish whether trades were actually simulated. Missing report or missing history means FAIL/incomplete, not success." | Add-Content -LiteralPath $summary -Encoding utf8
  # Reject a zero-history report before interpreting inputs or performance.
  $periodMatch = [regex]::Match($html,'(?is)Period:</td>\s*<td[^>]*><b>\s*([A-Z0-9]+)\s*\((\d{4}\.\d{2}\.\d{2})\s*-\s*(\d{4}\.\d{2}\.\d{2})\)\s*</b>')
  $barsMatch = [regex]::Match($html,'(?is)Bars:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
  $ticksMatch = [regex]::Match($html,'(?is)Ticks:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
  $reportBars = -1; $reportTicks = -1
  if ($barsMatch.Success) { $reportBars = [int]$barsMatch.Groups[1].Value.Replace(",","") }
  if ($ticksMatch.Success) { $reportTicks = [long]$ticksMatch.Groups[1].Value.Replace(",","") }
  $emptyHistoryReasons = [System.Collections.Generic.List[string]]::new()
  if (!$periodMatch.Success) {
    $emptyHistoryReasons.Add("Report period is missing or malformed.")
  } else {
    if ($periodMatch.Groups[1].Value -ne "M5") { $emptyHistoryReasons.Add("Unexpected report timeframe: $($periodMatch.Groups[1].Value).") }
    if ($periodMatch.Groups[2].Value -eq "1970.01.01" -or $periodMatch.Groups[3].Value -eq "1970.01.01") {
      $emptyHistoryReasons.Add("MT5 returned the default 1970 report period.")
    }
  }
  if ($reportBars -le 0) { $emptyHistoryReasons.Add("MT5 report has zero/missing bars.") }
  if ($reportTicks -le 0) { $emptyHistoryReasons.Add("MT5 report has zero/missing ticks.") }
  if ($emptyHistoryReasons.Count -gt 0) {
    $recentTesterLogs = @()
    if (Test-Path -LiteralPath $logsOut) {
      foreach ($logFile in @(Get-ChildItem -LiteralPath $logsOut -Filter "*.txt" -File -ErrorAction SilentlyContinue)) {
        $recentTesterLogs += @(Get-Content -LiteralPath $logFile.FullName -ErrorAction SilentlyContinue |
          Where-Object { $_ -match '(?i)no history data|history ticks canceled|history download.*cancel|not enough.*history' })
      }
    }
    @(
      "Data integrity gate: FAIL — empty/incomplete Strategy Tester history; this is NOT a strategy performance result.",
      "Parsed period: $(if ($periodMatch.Success) { $periodMatch.Groups[1].Value + ' (' + $periodMatch.Groups[2].Value + ' - ' + $periodMatch.Groups[3].Value + ')' } else { 'UNPARSED' })",
      "Bars: $reportBars",
      "Ticks: $reportTicks",
      "History failure markers: $($recentTesterLogs.Count)"
    ) + @($emptyHistoryReasons | ForEach-Object { "Reason: $_" }) + @($recentTesterLogs | Select-Object -First 20 | ForEach-Object { "Journal: $_" }) |
      Add-Content -LiteralPath $summary -Encoding utf8
    throw "MT5 report contains an empty or incomplete price-history result; do not evaluate strategy inputs/performance. See saved report and logs."
  }
  $paramsConfirmed = (($html -match '(?is)InpRiskPercent=0\.5</b>') -and ($html -match '(?is)InpStopATR=0\.45</b>') -and ($html -match '(?is)InpMaxSpreadPoints=100(?:\.0+)?</b>') -and ($html -match '(?is)InpMaxADX=40(?:\.0+)?</b>') -and ($html -match '(?is)InpAllowLong=false</b>'))
  if ($paramsConfirmed) {
    "Input verification: PASS (risk=0.5, stop=0.45 ATR, max spread=100, max ADX=40, long entries disabled)" | Add-Content -LiteralPath $summary -Encoding utf8
  } else {
    "Input verification: FAIL (MT5 report does not confirm all requested short-only test inputs; reject comparison)" | Add-Content -LiteralPath $summary -Encoding utf8
  }
  Get-Content -LiteralPath $summary
  if (-not $paramsConfirmed) { throw "Tester did not apply requested short-only test parameters; comparison result rejected." }
}
finally {
  $env:MT5_CREDENTIALS = $null
  $accountPasswordForConfig = $null
  if (Test-Path (Join-Path $root "goldlab-tester.ini")) { Remove-Item (Join-Path $root "goldlab-tester.ini") -Force -ErrorAction SilentlyContinue }
}
