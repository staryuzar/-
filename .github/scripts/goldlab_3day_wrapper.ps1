$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Three-day diagnostic override. This edits only the checked-out runner workspace.
# The committed long-period test script remains unchanged.
$scriptPath = ".github/scripts/goldlab_mt5_test.ps1"
$eaPath = "trading-lab/gold-xauusd/GoldLabEA.mq5"
$resultsDir = "goldlab-results"
if (!(Test-Path -LiteralPath $scriptPath)) { throw "GoldLab tester script not found." }
if (!(Test-Path -LiteralPath $eaPath)) { throw "GoldLab EA source not found." }

$content = Get-Content -LiteralPath $scriptPath -Raw
$changes = @(
  @("2026-09-01 through 2026-10-19 (short-side-only diagnostic)", "2026-09-01 through 2026-09-03 (3-day short-side-only diagnostic)"),
  @("GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-10-19", "GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-09-03"),
  @("ToDate=2026.10.19", "ToDate=2026.09.03"),
  @("GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19", "GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-09-03")
)
foreach ($change in $changes) {
  if (!$content.Contains($change[0])) { throw "Expected tester marker not found; refusing to run an unverified date range: $($change[0])" }
  $content = $content.Replace($change[0], $change[1])
}

Set-Content -LiteralPath $scriptPath -Value $content -Encoding utf8
$verified = Get-Content -LiteralPath $scriptPath -Raw
$checks = @(
  ($verified -match 'FromDate=2026\.09\.01\s*\r?\nToDate=2026\.09\.03'),
  ($verified -match '2026-09-01 through 2026-09-03'),
  ($verified -match 'InpAllowLong=false'),
  ($verified -match 'InpRiskPercent=0\.5'),
  ($verified -match 'InpStopATR=0\.45'),
  ($verified -match 'InpMaxSpreadPoints=100\.0'),
  ($verified -match 'InpMaxADX=40\.0'),
  ($verified -match 'Model=1')
)
if ($checks -contains $false) { throw "Three-day tester preflight failed; dates, risk, stop, spread, ADX, direction, or model does not match the intended experiment." }

New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null
$sourceHash = (Get-FileHash -LiteralPath $eaPath -Algorithm SHA256).Hash.ToLowerInvariant()
$testerHash = (Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()
$preflight = @(
  "GoldLab three-day Strategy Tester preflight",
  "Period: 2026-09-01 through 2026-09-03 (inclusive)",
  "Symbol: XAUUSD; timeframe: M5; model: 1-minute OHLC (not real ticks)",
  "Risk: 0.50%; stop: 0.45 ATR; max spread: 100 points; max ADX: 40; long entries disabled",
  "EA source SHA-256: $sourceHash",
  "Runner-local tester script SHA-256 after 3-day override: $testerHash",
  "UTC preflight: $([DateTime]::UtcNow.ToString('o'))"
)
$preflight | Set-Content -LiteralPath (Join-Path $resultsDir "three-day-preflight.txt") -Encoding utf8
Write-Output ($preflight -join "`n")

& $scriptPath
if (-not $?) { throw "GoldLab MT5 tester script failed." }

$reportPath = Join-Path $resultsDir "GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-09-03.htm"
if (!(Test-Path -LiteralPath $reportPath) -or (Get-Item -LiteralPath $reportPath).Length -le 0) {
  throw "Three-day Strategy Tester HTML report is missing/empty. This is an incomplete run, not a zero-trade result."
}
$reportHash = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
$reportBytes = (Get-Item -LiteralPath $reportPath).Length
@(
  "",
  "Tester report SHA-256: $reportHash",
  "Tester report bytes: $reportBytes",
  "UTC report verified: $([DateTime]::UtcNow.ToString('o'))",
  "Evidence note: report existence proves a report was generated; trade count/performance must be read from report and journal, not inferred from exit code."
) | Add-Content -LiteralPath (Join-Path $resultsDir "three-day-preflight.txt") -Encoding utf8
Write-Output "PASS: expected non-empty three-day HTML report exists; SHA-256=$reportHash; bytes=$reportBytes"
