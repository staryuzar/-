[CmdletBinding()]
param([ValidateSet("0.0","0.6")][string]$GapThreshold = "0.6")
$gapTag = if ($GapThreshold -eq "0.0") { "off" } else { "on" }

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Paired EMA-gap hypothesis: pin the exact v1.006 baseline source, inject a zero-default ATR-normalized EMA-gap input/gate, and compare OFF (0.0) against ON (0.6).
# Entry signals are filtered, but raw longSetup/shortSetup remain ungated for managing and closing opposing positions.
$baselineSourceCommit = "fed7b047454ff11c2b266fc1d1af1c0c55ede680"
$baselineSourceSha256 = "009dbe1832be4df6f51134815900ca565994349432dad02e2d484356ced8195f"
$scriptPath = ".github/scripts/goldlab_mt5_test.ps1"
$eaPath = "trading-lab/gold-xauusd/GoldLabEA.mq5"
$resultsDir = "goldlab-results"
if (!(Test-Path -LiteralPath $scriptPath)) { throw "GoldLab tester script not found." }
if (!(Test-Path -LiteralPath $eaPath)) { throw "GoldLab EA source not found." }

$baselineSourceUrl = "https://raw.githubusercontent.com/staryuzar/-/$baselineSourceCommit/trading-lab/gold-xauusd/GoldLabEA.mq5"
$baselineSourceTemp = Join-Path $env:RUNNER_TEMP "GoldLabEA-baseline-v1.006.mq5"
Invoke-WebRequest -Uri $baselineSourceUrl -OutFile $baselineSourceTemp -TimeoutSec 60
$downloadHash = (Get-FileHash -LiteralPath $baselineSourceTemp -Algorithm SHA256).Hash.ToLowerInvariant()
if ($downloadHash -ne $baselineSourceSha256) { throw "Immutable raw baseline EA source hash mismatch; refusing an unmatched EMA-gap comparison. Actual=$downloadHash" }
Copy-Item -LiteralPath $baselineSourceTemp -Destination $eaPath -Force
$workspaceSourceHash = (Get-FileHash -LiteralPath $eaPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($workspaceSourceHash -ne $baselineSourceSha256) { throw "Baseline EA source copy hash mismatch; refusing to test." }

# Add an experimental EMA-gap gate to this disposable EA source only.
$sourceText = Get-Content -LiteralPath $eaPath -Raw
$inputMarker = "input bool             InpRequireFastEMARejection = false;"
if (!$sourceText.Contains($inputMarker)) { throw "Pinned EA source input marker missing." }
# The OFF control explicitly sets 0.0. Keep the compiled default at 0.1 so MT5 HTML must print 0.0 instead of omitting a default-valued parameter.
$sourceText = $sourceText.Replace($inputMarker, $inputMarker + [Environment]::NewLine + "input double           InpMinEMAGapATR = 0.1;")
$validationMarker = "InpMaxSpreadPoints<=0.0)"
if (!$sourceText.Contains($validationMarker)) { throw "EA parameter-validation marker missing." }
$sourceText = $sourceText.Replace($validationMarker, "InpMaxSpreadPoints<=0.0 || InpMinEMAGapATR<0.0)")
$longSignalMarker = "bool longSignal=(InpAllowLong && longSetup);"
if (!$sourceText.Contains($longSignalMarker)) { throw "EA long-signal marker missing." }
$sourceText = $sourceText.Replace($longSignalMarker, "double emaGapATR=(atr>0.0 ? MathAbs(fast1-slow1)/atr : 0.0);" + [Environment]::NewLine + "   bool entryGapAllowed=(InpMinEMAGapATR<=0.0 || (atr>0.0 && emaGapATR>=InpMinEMAGapATR));" + [Environment]::NewLine + "   bool longSignal=(InpAllowLong && longSetup && entryGapAllowed);")
$shortPattern = 'bool shortSignal=\(candleShortAllowed[\s\S]*?adx<=InpMaxADX\);'
$shortMatch = [regex]::Match($sourceText, $shortPattern)
if (!$shortMatch.Success) { throw "EA short-signal marker missing." }
$shortSetupCode = $shortMatch.Value.Replace("bool shortSignal=", "bool shortSetup=")
if ($shortSetupCode -eq $shortMatch.Value) { throw "EA short setup isolation failed." }
$sourceText = $sourceText.Replace($shortMatch.Value, $shortSetupCode + [Environment]::NewLine + "   bool shortSignal=(shortSetup && entryGapAllowed);")
$manageMarker = "ManagePositions(atr,(spreadAllowed ? longSetup : false),(spreadAllowed ? shortSignal : false));"
if (!$sourceText.Contains($manageMarker)) { throw "Position-management marker missing." }
$sourceText = $sourceText.Replace($manageMarker, "ManagePositions(atr,(spreadAllowed ? longSetup : false),(spreadAllowed ? shortSetup : false));")
$auditMarker = '";ADX="+DoubleToString(adx,2)+";ATR="+DoubleToString(atr,_Digits)+'
if (!$sourceText.Contains($auditMarker)) { throw "EA SIGNAL_AUDIT marker missing." }
$sourceText = $sourceText.Replace($auditMarker, '";ADX="+DoubleToString(adx,2)+";ATR="+DoubleToString(atr,_Digits)+' + [Environment]::NewLine + '      ";ema_gap_atr="+DoubleToString(emaGapATR,3)+";ema_gap_min="+DoubleToString(InpMinEMAGapATR,2)+";entry_gap_allowed="+(entryGapAllowed ? "1":"0")+";short_setup="+(shortSetup ? "1":"0")+')
$sourceText = $sourceText.Replace('Research candidate v1.006', 'Research candidate v1.010 EMA-gap test')
if (!$sourceText.Contains("InpMinEMAGapATR = 0.1;") -or !$sourceText.Contains("entryGapAllowed") -or !$sourceText.Contains("ema_gap_atr") -or !$sourceText.Contains("shortSetup") -or !$sourceText.Contains("v1.010 EMA-gap test")) { throw "EMA-gap source injection verification failed: default sentinel, gate, audit telemetry, or position-management isolation missing." }
[System.IO.File]::WriteAllText($eaPath, $sourceText, [System.Text.UTF8Encoding]::new($false))

$content = Get-Content -LiteralPath $scriptPath -Raw
$longSetMarker = "InpAllowLong=false||true||0||true||N"
if (!$content.Contains($longSetMarker)) { throw "Long-entry SET marker missing; short-only mode cannot be verified." }
$longHtmlCheckMarker = "InpAllowLong=false</b>"
if (!$content.Contains($longHtmlCheckMarker)) { throw "Long-entry HTML check marker missing; short-only mode cannot be verified." }


$parameterChanges = @(
  @("InpMinADX=18.0||18.0||1.0||18.0||N", "InpMinADX=23.0||23.0||1.0||23.0||N"),
  @("FromDate=2026.09.01", "FromDate=2026.08.04"),
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
  @("2026-09-01 through 2026-10-19 (short-side-only diagnostic)", "2026-08-04 through 2026-10-20 (Model=4 minADX23 short-only control; ADX 23-25; EMA20 rejection ON; candle-direction ON; long entries disabled)"),
  @("model 1 (1-minute OHLC diagnostic; not real-tick validation)", "model 4 (Every tick based on real ticks; minimum-ADX23 sensitivity diagnostic)"),
  @("OHLC only, not production validation.", "short-only matched control with strict tick coverage gate; no live orders."),
  @("GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-10-19", "GoldLab_adx25_min23_shortonly_candle_true_2026-08-04_to-2026-10-20"),
  @("ToDate=2026.10.19", "ToDate=2026.10.21"),
  @("GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19", "GoldLab_adx25_min23_shortonly_candle_true_2026-08-04_to-2026-10-20")
)
foreach ($change in $parameterChanges) {
  if (!$content.Contains($change[0])) { throw "Expected ADX27 parameter marker missing: $($change[0])" }
  $content = $content.Replace($change[0], $change[1])
}
$setCsvMarker = "InpWriteTradeCSV=true||false||0||true||N"
if (!$content.Contains($setCsvMarker)) { throw "CSV SET marker missing; cannot add candle-direction input safely." }
$content = $content.Replace($setCsvMarker, $setCsvMarker + [Environment]::NewLine + "InpRequireSignalCandleDirection=true||true||0||true||N" + [Environment]::NewLine + "InpRequireFastEMARejection=true||false||0||false||N" + [Environment]::NewLine + "InpMinEMAGapATR=$GapThreshold||$GapThreshold||0.1||$GapThreshold||N")
$confirmationCheck = '($html -match ''(?is)InpAllowLong=false</b>''))'
if (!$content.Contains($confirmationCheck)) { throw "Tester input verification marker missing." }
$content = $content.Replace($confirmationCheck, '($html -match ''(?is)InpAllowLong=false</b>'') -and ($html -match ''(?is)InpMinADX=23(?:\.0+)?</b>'') -and ($html -match ''(?is)InpMaxADX=25(?:\.0+)?</b>'') -and ($html -match ''(?is)InpRequireSignalCandleDirection=true</b>'') -and ($html -match ''(?is)InpRequireFastEMARejection=true</b>''))')
$legacyPass = "Input verification: PASS (risk=0.5, stop=0.45 ATR, max spread=100, max ADX=25, long entries disabled)"
if (!$content.Contains($legacyPass)) { throw "Bidirectional input summary marker missing; refusing a misleading run log." }
$content = $content.Replace($legacyPass, "Input verification: PASS (risk=0.5, stop=0.45 ATR, EMA gap threshold=$GapThreshold ATR, max spread=100, min ADX=23, max ADX=25, long entries disabled, candle-direction confirmation=true, fast EMA rejection=true)")
$content = $content.Replace("max ADX=40", "max ADX=25")
$content = $content.Replace("ADX 18-40", "ADX 18-25")
foreach ($change in $changes) {
  if (!$content.Contains($change[0])) { throw "Expected tester marker not found; refusing to run an unverified period: $($change[0])" }
  $content = $content.Replace($change[0], $change[1])
}
$legacyExperiment = "long entries disabled for one-sided diagnostic. short-only matched control with strict tick coverage gate; no live orders."
if (!$content.Contains($legacyExperiment)) { throw "Bidirectional parameter experiment label marker missing." }
$content = $content.Replace($legacyExperiment, "long entries disabled for short-only diagnostic. EMA20 rejection=true, candle-direction=true; strict Model=4 data gate; no live orders.")
$legacyMinLabel = "max ADX=25, long entries disabled for short-only diagnostic."
if (!$content.Contains($legacyMinLabel)) { throw "Minimum-ADX sensitivity label marker missing." }
$content = $content.Replace($legacyMinLabel, "min ADX=23, max ADX=25, long entries disabled for short-only diagnostic.")
$content = $content.Replace("ADX 18-25", "ADX 23-25")
$content = $content.Replace("max ADX=25, long entries disabled, candle-direction confirmation=true", "min ADX=23, max ADX=25, long entries disabled, candle-direction confirmation=true")

# Short-only mode keeps the original disabled-long summary.
# Short-only mode keeps the base runner input description.
# Short-only mode does not rewrite the parameter description.
# Keep SL=0.45 ATR and all other baseline inputs unchanged; vary only InpMinEMAGapATR.
$content = $content.Replace("GoldLab_adx25_min23_shortonly_candle_true_2026-08-04_to-2026-10-20", "GoldLab_advisor_emagap_$($gapTag)_2026-08-04_to-2026-10-20")
$content = $content.Replace("goldlab_adx25_min23_shortonly_candle_true_2026-08-04_to-2026-10-20", "goldlab_advisor_emagap_$($gapTag)_2026-08-04_to-2026-10-20")
$content = $content.Replace("Model=4 minADX23 short-only control; ADX 23-25; EMA20 rejection ON; candle-direction ON; long entries disabled", "Model=4 short-only EMA-gap diagnostic; threshold=$GapThreshold ATR; SL=0.45 ATR; ADX 23-25; EMA20 rejection ON; candle-direction ON")
$content = $content.Replace("short-only matched control with strict tick coverage gate; no live orders.", "short-only EMA-gap experiment with strict Model=4 tick coverage gate; no live orders.")
$content = $content.Replace("short-only candle-direction ON control report audit", "short-only EMA-gap report audit ($gapTag)")
$content = $content.Replace("minADX23 candle-direction cross-period diagnostic period", "EMA-gap diagnostic period")
$content = $content.Replace("candle-direction EMA-gap data gate failed", "EMA-gap diagnostic data gate failed")
Set-Content -LiteralPath $scriptPath -Value $content -Encoding utf8
$verified = Get-Content -LiteralPath $scriptPath -Raw
$checks = @(
  ($verified -match 'FromDate=2026\.08\.04\s*\r?\nToDate=2026\.10\.21'),
  ($verified -match '2026-08-04 through 2026-10-20'),
  ($verified -match 'InpAllowLong=false'),
  ($verified -match 'InpRiskPercent=0\.5'),
  ($verified -match 'InpStopATR=0\.45'),
  ($verified -match ('InpMinEMAGapATR=' + [regex]::Escape($GapThreshold) + '\|\|' + [regex]::Escape($GapThreshold) + '\|\|0\.1\|\|' + [regex]::Escape($GapThreshold) + '\|\|N')),
  ($verified -match 'InpMaxSpreadPoints=100\.0'),
  ($verified -match 'InpMinADX=23\.0'),
  ($verified -match 'InpMaxADX=25\.0'),
  ($verified -match 'InpRequireSignalCandleDirection=true'),
  ($verified -match 'InpRequireFastEMARejection=true'),
  ($verified -match 'Model=4')
)
if ($checks -contains $false) { throw "Historical Model=4 preflight failed: date range, risk, stop, spread, ADX, direction, or tester model mismatch." }

New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null
$sourceHash = (Get-FileHash -LiteralPath $eaPath -Algorithm SHA256).Hash.ToLowerInvariant()
$testerHash = (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
@(
  "GoldLab EMA-gap diagnostic on baseline EA v1.006-derived source; threshold=$GapThreshold ATR ($gapTag; 2026-08-04 to 2026-10-20)",
  "Period: 2026-08-04 through 2026-10-20",
  "Symbol: XAUUSD; timeframe: M5; model: Model=4, Every tick based on real ticks (actual start date is in the journal)",
  "Risk: 0.50%; stop: 0.45 ATR; gap threshold: $GapThreshold ATR; target: 2.4 ATR; trail: 1.4 ATR",
  "Max spread: 100 points; ADX 23-25; EMA20 rejection ON; candle-direction ON; EMA-gap diagnostic; threshold=$GapThreshold",
  "EA source SHA-256: $sourceHash (derived from baseline v1.006; raw baseline SHA-256=$baselineSourceSha256; commit $baselineSourceCommit)",
  "Runner-local tester script SHA-256: $testerHash",
  "UTC preflight: $([DateTime]::UtcNow.ToString('o'))"
) | Set-Content -LiteralPath (Join-Path $resultsDir "advisor-emagap-$($gapTag)-preflight.txt") -Encoding utf8

& $scriptPath
if (-not $?) { throw "GoldLab Strategy Tester invocation failed." }

# Regression check: a fresh audit CSV must start with the documented field names.
# This must happen before CSV parsing so the parser cannot hide a missing header
# by imposing its own -Header column list.
$tradeAuditDir = Join-Path $resultsDir "trade-audit"
$tradeAuditFiles = @(Get-ChildItem -LiteralPath $tradeAuditDir -Filter "GoldLab_trade_audit-*.csv" -File -ErrorAction SilentlyContinue)
if ($tradeAuditFiles.Count -eq 0) { throw "CSV header regression gate failed: no trade-audit CSV was produced." }
$expectedCsvHeader = "deal,time,symbol,entry,type,volume,price,profit,commission,swap,reason,position_id"
foreach ($auditFile in $tradeAuditFiles) {
  $firstCsvLine = (Get-Content -LiteralPath $auditFile.FullName -TotalCount 1 -ErrorAction Stop).TrimStart([char]0xFEFF)
  if ($firstCsvLine.Trim() -ne $expectedCsvHeader) {
    throw "CSV header regression gate failed: $($auditFile.Name) does not start with the exact expected column header."
  }
}
"Trade-audit CSV header verification: PASS ($($tradeAuditFiles.Count) file(s))." | Add-Content -LiteralPath (Join-Path $resultsDir "run-summary.txt") -Encoding utf8

$reportPath = Join-Path $resultsDir "GoldLab_advisor_emagap_$($gapTag)_2026-08-04_to-2026-10-20.htm"
if (!(Test-Path -LiteralPath $reportPath) -or (Get-Item -LiteralPath $reportPath).Length -le 0) {
  throw "Expected historical Model=4 HTML report is missing/empty; this is an incomplete run, not a zero-trade result."
}
$html = Get-Content -LiteralPath $reportPath -Raw
if ($html -notmatch '2026\.08\.04\s*-\s*2026\.10\.21') { throw "Tester report does not prove the requested EMA-gap diagnostic period." }
$gapHtmlRegex = if ($GapThreshold -eq "0.0") { 'InpMinEMAGapATR=0(?:\.0+)?</b>' } else { 'InpMinEMAGapATR=0\.6(?:0+)?</b>' }
if ($html -notmatch "(?is)$gapHtmlRegex") { throw "Tester report does not confirm InpMinEMAGapATR=$GapThreshold; reject comparison." }

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
if ($GapThreshold -eq "0.0") {
  $controlNet=0.0; $controlPF=0.0; $controlTrades=0; $controlDD=0.0
  $netOk=[double]::TryParse([string]$metrics["Total Net Profit"],[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$controlNet)
  $pfOk=[double]::TryParse([string]$metrics["Profit Factor"],[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$controlPF)
  $tradeMatch=[regex]::Match([string]$metrics["Total Trades"],'\d+')
  if ($tradeMatch.Success) { $controlTrades=[int]$tradeMatch.Value }
  $ddMatch=[regex]::Match([string]$metrics["Equity Drawdown Maximal"],'^\s*(\d+(?:\.\d+)?)')
  $ddOk=$false
  if ($ddMatch.Success) { $ddOk=[double]::TryParse($ddMatch.Groups[1].Value,[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$controlDD) }
  if (!$netOk -or !$pfOk -or !$ddOk -or [math]::Abs($controlNet-26.64) -gt 0.05 -or [math]::Abs($controlPF-1.59) -gt 0.02 -or $controlTrades -ne 35 -or [math]::Abs($controlDD-18.98) -gt 0.15) {
    throw "EMA-gap OFF control failed to reproduce the baseline: net=$($metrics['Total Net Profit']); PF=$($metrics['Profit Factor']); trades=$($metrics['Total Trades']); DD=$($metrics['Equity Drawdown Maximal']). Filter ON must not run on a mismatched control."
  }
  "EMA-GAP OFF CONTROL MATCH: baseline net=$controlNet; PF=$controlPF; trades=$controlTrades; max equity DD=$controlDD." | Add-Content -LiteralPath (Join-Path $resultsDir "run-summary.txt") -Encoding utf8
}
$lines = @(
  "# GoldLab ADX25 minADX23 short-only EMA-gap report audit ($gapTag)",
  "",
  "- Period: 2026-08-04 through 2026-10-20; min ADX=23; max ADX=25; stop=0.45 ATR; EMA gap threshold=$GapThreshold ATR; EMA20 rejection=true; candle-direction=true; short-only",
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
$historyQualityFull = ($metrics["History Quality"] -match '^\s*100%')
$realTickStartMatches = [regex]::Matches($logText, '(?i)real ticks begin from (\d{4}\.\d{2}\.\d{2})')
$realTickStart = $null
foreach ($tickStartMatch in $realTickStartMatches) {
  try {
    $tickStartCandidate = [datetime]::ParseExact($tickStartMatch.Groups[1].Value, 'yyyy.MM.dd', [Globalization.CultureInfo]::InvariantCulture)
    if ($null -eq $realTickStart -or $tickStartCandidate -lt $realTickStart) { $realTickStart = $tickStartCandidate }
  } catch {}
}
$realTickCoverage = ($null -ne $realTickStart -and $realTickStart.Date -le [datetime]'2026-08-04')
$badTickLines = @($logText -split '\r?\n' | Where-Object { $_ -match '(?i)(real ticks? (?:are )?(?:absent|missing)|real ticks? discarded|tick prices?.{0,100}(?:mismatch|not matched)|tick volumes?.{0,100}(?:mismatch|not matched)|every tick generation (?:was )?used)' } | Select-Object -Unique -First 100)
$realTickStartText = if ($null -ne $realTickStart) { $realTickStart.ToString('yyyy-MM-dd') } else { 'NOT_FOUND' }
$strictRealTickCoverage = ($historyQualityFull -and $realTickCoverage -and $badTickLines.Count -eq 0)

$coverageState = if ($barCount -ge 12000 -and $dateCoverage -and $strictRealTickCoverage) { "PASS: at least 12,000 M5 bars; broker and SIGNAL_AUDIT reach 2026-10-20; History Quality 100%; real ticks begin on/before 2026-08-04; no identified fallback/rejection messages" } else { "INCOMPLETE/REJECTED: combined-window bar/date coverage, History Quality, real-tick start date, or journal fallback/rejection gate failed; no performance acceptance" }
$realTickLines = @($logText -split '\r?\n' | Where-Object { $_ -match '(?i)real tick|real ticks|every tick generation|ticks? (?:are )?absent|discarded.*tick|tick.*discarded' } | Select-Object -Unique -First 40)
$lines += @("", "## Real-tick journal evidence", "", "- Model=4 was requested; this does not prove every tested minute used real ticks.", "- Matching real-tick journal lines: $($realTickLines.Count)")
if ($realTickLines.Count -gt 0) { foreach ($tickLine in $realTickLines) { $lines += ("- " + $tickLine.Trim()) } } else { $lines += "- No matching real-tick status line was found in copied logs; inspect archived terminal/tester logs." }
$historySyncEndText = if ($null -ne $historySyncEnd) { $historySyncEnd.ToString("yyyy-MM-dd") } else { "NOT_FOUND" }
$lastMarketTimeText = if ($null -ne $lastMarketTime) { $lastMarketTime.ToString("yyyy-MM-dd HH:mm:ss") } else { "NOT_FOUND" }
$lines += @("", "## Strict historical data coverage gate", "", "- $coverageState", "- Coverage floor: 12,000 M5 bars; diagnostic only, not strategy acceptance.", "- History Quality: $($metrics['History Quality'])", "- Broker history synchronized through: $historySyncEndText", "- Latest market signal timestamp (SIGNAL_AUDIT): $lastMarketTimeText", "- Earliest real-tick start date: $realTickStartText", "- Lines indicating missing/discarded/mismatched real ticks or generated-tick fallback: $($badTickLines.Count)", "- Requested inclusive dates: 2026-08-04 through 2026-10-20; configured ToDate boundary: 2026-10-21.")
if ($badTickLines.Count -gt 0) { $lines += @("", "## Disqualifying real-tick journal lines", ""); foreach ($badTickLine in $badTickLines) { $lines += ("- " + $badTickLine.Trim()) } }

# Attribute closed-position net results by entry side using the MT5 deal CSVs.
# Each position_id is counted once; net is the sum of profit, commission and swap across its deals.
$csvHeaders = @("deal","time","symbol","entry","type","volume","price","profit","commission","swap","reason","position_id")
$positionTrades = @{}
$tradeAuditDir = Join-Path $resultsDir "trade-audit"
$tradeAuditFiles = @()
if (Test-Path -LiteralPath $tradeAuditDir) {
  $tradeAuditFiles = @(Get-ChildItem -LiteralPath $tradeAuditDir -Filter "*.csv" -File -ErrorAction SilentlyContinue)
}
foreach ($csvFile in $tradeAuditFiles) {
  $csvLines = @(Get-Content -LiteralPath $csvFile.FullName -ErrorAction SilentlyContinue | Where-Object { $_.Trim().Length -gt 0 })
  if ($csvLines.Count -eq 0) { continue }
  if ($csvLines[0] -match '^\s*"?deal"?\s*,') { $csvLines = @($csvLines | Select-Object -Skip 1) }
  foreach ($dealRow in ($csvLines | ConvertFrom-Csv -Header $csvHeaders)) {
    $positionId = ([string]$dealRow.position_id).Trim()
    if ([string]::IsNullOrWhiteSpace($positionId)) { continue }
    if (!$positionTrades.ContainsKey($positionId)) {
      $positionTrades[$positionId] = [ordered]@{ Net=0.0; Side="UNKNOWN"; EntryTime=""; DealRows=0 }
    }
    $positionRecord = $positionTrades[$positionId]
    foreach ($field in @("profit","commission","swap")) {
      $amount = 0.0
      if ([double]::TryParse([string]$dealRow.$field,[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$amount)) {
        $positionRecord.Net += $amount
      }
    }
    $positionRecord.DealRows++
    if ([string]$dealRow.entry -eq "0" -and [string]$dealRow.type -in @("0","1")) {
      $positionRecord.Side = if ([string]$dealRow.type -eq "0") { "LONG" } else { "SHORT" }
      $positionRecord.EntryTime = [string]$dealRow.time
    }
  }
}
$sideSummary = [ordered]@{}
foreach ($side in @("LONG","SHORT","UNKNOWN")) {
  $sideRecords = @($positionTrades.GetEnumerator() | Where-Object { $_.Value.Side -eq $side })
  if ($sideRecords.Count -eq 0) { continue }
  $stats = [ordered]@{ Trades=0; Net=0.0; Wins=0; Losses=0; Breakeven=0 }
  foreach ($sideRecord in $sideRecords) {
    $tradeNet = [double]$sideRecord.Value.Net
    $stats.Trades++
    $stats.Net += $tradeNet
    if ($tradeNet -gt 0.000001) { $stats.Wins++ }
    elseif ($tradeNet -lt -0.000001) { $stats.Losses++ }
    else { $stats.Breakeven++ }
  }
  $sideSummary[$side] = $stats
}
$lines += @("", "## MT5 trade CSV attribution by entry direction", "", "- CSV files found: $($tradeAuditFiles.Count)", "- Position IDs grouped: $($positionTrades.Count)", "- Side convention: opening deal type 0=BUY/LONG; type 1=SELL/SHORT; grouped net includes profit, commission and swap.")
if ($sideSummary.Count -eq 0) {
  $lines += "- Directional attribution unavailable: no position-level deal rows could be parsed."
} else {
  foreach ($side in $sideSummary.Keys) {
    $stats = $sideSummary[$side]
    $lines += ("- {0}: trades={1}; net={2:N2} USD; wins={3}; losses={4}; breakeven={5}" -f $side,$stats.Trades,$stats.Net,$stats.Wins,$stats.Losses,$stats.Breakeven)
  }
  $csvNet = 0.0
  foreach ($side in $sideSummary.Keys) { $csvNet += [double]$sideSummary[$side].Net }
  $reportNet = 0.0
  $reportNetFound = [double]::TryParse([string]$metrics["Total Net Profit"],[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$reportNet)
  if ($reportNetFound) {
    $parityDelta = [math]::Abs($csvNet-$reportNet)
    $lines += ("- CSV net total: {0:N2} USD; Strategy Tester net total: {1:N2} USD; absolute difference: {2:N2} USD; parity={3}" -f $csvNet,$reportNet,$parityDelta,($(if ($parityDelta -le 0.10) { "PASS" } else { "REVIEW" })))
  } else {
    $lines += "- CSV/HTML net parity: REVIEW (Strategy Tester net value not parseable)."
  }
}

$lines | Set-Content -LiteralPath (Join-Path $resultsDir "advisor-emagap-$($gapTag)-report-audit.md") -Encoding utf8
$lines | ForEach-Object { Write-Output $_ }
$reportHash = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
Add-Content -LiteralPath (Join-Path $resultsDir "advisor-emagap-$($gapTag)-preflight.txt") -Value @("", "Report SHA-256: $reportHash", "Report bytes: $((Get-Item -LiteralPath $reportPath).Length)", "Coverage gate: $coverageState", "UTC verified: $([DateTime]::UtcNow.ToString('o'))") -Encoding utf8
if ($barCount -lt 12000 -or -not $dateCoverage -or -not $strictRealTickCoverage) { throw "Candle-direction EMA-gap data gate failed: bars=$barCount; history quality=$($metrics['History Quality']); broker history through=$(if ($null -ne $historySyncEnd) { $historySyncEnd.ToString('yyyy-MM-dd') } else { 'NOT_FOUND' }); latest market signal=$(if ($null -ne $lastMarketTime) { $lastMarketTime.ToString('yyyy-MM-dd HH:mm:ss') } else { 'NOT_FOUND' }); real ticks begin=$realTickStartText; bad journal lines=$($badTickLines.Count)." }
