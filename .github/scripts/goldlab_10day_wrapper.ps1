$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Ten-day out-of-sample robustness check for the short-side candidate.
# This wrapper rewrites only the disposable CI workspace, never the committed runner.
$scriptPath = ".github/scripts/goldlab_mt5_test.ps1"
$eaPath = "trading-lab/gold-xauusd/GoldLabEA.mq5"
$resultsDir = "goldlab-results"
if (!(Test-Path -LiteralPath $scriptPath)) { throw "GoldLab tester script not found." }
if (!(Test-Path -LiteralPath $eaPath)) { throw "GoldLab EA source not found." }

$content = Get-Content -LiteralPath $scriptPath -Raw
$changes = @(
  @("2026-09-01 through 2026-10-19 (short-side-only diagnostic)", "2026-09-01 through 2026-09-10 (10-day short-side-only validation)"),
  @("GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-10-19", "GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-09-10"),
  @("ToDate=2026.10.19", "ToDate=2026.09.10"),
  @("GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19", "GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-09-10")
)
foreach ($change in $changes) {
  if (!$content.Contains($change[0])) { throw "Expected tester marker not found; refusing to run an unverified period: $($change[0])" }
  $content = $content.Replace($change[0], $change[1])
}
Set-Content -LiteralPath $scriptPath -Value $content -Encoding utf8
$verified = Get-Content -LiteralPath $scriptPath -Raw
$checks = @(
  ($verified -match 'FromDate=2026\.09\.01\s*\r?\nToDate=2026\.09\.10'),
  ($verified -match '2026-09-01 through 2026-09-10'),
  ($verified -match 'InpAllowLong=false'),
  ($verified -match 'InpRiskPercent=0\.5'),
  ($verified -match 'InpStopATR=0\.45'),
  ($verified -match 'InpMaxSpreadPoints=100\.0'),
  ($verified -match 'InpMaxADX=40\.0'),
  ($verified -match 'Model=1')
)
if ($checks -contains $false) { throw "Ten-day preflight failed: period, risk, stop, spread, ADX, direction, or OHLC model mismatch." }

New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null
$sourceHash = (Get-FileHash -LiteralPath $eaPath -Algorithm SHA256).Hash.ToLowerInvariant()
$testerHash = (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
@(
  "GoldLab ten-day MT5 Strategy Tester validation",
  "Period: 2026-09-01 through 2026-09-10",
  "Symbol: XAUUSD; timeframe: M5; model: 1-minute OHLC, not real ticks",
  "Risk: 0.50%; stop: 0.45 ATR; target: 2.4 ATR; trail: 1.4 ATR",
  "Max spread: 100 points; ADX 18-40; long entries disabled",
  "EA source SHA-256: $sourceHash",
  "Runner-local tester script SHA-256: $testerHash",
  "UTC preflight: $([DateTime]::UtcNow.ToString('o'))"
) | Set-Content -LiteralPath (Join-Path $resultsDir "ten-day-preflight.txt") -Encoding utf8

& $scriptPath
if ($LASTEXITCODE -ne 0 -or -not $?) { throw "GoldLab Strategy Tester invocation failed." }

$reportPath = Join-Path $resultsDir "GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-09-10.htm"
if (!(Test-Path -LiteralPath $reportPath) -or (Get-Item -LiteralPath $reportPath).Length -le 0) {
  throw "Expected ten-day HTML report is missing/empty; this is an incomplete run, not a zero-trade result."
}
$html = Get-Content -LiteralPath $reportPath -Raw
if ($html -notmatch '2026\.09\.01\s*-\s*2026\.09\.10') { throw "Tester report does not prove the requested ten-day period." }

function Read-TesterMetric([string]$label,[string]$source) {
  $escaped = [regex]::Escape($label)
  $pattern = "(?is)<td[^>]*>\s*$escaped:\s*</td>\s*<td[^>]*>\s*<b>(.*?)</b>"
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
  "Maximal consecutive loss" = Read-TesterMetric "Maximal consecutive loss" $html
}
$lines = @(
  "# GoldLab ten-day report audit",
  "",
  "- Period: 2026-09-01 through 2026-09-10",
  "- Model: 1-minute OHLC; not real ticks",
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
$coverageState = if ($barCount -ge 1200) { "PASS: bar-count floor met" } else { "INCOMPLETE: fewer than 1,200 M5 bars across the ten-day requested period; do not treat performance as validated" }
$lines += @("", "## Data coverage gate", "", "- $coverageState", "- 1,200 is a minimum screening floor, not proof that every session is present.", "- Compare first/last deal dates in the HTML/logs before interpreting performance.")
$lines | Set-Content -LiteralPath (Join-Path $resultsDir "ten-day-report-audit.md") -Encoding utf8
$lines | ForEach-Object { Write-Output $_ }
$reportHash = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
Add-Content -LiteralPath (Join-Path $resultsDir "ten-day-preflight.txt") -Value @("", "Report SHA-256: $reportHash", "Report bytes: $((Get-Item -LiteralPath $reportPath).Length)", "Coverage gate: $coverageState", "UTC verified: $([DateTime]::UtcNow.ToString('o'))") -Encoding utf8
if ($barCount -lt 1200) { throw "Data-coverage gate failed: only $barCount M5 bars for the requested ten-day period." }
