$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Matched A/B control: disable EMA20 rejection while holding the other Model=4 candidate inputs and date window constant.
# This wrapper rewrites only the disposable CI workspace, never the committed runner.
$scriptPath = ".github/scripts/goldlab_mt5_test.ps1"
$eaPath = "trading-lab/gold-xauusd/GoldLabEA.mq5"
$resultsDir = "goldlab-results"
if (!(Test-Path -LiteralPath $scriptPath)) { throw "GoldLab tester script not found." }
if (!(Test-Path -LiteralPath $eaPath)) { throw "GoldLab EA source not found." }

$content = Get-Content -LiteralPath $scriptPath -Raw
$parameterChanges = @(
  @("FromDate=2026.09.01", "FromDate=2026.09.01"),
  @("Model=1", "Model=4"),
  @("InpMaxADX=40.0||40.0||1.0||40.0||N", "InpMaxADX=27.0||27.0||1.0||27.0||N"),
  @("InpMaxADX=27.0||27.0||1.0||27.0||N", "InpMaxADX=25.0||25.0||1.0||25.0||N"),
  @("InpMaxADX=40(?:\.0+)?</b>", "InpMaxADX=27(?:\.0+)?</b>"),
  @("InpMaxADX=27(?:\.0+)?</b>", "InpMaxADX=25(?:\.0+)?</b>"),
  @("max ADX=40", "max ADX=25"),
  @("ADX 18-40", "ADX 18-25"),
  @("GoldLabShortOnlyADX40Stop045.set", "GoldLabShortOnlyADX27Stop045.set"),
  @("GoldLabShortOnlyADX27Stop045.set", "GoldLabADX27NoCandleStop045.set"),
  @("GoldLabADX27NoCandleStop045.set", "GoldLabADX27FastEMARejectStop045.set"),
  @("GoldLabADX27FastEMARejectStop045.set", "GoldLabADX25FastEMARejectStop045.set")
)
$changes = @(
  @("2026-09-01 through 2026-10-19 (short-side-only diagnostic)", "2026-09-01 through 2026-10-20 (matched-period Model=4 EMA20 rejection OFF control; ADX 25 fixed)"),
  @("model 1 (1-minute OHLC diagnostic; not real-tick validation)", "model 4 (Every tick based on real ticks; matched EMA20 rejection-off control only)"),
  @("OHLC only, not production validation.", "matched-period EMA20 rejection-off control only; no live orders."),
  @("GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-10-19", "GoldLab_adx25_model4_ema_control_2026-09-01_to_2026-10-20"),
  @("ToDate=2026.10.19", "ToDate=2026.10.21"),
  @("GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19", "GoldLab_adx25_model4_ema_control_2026-09-01_to_2026-10-20")
)
foreach ($change in $parameterChanges) {
  if (!$content.Contains($change[0])) { throw "Expected ADX27 parameter marker missing: $($change[0])" }
  $content = $content.Replace($change[0], $change[1])
}
$setCsvMarker = "InpWriteTradeCSV=true||false||0||true||N"
if (!$content.Contains($setCsvMarker)) { throw "CSV SET marker missing; cannot add candle-direction input safely." }
$content = $content.Replace($setCsvMarker, $setCsvMarker + [Environment]::NewLine + "InpRequireSignalCandleDirection=false||false||0||false||N" + [Environment]::NewLine + "InpRequireFastEMARejection=false||false||0||false||N")
$confirmationCheck = '($html -match ''(?is)InpAllowLong=false</b>''))'
if (!$content.Contains($confirmationCheck)) { throw "Tester input verification marker missing." }
$content = $content.Replace($confirmationCheck, '($html -match ''(?is)InpAllowLong=false</b>'') -and ($html -match ''(?is)InpRequireSignalCandleDirection=false</b>'') -and ($html -match ''(?is)InpRequireFastEMARejection=false</b>''))')
$content = $content.Replace("Input verification: PASS (risk=0.5, stop=0.45 ATR, max spread=100, max ADX=25, long entries disabled)", "Input verification: PASS (risk=0.5, stop=0.45 ATR, max spread=100, max ADX=25, long disabled, candle-direction confirmation=false, fast EMA rejection=false)")
$content = $content.Replace("max ADX=40", "max ADX=25")
$content = $content.Replace("ADX 18-40", "ADX 18-25")
foreach ($change in $changes) {
  if (!$content.Contains($change[0])) { throw "Expected tester marker not found; refusing to run an unverified period: $($change[0])" }
  $content = $content.Replace($change[0], $change[1])
}
Set-Content -LiteralPath $scriptPath -Value $content -Encoding utf8
$verified = Get-Content -LiteralPath $scriptPath -Raw
$checks = @(
  ($verified -match 'FromDate=2026\.09\.01\s*\r?\nToDate=2026\.10\.21'),
  ($verified -match '2026-09-01 through 2026-10-20'),
  ($verified -match 'InpAllowLong=false'),
  ($verified -match 'InpRiskPercent=0\.5'),
  ($verified -match 'InpStopATR=0\.45'),
  ($verified -match 'InpMaxSpreadPoints=100\.0'),
  ($verified -match 'InpMaxADX=25\.0'),
  ($verified -match 'InpRequireSignalCandleDirection=false'),
  ($verified -match 'InpRequireFastEMARejection=false'),
  ($verified -match 'Model=4')
)
if ($checks -contains $false) { throw "Historical Model=4 preflight failed: date range, risk, stop, spread, ADX, direction, or tester model mismatch." }

New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null
$sourceHash = (Get-FileHash -LiteralPath $eaPath -Algorithm SHA256).Hash.ToLowerInvariant()
$testerHash = (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
@(
  "GoldLab ADX25 Model=4 EMA20-rejection-off control (2026-09-01 to 2026-10-20)",
  "Period: 2026-09-01 through 2026-10-20",
  "Symbol: XAUUSD; timeframe: M5; model: Model=4, Every tick based on real ticks (matched-period control; actual coverage is in the journal)",
  "Risk: 0.50%; stop: 0.45 ATR; target: 2.4 ATR; trail: 1.4 ATR",
  "Max spread: 100 points; ADX 18-25; long entries disabled",
  "EA source SHA-256: $sourceHash",
  "Runner-local tester script SHA-256: $testerHash",
  "UTC preflight: $([DateTime]::UtcNow.ToString('o'))"
) | Set-Content -LiteralPath (Join-Path $resultsDir "adx25-model4-ema-control-preflight.txt") -Encoding utf8

& $scriptPath
if (-not $?) { throw "GoldLab Strategy Tester invocation failed." }

$reportPath = Join-Path $resultsDir "GoldLab_adx25_model4_ema_control_2026-09-01_to_2026-10-20.htm"
if (!(Test-Path -LiteralPath $reportPath) -or (Get-Item -LiteralPath $reportPath).Length -le 0) {
  throw "Expected historical Model=4 HTML report is missing/empty; this is an incomplete run, not a zero-trade result."
}
$html = Get-Content -LiteralPath $reportPath -Raw
if ($html -notmatch '2026\.09\.01\s*-\s*2026\.10\.21') { throw "Tester report does not prove the requested final holdout period." }

function Read-TesterMetric([string]$label,[string]$source) {
  $escaped = [regex]::Escape($label)
  $pattern = "(?is)<td[^>]*>\s*" + $escaped + ":\s*</td>\s*<td[^>]*>\s*<b>(.*?)</b>"
  $match = [regex]::Match($source,$pattern)
  if ($match.Success) { return ($match.Groups[1].Value -replace '<[^>]+>','').Trim() }
  return "NOT_FOUND"
}
$metrics = [ordered]@{
  "Bars" = Read-TesterMetric "Bars" $html
  "History Quality" = Read-TesterMetric "History Quality" $html
  "Total Net Profit" = Read-TesterMetric "Total Net Profit" $html
  "Profit Factor" = Read-TesterMetric "Profit Factor" $html
  "Expected Payoff" = Read-TesterMetric "Expected Payoff" $html
  "Equity Drawdown Maximal" = Read-TesterMetric "Equity Drawdown Maximal" $html
  "Total Trades" = Read-TesterMetric "Total Trades" $html
  "Profit Trades (% of total)" = Read-TesterMetric "Profit Trades (% of total)" $html
  "Loss Trades (% of total)" = Read-TesterMetric "Loss Trades (% of total)" $html
  "Maximal consecutive loss" = Read-TesterMetric "Maximal consecutive loss (count)" $html
}
$lines = @(
  "# GoldLab ADX25 Model=4 EMA20-rejection-off matched-period control report audit",
  "",
  "- Period: 2026-09-01 through 2026-10-20",
  "- Model: Model=4 — Every tick based on real ticks; actual real-tick coverage must be verified in MT5 journal",
  "- EA SHA-256: $sourceHash",
  "- Tester report SHA-256: $((Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant())",
  "- Report bytes: $((Get-Item -LiteralPath $reportPath).Length)",
  "",
  "## Extracted Strategy Tester metrics",
  ""
)
foreach ($key in $metrics.Keys) { $lines += ("- " + $key + ": " + $metrics[$key]) }
$barCount = 0
if ($metrics["Bars"] -match '^\s*\d+') { $barCount = [int]$Matches[0] }
$logText = ""
$logsDir = Join-Path $resultsDir "logs"
if (Test-Path -LiteralPath $logsDir) {
  $logFiles = @(Get-ChildItem -LiteralPath $logsDir -Filter "*.txt" -File -ErrorAction SilentlyContinue)
  foreach ($logFile in $logFiles) {
    $logText += (Get-Content -LiteralPath $logFile.FullName -Raw -ErrorAction SilentlyContinue) + [Environment]::NewLine
  }
}
$dateTokens = [regex]::Matches($logText,'(?m)^.*?(2026\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2})\s+GoldLab\|SIGNAL_AUDIT\|')
$lastMarketTime = $null
foreach ($token in $dateTokens) {
  try {
    $parsed = [datetime]::ParseExact($token.Groups[1].Value,'yyyy.MM.dd HH:mm:ss',[Globalization.CultureInfo]::InvariantCulture)
    if ($null -eq $lastMarketTime -or $parsed -gt $lastMarketTime) { $lastMarketTime = $parsed }
  } catch {}
}
$historyRangeMatches = [regex]::Matches($logText, '(?i)history synchronized from (\d{4}\.\d{2}\.\d{2}) to (\d{4}\.\d{2}\.\d{2})')
$historySyncEnd = $null
foreach ($historyMatch in $historyRangeMatches) {
  try {
    $historyEndCandidate = [datetime]::ParseExact($historyMatch.Groups[2].Value, 'yyyy.MM.dd', [Globalization.CultureInfo]::InvariantCulture)
    if ($null -eq $historySyncEnd -or $historyEndCandidate -gt $historySyncEnd) { $historySyncEnd = $historyEndCandidate }
  } catch {}
}
$historySyncedThroughTarget = ($null -ne $historySyncEnd -and $historySyncEnd.Date -ge [datetime]'2026-10-20')
$dateCoverage = ($null -ne $lastMarketTime -and $lastMarketTime.Date -ge [datetime]'2026-10-20' -and $historySyncedThroughTarget)
$coverageState = if ($barCount -ge 8000 -and $dateCoverage) { "PASS: at least 8,000 M5 bars, broker history and SIGNAL_AUDIT reach 2026-10-20" } else { "INCOMPLETE: fewer than 8,000 M5 bars, broker history ends before 2026-10-20, or SIGNAL_AUDIT ends before 2026-10-20; do not treat as performance validation" }
$realTickLines = @($logText -split '\r?\n' | Where-Object { $_ -match '(?i)real tick|real ticks|every tick generation|ticks? (?:are )?absent|discarded.*tick|tick.*discarded' } | Select-Object -Unique -First 40)
$lines += @("", "## Real-tick journal evidence", "", "- Model=4 was requested; this does not prove every tested minute used real ticks.", "- Matching real-tick journal lines: $($realTickLines.Count)")
if ($realTickLines.Count -gt 0) { foreach ($tickLine in $realTickLines) { $lines += ("- " + $tickLine.Trim()) } } else { $lines += "- No matching real-tick status line was found in copied logs; inspect archived terminal/tester logs." }
$historySyncEndText = if ($null -ne $historySyncEnd) { $historySyncEnd.ToString("yyyy-MM-dd") } else { "NOT_FOUND" }
$lastMarketTimeText = if ($null -ne $lastMarketTime) { $lastMarketTime.ToString("yyyy-MM-dd HH:mm:ss") } else { "NOT_FOUND" }
$lines += @("", "## Historical data coverage gate", "", "- $coverageState", "- Coverage floor: 8,000 M5 bars; matched-input control only, not profitability validation.", "- Broker history synchronized through: $historySyncEndText", "- Latest market signal timestamp (SIGNAL_AUDIT): $lastMarketTimeText", "- Requested inclusive dates: 2026-09-01 through 2026-10-20; configured ToDate boundary: 2026-10-21.", "- Compare first/last deal dates in the HTML/logs before interpreting performance.")
$lines | Set-Content -LiteralPath (Join-Path $resultsDir "adx25-model4-ema-control-report-audit.md") -Encoding utf8
$lines | ForEach-Object { Write-Output $_ }
$reportHash = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
Add-Content -LiteralPath (Join-Path $resultsDir "adx25-model4-ema-control-preflight.txt") -Value @("", "Report SHA-256: $reportHash", "Report bytes: $((Get-Item -LiteralPath $reportPath).Length)", "Coverage gate: $coverageState", "UTC verified: $([DateTime]::UtcNow.ToString('o'))") -Encoding utf8
if ($barCount -lt 8000 -or -not $dateCoverage) { throw "Historical Model=4 coverage audit incomplete: bars=$barCount; broker history through=$(if ($null -ne $historySyncEnd) { $historySyncEnd.ToString("yyyy-MM-dd") } else { "NOT_FOUND" }); latest market signal=$(if ($null -ne $lastMarketTime) { $lastMarketTime.ToString("yyyy-MM-dd HH:mm:ss") } else { "NOT_FOUND" })." }
