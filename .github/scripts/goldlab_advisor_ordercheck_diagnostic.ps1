$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$runnerPath = ".github/scripts/goldlab_mt5_test.ps1"
$eaPath = "trading-lab/gold-xauusd/GoldLabEA.mq5"
if (!(Test-Path -LiteralPath $runnerPath)) { throw "Generic MT5 runner is missing." }
if (!(Test-Path -LiteralPath $eaPath)) { throw "GoldLabEA source is missing." }

$source = Get-Content -LiteralPath $eaPath -Raw
if ($source -notmatch '(?m)^#property version\s+"1\.011"' -or
    $source -notmatch 'PreflightTradeRequest\(request,"open"\)' -or
    $source -notmatch 'PreflightTradeRequest\(request,"close"\)' -or
    $source -notmatch 'PreflightTradeRequest\(request,"modify-sltp"\)' -or
    $source -notmatch 'ORDER_CHECK_SUMMARY') {
  throw "EA source does not contain the intended v1.010 OrderCheck patch."
}
$sourceHash = (Get-FileHash -LiteralPath $eaPath -Algorithm SHA256).Hash.ToLowerInvariant()
$content = Get-Content -LiteralPath $runnerPath -Raw

$writeCsvMarker = "InpWriteTradeCSV=true||false||0||true||N"
$writeCsvReplacement = $writeCsvMarker + [Environment]::NewLine + "InpRequireSignalCandleDirection=true||true||0||true||N" + [Environment]::NewLine + "InpRequireFastEMARejection=true||false||0||false||N"
$replacements = @(
  @("2026-09-01 through 2026-10-19 (short-side-only diagnostic)", "2026-08-04 through 2026-10-20 (OrderCheck execution-safety diagnostic; short-only)"),
  @("model 1 (1-minute OHLC diagnostic; not real-tick validation)", "model 4 (Every tick based on real ticks; OrderCheck diagnostic)"),
  @("Parameter experiment: risk=0.50%, stop=0.45 ATR, max spread=100 points, max ADX=40, long entries disabled for one-sided diagnostic. OHLC only, not production validation.", "Parameter experiment: risk=0.50%, stop=0.45 ATR, max spread=100 points, ADX=23-25, long entries disabled, candle-direction and EMA rejection enabled. Real-tick demo/tester diagnostic only."),
  @("GoldLabShortOnlyADX40Stop045.set", "GoldLabADX25Min23OrderCheckStop045.set"),
  @("InpMinADX=18.0||18.0||1.0||18.0||N", "InpMinADX=23.0||23.0||1.0||23.0||N"),
  @("InpMaxADX=40.0||40.0||1.0||40.0||N", "InpMaxADX=25.0||25.0||1.0||25.0||N"),
  @("InpWriteTradeCSV=true||false||0||true||N", $writeCsvReplacement),
  @("ADX 18-40, long entries disabled", "ADX 23-25, long entries disabled, candle direction=true, fast EMA rejection=true"),
  @("GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-10-19", "GoldLab_ordercheck_adx25_min23_stop045_2026-08-04_to_2026-10-20"),
  @("GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19.htm", "GoldLab_ordercheck_adx25_min23_stop045_2026-08-04_to-2026-10-20.htm")
)
foreach ($pair in $replacements) {
  if (!$content.Contains($pair[0])) { throw "Exact generic-runner replacement marker is missing: $($pair[0])" }
  $content = $content.Replace($pair[0], $pair[1])
}
$content = [regex]::Replace($content, '(?m)^Model=1\r?$', 'Model=4')
$content = [regex]::Replace($content, '(?m)^FromDate=2026\.09\.01\r?$', 'FromDate=2026.08.04')
$content = [regex]::Replace($content, '(?m)^ToDate=2026\.10\.19\r?$', 'ToDate=2026.10.21')
$oldMax = '($html -match ''(?is)InpMaxADX=40(?:\.0+)?</b>'')'
$newChecks = '($html -match ''(?is)InpMinADX=23(?:\.0+)?</b>'') -and ($html -match ''(?is)InpMaxADX=25(?:\.0+)?</b>'') -and ($html -match ''(?is)InpRequireSignalCandleDirection=true</b>'') -and ($html -match ''(?is)InpRequireFastEMARejection=true</b>'')'
if (!$content.Contains($oldMax)) { throw "Parameter verification source marker not found." }
$content = $content.Replace($oldMax, $newChecks)
$content = $content.Replace("Input verification: PASS (risk=0.5, stop=0.45 ATR, max spread=100, max ADX=40, long entries disabled)", "Input verification: PASS (risk=0.5, stop=0.45 ATR, max spread=100, ADX 23-25, long entries disabled, candle direction=true, fast EMA rejection=true)")

$checks = @(
  ($content -match 'InpMinADX=23\.0'),
  ($content -match 'InpMaxADX=25\.0'),
  ($content -match 'InpRequireSignalCandleDirection=true'),
  ($content -match 'InpRequireFastEMARejection=true'),
  ($content -match '(?m)^Model=4\r?$'),
  ($content -match '(?m)^FromDate=2026\.08\.04\r?$'),
  ($content -match '(?m)^ToDate=2026\.10\.21\r?$'),
  ($content -match 'GoldLab_ordercheck_adx25_min23_stop045_2026-08-04_to-2026-10-20'),
  ($content -match 'OrderCheck diagnostic')
)
if ($checks -contains $false) {
  $checkNames = @("InpMinADX=23.0","InpMaxADX=25.0","InpRequireSignalCandleDirection=true","InpRequireFastEMARejection=true","Model=4","FromDate=2026.08.04","ToDate=2026.10.21","report basename","OrderCheck diagnostic label")
  for ($i=0; $i -lt $checks.Count; $i++) { Write-Host ("PRECHECK " + $checkNames[$i] + "=" + [bool]$checks[$i]) }
  throw "OrderCheck diagnostic runner preflight failed; see named PRECHECK results above."
}
$runtimeRunner = Join-Path $env:RUNNER_TEMP "goldlab_mt5_ordercheck_runner.ps1"
[System.IO.File]::WriteAllText($runtimeRunner, $content, [System.Text.UTF8Encoding]::new($false))
@(
  "OrderCheck execution-safety diagnostic",
  "EA source SHA-256: $sourceHash",
  "EA version: 1.011",
  "Period: 2026-08-04 through 2026-10-20",
  "Model: 4 — every tick based on real ticks",
  "Expected inputs: risk=0.50%; stop=0.45 ATR; target=2.4 ATR; trail=1.4 ATR; spread=100; ADX=23-25; short-only; candle direction=true; EMA rejection=true.",
  "OrderCheck is called before market entry, opposite close and SL/TP modification. This tests request preflight, not a guarantee of eventual fill.",
  "UTC preflight: $([DateTime]::UtcNow.ToString('o'))"
) | Set-Content -LiteralPath (Join-Path $PWD "goldlab-ordercheck-preflight.txt") -Encoding utf8

& $runtimeRunner
$reports = Join-Path $PWD "goldlab-results"
$summaryLines = @()
foreach ($file in @(Get-ChildItem -LiteralPath $reports -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in @(".txt",".log") })) {
  $summaryLines += @(Get-Content -LiteralPath $file.FullName -ErrorAction SilentlyContinue | Where-Object { $_ -match 'GoldLab\|ORDER_CHECK_SUMMARY\|' })
}
if ($summaryLines.Count -eq 0) { throw "No ORDER_CHECK_SUMMARY line was found in copied MT5 logs; result is incomplete." }
$passTotal = 0
$failTotal = 0
foreach ($line in $summaryLines) {
  if ($line -match 'passed=(\d+)') { $passTotal += [int]$Matches[1] }
  if ($line -match 'failed=(\d+)') { $failTotal += [int]$Matches[1] }
}
$summaryPath = Join-Path $reports "run-summary.txt"
@(
  "",
  "## OrderCheck preflight diagnostic",
  "EA source SHA-256: $sourceHash",
  "Summary lines found: $($summaryLines.Count)",
  "OrderCheck passes: $passTotal",
  "OrderCheck failures: $failTotal",
  "OrderCheck summary records:"
) | Add-Content -LiteralPath $summaryPath -Encoding utf8
$summaryLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
if ($passTotal -lt 1) { throw "No OrderCheck success was observed; request-preflight remains unproven." }
if ($failTotal -gt 0) { throw "OrderCheck rejected $failTotal request(s); inspect tester logs before acceptance." }
"OrderCheck diagnostic gate: PASS (passes=$passTotal; failures=$failTotal)." | Add-Content -LiteralPath $summaryPath -Encoding utf8
Get-Content -LiteralPath $summaryPath
