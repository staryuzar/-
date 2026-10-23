# Controlled one-variable experiment: stop 0.35 ATR vs validated 0.45 ATR baseline.
# ADX remains 23-25; date window ends 2026-10-20; protected holdout is not tested.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$runnerPath = ".github/scripts/goldlab_mt5_test_setfree.ps1"
$eaPath = "trading-lab/gold-xauusd/GoldLabEA.mq5"
if (!(Test-Path -LiteralPath $runnerPath)) { throw "Generic MT5 runner is missing." }
if (!(Test-Path -LiteralPath $eaPath)) { throw "GoldLabEA source is missing." }

$source = Get-Content -LiteralPath $eaPath -Raw
if ($source -notmatch '(?m)^#property version\s+"1\.014"' -or
    $source -notmatch 'PreflightTradeRequest\(request,"open"\)' -or
    $source -notmatch 'PreflightTradeRequest\(request,"close"\)' -or
    $source -notmatch 'PreflightTradeRequest\(request,"modify-sltp"\)' -or
    $source -notmatch 'ORDER_CHECK_SUMMARY' -or
    $source -notmatch 'if\(!ok\s*\|\|\s*check\.retcode\s*!=\s*0\)' -or
    $source -notmatch 'call_ok=' -or
    $source -notmatch 'Research candidate v1\.014;' -or
    $source -notmatch 'RecordOrderSendTelemetry\(' -or
    $source -notmatch 'ORDER_SEND_FAIL' -or
    $source -notmatch 'ORDER_SEND_SUMMARY' -or
    $source -notmatch 'ORDER_SEND_RESULT' -or
    $source -notmatch 'ORDER_REQUEST_RESULT' -or
    $source -notmatch 'ORDER_REQUEST_SUMMARY' -or
    $source -notmatch 'void OnTradeTransaction\(' -or
    $source -notmatch 'TRADE_TRANSACTION_REQUEST') {
  throw "EA source does not contain the intended v1.014 OrderCheck, OrderSend, and request-result telemetry gates."
}
$sourceHash = (Get-FileHash -LiteralPath $eaPath -Algorithm SHA256).Hash.ToLowerInvariant()

# Build a disposable, set-free EA copy: keep all strategy logic identical and bake only the test inputs
# into the input defaults. This avoids relying on ExpertParameters=.set for this diagnostic.
$runtimeSourceDir = Join-Path $PWD "goldlab-results\test-source"
New-Item -ItemType Directory -Path $runtimeSourceDir -Force | Out-Null
$runtimeSourcePath = Join-Path $runtimeSourceDir "GoldLabEA.mq5"
$runtimeSource = $source
$inputDefaultOverrides = @(
  @("input double           InpMinADX              = 18.0;", "input double           InpMinADX              = 23.0;"),
  @("input double           InpMaxADX              = 40.0;", "input double           InpMaxADX              = 25.0;"),
  @("input bool             InpAllowLong            = true;", "input bool             InpAllowLong            = false;"),
  @("input double           InpStopATR             = 1.8;", "input double           InpStopATR             = 0.35;"),
  @("input bool             InpRequireSignalCandleDirection = false;", "input bool             InpRequireSignalCandleDirection = true;"),
  @("input bool             InpRequireFastEMARejection = false;", "input bool             InpRequireFastEMARejection = true;")
)
foreach ($override in $inputDefaultOverrides) {
  if (!$runtimeSource.Contains($override[0])) { throw "Runtime input-baking marker missing: $($override[0])" }
  $runtimeSource = $runtimeSource.Replace($override[0], $override[1])
}
[System.IO.File]::WriteAllText($runtimeSourcePath,$runtimeSource,[System.Text.UTF8Encoding]::new($false))
$runtimeSourceHash = (Get-FileHash -LiteralPath $runtimeSourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$env:GOLDLAB_RUNTIME_EA_SOURCE = $runtimeSourcePath
$content = Get-Content -LiteralPath $runnerPath -Raw

$writeCsvMarker = "InpWriteTradeCSV=true||false||0||true||N"
$writeCsvReplacement = $writeCsvMarker + [Environment]::NewLine + "InpRequireSignalCandleDirection=true||true||0||true||N" + [Environment]::NewLine + "InpRequireFastEMARejection=true||false||0||false||N"
$replacements = @(
  @("2026-09-01 through 2026-10-19 (short-side-only diagnostic)", "2026-08-05 through 2026-10-20 (OrderCheck execution-safety diagnostic; short-only)"),
  @("model 1 (1-minute OHLC diagnostic; not real-tick validation)", "model 4 (Every tick based on real ticks; OrderCheck diagnostic)"),
  @("Parameter experiment: risk=0.50%, stop=0.45 ATR, max spread=100 points, max ADX=40, long entries disabled for one-sided diagnostic. OHLC only, not production validation.", "Parameter experiment: risk=0.50%, stop=0.35 ATR, max spread=100 points, ADX=23-25, long entries disabled, candle-direction and EMA rejection enabled. Real-tick demo/tester diagnostic only."),
  @("GoldLabShortOnlyADX40Stop045.set", "GoldLabADX25Min23OrderCheckStop035.set"),
  @("InpMinADX=18.0||18.0||1.0||18.0||N", "InpMinADX=23.0||23.0||1.0||23.0||N"),
  @("InpMaxADX=40.0||40.0||1.0||40.0||N", "InpMaxADX=25.0||25.0||1.0||25.0||N"),
  @("InpStopATR=0.45||0.45||0.05||0.45||N", "InpStopATR=0.35||0.35||0.05||0.35||N"),
  @("InpWriteTradeCSV=true||false||0||true||N", $writeCsvReplacement),
  @("ADX 18-40, long entries disabled", "ADX 23-25, long entries disabled, candle direction=true, fast EMA rejection=true"),
  @("GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-10-19", "GoldLab_ordercheck_adx25_min23_stop035_2026-08-05_to_2026-10-20"),
  @("GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19.htm", "GoldLab_ordercheck_adx25_min23_stop035_2026-08-05_to-2026-10-20.htm")
)
foreach ($pair in $replacements) {
  if (!$content.Contains($pair[0])) { throw "Exact generic-runner replacement marker is missing: $($pair[0])" }
  $content = $content.Replace($pair[0], $pair[1])
}
$content = [regex]::Replace($content, '(?m)^Model=1\r?$', 'Model=4')
$content = [regex]::Replace($content, '(?m)^FromDate=2026\.09\.01\r?$', 'FromDate=2026.08.05')
$content = [regex]::Replace($content, '(?m)^ToDate=2026\.10\.19\r?$', 'ToDate=2026.10.20')
$content = $content.Replace("InpStopATR=0\.45</b>", "InpStopATR=0\.35</b>")
$content = $content.Replace('Tester parameter file: $setName (risk=0.50%, stop=0.45 ATR, max spread=100 points, ADX 18-40, long entries disabled)', 'Tester input source: $setName is audit-only (ExpertParameters omitted); active temporary EA defaults use stop=0.35 ATR, ADX=23-25, short-only.')
$content = $content.Replace('"Tester parameter file: $setName (risk=0.50%, stop=0.45 ATR, max spread=100 points, ADX 18-40, long entries disabled)"', '"Tester input source: $setName is audit-only (ExpertParameters omitted); active temporary EA defaults use stop=0.35 ATR, ADX=23-25, short-only."')
$oldMax = '($html -match ''(?is)InpMaxADX=40(?:\.0+)?</b>'')'
$newChecks = '($html -match ''(?is)InpRiskPercent=0\.5</b>'') -and ($html -match ''(?is)InpStopATR=0\.35</b>'') -and ($html -match ''(?is)InpMaxSpreadPoints=100(?:\.0+)?</b>'') -and ($html -match ''(?is)InpAllowLong=false</b>'') -and ($html -match ''(?is)InpMinADX=23(?:\.0+)?</b>'') -and ($html -match ''(?is)InpMaxADX=25(?:\.0+)?</b>'') -and ($html -match ''(?is)InpRequireSignalCandleDirection=true</b>'') -and ($html -match ''(?is)InpRequireFastEMARejection=true</b>'') -and ($html -match ''(?is)Period:</td>\s*<td[^>]*><b>M5 \(2026\.08\.05 - 2026\.10\.20\)</b>'')'
if (!$content.Contains($oldMax)) { throw "Parameter verification source marker not found." }
$content = $content.Replace($oldMax, $newChecks)
$expertParametersMarker = 'ExpertParameters=$setName'
if (!$content.Contains($expertParametersMarker)) { throw "ExpertParameters line marker missing for set-free test." }
$content = $content.Replace($expertParametersMarker, '; ExpertParameters intentionally omitted; use runtime input defaults')
$content = $content.Replace("Input verification: PASS (risk=0.5, stop=0.45 ATR, max spread=100, max ADX=40, long entries disabled)", "Input + date verification: PASS (risk=0.5, stop=0.35 ATR, max spread=100, ADX 23-25, long entries disabled, candle direction=true, fast EMA rejection=true, report period ends 2026-10-20)")

$checks = @(
  ($content -match 'InpMinADX=23\.0'),
  ($content -match 'InpMaxADX=25.0'),
  ($content -match 'InpStopATR=0.35'),
  ($content -match 'InpRequireSignalCandleDirection=true'),
  ($content -match 'InpRequireFastEMARejection=true'),
  ($content -match '(?m)^Model=4\r?$'),
  ($content -match '(?m)^FromDate=2026\.08\.05\r?$'),
  ($content -match '(?m)^ToDate=2026\.10\.20\r?$'),
  ($content -match 'GoldLab_ordercheck_adx25_min23_stop035_2026-08-05_to-2026-10-20'),
  ($content -match '2026\.10\.20'),
  ($content -match 'OrderCheck diagnostic')
)
if ($checks -contains $false) {
  $checkNames = @("InpMinADX=23.0","InpMaxADX=25.0","InpStopATR=0.35","InpRequireSignalCandleDirection=true","InpRequireFastEMARejection=true","Model=4","FromDate=2026.08.05","ToDate=2026.10.20","report basename","OrderCheck period guard","OrderCheck diagnostic label")
  for ($i=0; $i -lt $checks.Count; $i++) { Write-Host ("PRECHECK " + $checkNames[$i] + "=" + [bool]$checks[$i]) }
  throw "OrderCheck diagnostic runner preflight failed; see named PRECHECK results above."
}
$runtimeRunner = Join-Path $env:RUNNER_TEMP "goldlab_mt5_ordercheck_runner.ps1"
[System.IO.File]::WriteAllText($runtimeRunner, $content, [System.Text.UTF8Encoding]::new($false))
@(
  "OrderCheck execution-safety diagnostic",
  "EA source SHA-256: $sourceHash",
  "Runtime test source SHA-256 (temporary inputs baked; logic unchanged): $runtimeSourceHash",
  "Parameter transport: set-free; ExpertParameters is intentionally omitted to avoid custom .set load failures.",
  "EA version: 1.014",
  "Period: 2026-08-05 through 2026-10-20",
  "Model: 4 — every tick based on real ticks",
  "Expected inputs: risk=0.50%; stop=0.35 ATR; target=2.4 ATR; trail=1.4 ATR; spread=100; ADX=23-25; short-only; candle direction=true; EMA rejection=true.",
  "OrderCheck preflight, immediate OrderSend results, and TRADE_TRANSACTION_REQUEST replies are logged separately. This is diagnostics only; deal history remains the execution audit.",
  "UTC preflight: $([DateTime]::UtcNow.ToString('o'))"
) | Set-Content -LiteralPath (Join-Path $PWD "goldlab-ordercheck-preflight.txt") -Encoding utf8

& $runtimeRunner
$env:GOLDLAB_RUNTIME_EA_SOURCE = $null
$reports = Join-Path $PWD "goldlab-results"
$rawSummaryLines = @()
foreach ($file in @(Get-ChildItem -LiteralPath $reports -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in @(".txt",".log") })) {
  $rawSummaryLines += @(Get-Content -LiteralPath $file.FullName -ErrorAction SilentlyContinue | Where-Object { $_ -match 'GoldLab\|ORDER_CHECK_SUMMARY\|' })
}
if ($rawSummaryLines.Count -eq 0) { throw "No ORDER_CHECK_SUMMARY line was found in copied MT5 logs; result is incomplete." }

# MT5 mirrors the EA summary in chart and Core logs; count each unique payload once.
$seenSummaryPayloads = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$uniqueSummaryLines = @()
foreach ($line in $rawSummaryLines) {
  $marker = "GoldLab|ORDER_CHECK_SUMMARY|"
  $markerIndex = $line.IndexOf($marker, [System.StringComparison]::Ordinal)
  if ($markerIndex -lt 0) { throw "Malformed ORDER_CHECK_SUMMARY record; refusing an ambiguous count." }
  $payload = $line.Substring($markerIndex + $marker.Length).Trim()
  if ($payload -notmatch '^[^|]+\|passed=\d+;failed=\d+;deinit_reason=\d+') {
    throw "Unexpected ORDER_CHECK_SUMMARY payload format: $payload"
  }
  if ($seenSummaryPayloads.Add($payload)) { $uniqueSummaryLines += $line }
}
if ($uniqueSummaryLines.Count -eq 0) { throw "No unique ORDER_CHECK_SUMMARY payload was found; result is incomplete." }

$passTotal = 0
$failTotal = 0
foreach ($line in $uniqueSummaryLines) {
  if ($line -match 'passed=(\d+)') { $passTotal += [int]$Matches[1] }
  if ($line -match 'failed=(\d+)') { $failTotal += [int]$Matches[1] }
}
$duplicateCount = $rawSummaryLines.Count - $uniqueSummaryLines.Count
$summaryPath = Join-Path $reports "run-summary.txt"
@(
  "",
  "## OrderCheck preflight diagnostic",
  "EA source SHA-256: $sourceHash",
  "Raw summary log lines: $($rawSummaryLines.Count)",
  "Unique summary payloads: $($uniqueSummaryLines.Count)",
  "Duplicate summary copies ignored: $duplicateCount",
  "OrderCheck passes (unique payloads): $passTotal",
  "OrderCheck failures (unique payloads): $failTotal",
  "Unique OrderCheck summary records:"
) | Add-Content -LiteralPath $summaryPath -Encoding utf8
$uniqueSummaryLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
"Raw OrderCheck summary lines (includes duplicates):" | Add-Content -LiteralPath $summaryPath -Encoding utf8
$rawSummaryLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
if ($passTotal -lt 1) { throw "No OrderCheck success was observed; request-preflight remains unproven." }
if ($failTotal -gt 0) { throw "OrderCheck rejected $failTotal request(s); inspect tester logs before acceptance." }
"OrderCheck diagnostic gate: PASS (unique passes=$passTotal; unique failures=$failTotal; duplicate copies ignored=$duplicateCount)." | Add-Content -LiteralPath $summaryPath -Encoding utf8

$rawSendSummaryLines = @()
foreach ($file in @(Get-ChildItem -LiteralPath $reports -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in @(".txt",".log") })) {
  $rawSendSummaryLines += @(Get-Content -LiteralPath $file.FullName -ErrorAction SilentlyContinue | Where-Object { $_ -match 'GoldLab\|ORDER_SEND_SUMMARY\|' })
}
if ($rawSendSummaryLines.Count -eq 0) { throw "No ORDER_SEND_SUMMARY line found; send telemetry is incomplete." }
$seenSendPayloads = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$uniqueSendSummaryLines = @()
foreach ($line in $rawSendSummaryLines) {
  $marker = "GoldLab|ORDER_SEND_SUMMARY|"
  $markerIndex = $line.IndexOf($marker, [System.StringComparison]::Ordinal)
  if ($markerIndex -lt 0) { throw "Malformed ORDER_SEND_SUMMARY record; refusing an ambiguous count." }
  $payload = $line.Substring($markerIndex + $marker.Length).Trim()
  if ($payload -notmatch '^[^|]+\|calls=\d+;accepted=\d+;failed=\d+;deinit_reason=\d+$') {
    throw "Unexpected ORDER_SEND_SUMMARY payload format: $payload"
  }
  if ($seenSendPayloads.Add($payload)) { $uniqueSendSummaryLines += $line }
}
if ($uniqueSendSummaryLines.Count -eq 0) { throw "No unique ORDER_SEND_SUMMARY payload found; result is incomplete." }
$sendCallTotal = 0
$sendAcceptedTotal = 0
$sendFailTotal = 0
foreach ($line in $uniqueSendSummaryLines) {
  if ($line -match 'calls=(\d+)') { $sendCallTotal += [int]$Matches[1] }
  if ($line -match 'accepted=(\d+)') { $sendAcceptedTotal += [int]$Matches[1] }
  if ($line -match 'failed=(\d+)') { $sendFailTotal += [int]$Matches[1] }
}
$sendDuplicateCount = $rawSendSummaryLines.Count - $uniqueSendSummaryLines.Count
@(
  "",
  "## OrderSend result telemetry",
  "EA source SHA-256: $sourceHash",
  "Raw summary log lines: $($rawSendSummaryLines.Count)",
  "Unique summary payloads: $($uniqueSendSummaryLines.Count)",
  "Duplicate summary copies ignored: $sendDuplicateCount",
  "OrderSend calls (unique payloads): $sendCallTotal",
  "OrderSend accepted (unique payloads): $sendAcceptedTotal",
  "OrderSend failures (unique payloads): $sendFailTotal",
  "Unique OrderSend summary records:"
) | Add-Content -LiteralPath $summaryPath -Encoding utf8
$uniqueSendSummaryLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
"Raw OrderSend summary lines (includes duplicates):" | Add-Content -LiteralPath $summaryPath -Encoding utf8
$rawSendSummaryLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
if ($sendCallTotal -lt 1) { throw "No OrderSend call observed; result telemetry is unproven." }
if (($sendAcceptedTotal + $sendFailTotal) -ne $sendCallTotal) { throw "OrderSend summary counts do not reconcile; inspect tester telemetry." }
if ($sendFailTotal -gt 0) { throw "OrderSend recorded $sendFailTotal failure(s); inspect detailed ORDER_SEND_FAIL records before acceptance." }
"OrderSend telemetry gate: PASS (calls=$sendCallTotal; accepted=$sendAcceptedTotal; failures=$sendFailTotal; duplicate copies ignored=$sendDuplicateCount)." | Add-Content -LiteralPath $summaryPath -Encoding utf8

$rawImmediateResultLines = @()
$rawRequestResultLines = @()
$rawRequestSummaryLines = @()
foreach ($file in @(Get-ChildItem -LiteralPath $reports -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in @(".txt",".log") })) {
  $lines = Get-Content -LiteralPath $file.FullName -ErrorAction SilentlyContinue
  $rawImmediateResultLines += @($lines | Where-Object { $_ -match 'GoldLab\|ORDER_SEND_RESULT\|' })
  $rawRequestResultLines += @($lines | Where-Object { $_ -match 'GoldLab\|ORDER_REQUEST_RESULT\|' })
  $rawRequestSummaryLines += @($lines | Where-Object { $_ -match 'GoldLab\|ORDER_REQUEST_SUMMARY\|' })
}
if ($rawImmediateResultLines.Count -eq 0) { throw "No ORDER_SEND_RESULT records found; per-call telemetry is incomplete." }
if ($rawRequestResultLines.Count -eq 0) { throw "No ORDER_REQUEST_RESULT records found; server request-result telemetry is incomplete." }
if ($rawRequestSummaryLines.Count -eq 0) { throw "No ORDER_REQUEST_SUMMARY found; request-result summary is incomplete." }

$seenImmediatePayloads = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$uniqueImmediateResultLines = @()
$seenImmediateSeq = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($line in $rawImmediateResultLines) {
  $marker = "GoldLab|ORDER_SEND_RESULT|"
  $markerIndex = $line.IndexOf($marker, [System.StringComparison]::Ordinal)
  if ($markerIndex -lt 0) { throw "Malformed ORDER_SEND_RESULT record." }
  $payload = $line.Substring($markerIndex + $marker.Length).Trim()
  if ($payload -notmatch '^[^|]+\|seq=\d+;context=[^;]+;sent=(true|false);accepted=(true|false);request_id=\d+;retcode=\d+;') {
    throw "Unexpected ORDER_SEND_RESULT payload format: $payload"
  }
  if ($seenImmediatePayloads.Add($payload)) {
    if ($payload -match '\|seq=(\d+);') {
      if (!$seenImmediateSeq.Add($Matches[1])) { throw "Duplicate send sequence number across distinct payloads: $($Matches[1])" }
    }
    $uniqueImmediateResultLines += $line
  }
}
$sendResultDuplicateCount = $rawImmediateResultLines.Count - $uniqueImmediateResultLines.Count
$sendResultIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$sendResultZeroIds = 0
$sendResultSignatures = @{}
$sendResultZeroSignatures = @()
foreach ($line in $uniqueImmediateResultLines) {
  $markerIndex = $line.IndexOf("GoldLab|ORDER_SEND_RESULT|", [System.StringComparison]::Ordinal)
  $payload = $line.Substring($markerIndex + "GoldLab|ORDER_SEND_RESULT|".Length)
  if ($payload -match ';request_id=(\d+);retcode=(\d+);order=(\d+);deal=(\d+);volume=([\d.]+);price=([\d.]+);comment=') {
    $rid = [string]$Matches[1]
    $signature = "$($Matches[2])|$($Matches[3])|$($Matches[4])|$($Matches[5])|$($Matches[6])"
    if ($rid -eq "0") {
      $sendResultZeroIds++
      if ($Matches[3] -eq "0" -and $Matches[4] -eq "0") { throw "request_id=0 has neither an order nor a deal ticket; no safe fallback key exists." }
      $sendResultZeroSignatures += $signature
    } else {
      [void]$sendResultIds.Add($rid)
      $sendResultSignatures[$rid] = $signature
    }
  } else { throw "Cannot parse request_id and result signature from ORDER_SEND_RESULT: $payload" }
}
if ($uniqueImmediateResultLines.Count -ne $sendCallTotal) {
  throw "ORDER_SEND_RESULT records ($($uniqueImmediateResultLines.Count)) do not equal OrderSend calls ($sendCallTotal)."
}
if ($sendResultIds.Count -ne ($uniqueImmediateResultLines.Count - $sendResultZeroIds)) {
  throw "Duplicate nonzero request IDs occurred across immediate OrderSend results."
}

$seenRequestPayloads = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$uniqueRequestResultLines = @()
foreach ($line in $rawRequestResultLines) {
  $marker = "GoldLab|ORDER_REQUEST_RESULT|"
  $markerIndex = $line.IndexOf($marker, [System.StringComparison]::Ordinal)
  if ($markerIndex -lt 0) { throw "Malformed ORDER_REQUEST_RESULT record." }
  $payload = $line.Substring($markerIndex + $marker.Length).Trim()
  if ($payload -notmatch '^[^|]+\|request_id=\d+;action=[^;]+;type=[^;]+;magic=\d+;retcode=\d+;accepted_by_retcode=(true|false);') {
    throw "Unexpected ORDER_REQUEST_RESULT payload format: $payload"
  }
  if ($seenRequestPayloads.Add($payload)) { $uniqueRequestResultLines += $line }
}
$requestResultDuplicateCount = $rawRequestResultLines.Count - $uniqueRequestResultLines.Count
$requestResultIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$requestResultZeroIds = 0
$requestResultSignatures = @{}
$requestResultZeroSignatures = @()
$requestResultOtherRetcodeLines = @()
foreach ($line in $uniqueRequestResultLines) {
  $markerIndex = $line.IndexOf("GoldLab|ORDER_REQUEST_RESULT|", [System.StringComparison]::Ordinal)
  $payload = $line.Substring($markerIndex + "GoldLab|ORDER_REQUEST_RESULT|".Length)
  if ($payload -match '^[^|]+\|request_id=(\d+);action=[^;]+;type=[^;]+;magic=\d+;retcode=(\d+);accepted_by_retcode=(true|false);comment=.*?;order=(\d+);deal=(\d+);volume=([\d.]+);price=([\d.]+);retcode_external=(-?\d+)$') {
    $rid = [string]$Matches[1]
    $signature = "$($Matches[2])|$($Matches[4])|$($Matches[5])|$($Matches[6])|$($Matches[7])"
    if ($rid -eq "0") {
      $requestResultZeroIds++
      if ($Matches[4] -eq "0" -and $Matches[5] -eq "0") { throw "request_id=0 callback has neither an order nor a deal ticket; no safe fallback key exists." }
      $requestResultZeroSignatures += $signature
    } else {
      [void]$requestResultIds.Add($rid)
      $requestResultSignatures[$rid] = $signature
    }
  } else { throw "Cannot parse request_id and result signature from ORDER_REQUEST_RESULT: $payload" }
  if ($payload -match ';accepted_by_retcode=false;') { $requestResultOtherRetcodeLines += $line }
}

$seenRequestSummaryPayloads = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$uniqueRequestSummaryLines = @()
foreach ($line in $rawRequestSummaryLines) {
  $marker = "GoldLab|ORDER_REQUEST_SUMMARY|"
  $markerIndex = $line.IndexOf($marker, [System.StringComparison]::Ordinal)
  if ($markerIndex -lt 0) { throw "Malformed ORDER_REQUEST_SUMMARY record." }
  $payload = $line.Substring($markerIndex + $marker.Length).Trim()
  if ($payload -notmatch '^[^|]+\|callbacks=\d+;accepted_by_retcode=\d+;other_retcode=\d+;deinit_reason=\d+$') {
    throw "Unexpected ORDER_REQUEST_SUMMARY payload format: $payload"
  }
  if ($seenRequestSummaryPayloads.Add($payload)) { $uniqueRequestSummaryLines += $line }
}
if ($uniqueRequestSummaryLines.Count -ne 1) {
  throw "Expected exactly one unique ORDER_REQUEST_SUMMARY payload, got $($uniqueRequestSummaryLines.Count)."
}
$requestCallbackSummary = 0
$requestAcceptedSummary = 0
$requestOtherSummary = 0
$uniqueSummaryLine = $uniqueRequestSummaryLines[0]
if ($uniqueSummaryLine -match 'callbacks=(\d+)') { $requestCallbackSummary = [int]$Matches[1] }
if ($uniqueSummaryLine -match 'accepted_by_retcode=(\d+)') { $requestAcceptedSummary = [int]$Matches[1] }
if ($uniqueSummaryLine -match 'other_retcode=(\d+)') { $requestOtherSummary = [int]$Matches[1] }
if ($requestCallbackSummary -ne $uniqueRequestResultLines.Count) {
  throw "ORDER_REQUEST_SUMMARY callbacks ($requestCallbackSummary) do not match unique request-result records ($($uniqueRequestResultLines.Count))."
}
if (($requestAcceptedSummary + $requestOtherSummary) -ne $requestCallbackSummary) {
  throw "Request-result summary counters do not reconcile."
}

$matchedRequestIds = 0
$unmatchedSendIds = @()
$unmatchedReplyIds = @()
$signatureMismatches = @()
foreach ($id in $sendResultIds) {
  if ($requestResultIds.Contains($id)) {
    if ($sendResultSignatures[$id] -eq $requestResultSignatures[$id]) { $matchedRequestIds++ }
    else { $signatureMismatches += $id }
  } else { $unmatchedSendIds += $id }
}
foreach ($id in $requestResultIds) {
  if (!$sendResultIds.Contains($id)) { $unmatchedReplyIds += $id }
}
if ($sendResultZeroIds -ne $requestResultZeroIds) {
  throw "request_id=0 record count differs between immediate results and server callbacks."
}
if ($sendResultZeroIds -gt 1) {
  throw "More than one request_id=0 encountered; signature fallback is ambiguous."
}
$matchedZeroIdFallback = 0
if ($sendResultZeroIds -eq 1) {
  if ($sendResultZeroSignatures[0] -ne $requestResultZeroSignatures[0]) {
    throw "request_id=0 fallback signature mismatch on retcode/order/deal/volume/price."
  }
  $matchedZeroIdFallback = 1
}
@(
  "",
  "## OrderSend ↔ OnTradeTransaction request-result correlation",
  "Raw ORDER_SEND_RESULT lines: $($rawImmediateResultLines.Count)",
  "Unique ORDER_SEND_RESULT records: $($uniqueImmediateResultLines.Count)",
  "Mirrored send-result copies ignored: $sendResultDuplicateCount",
  "Distinct nonzero immediate request IDs: $($sendResultIds.Count)",
  "Immediate result records with request_id=0: $sendResultZeroIds",
  "Raw ORDER_REQUEST_RESULT lines: $($rawRequestResultLines.Count)",
  "Unique ORDER_REQUEST_RESULT records: $($uniqueRequestResultLines.Count)",
  "Mirrored request-result copies ignored: $requestResultDuplicateCount",
  "Distinct nonzero callback request IDs: $($requestResultIds.Count)",
  "Callback records with request_id=0: $requestResultZeroIds",
  "Matched distinct nonzero request IDs (including result signature): $matchedRequestIds",
  "Verified request_id=0 fallback matches by retcode/order/deal/volume/price: $matchedZeroIdFallback",
  "Request-result signature mismatches: $($signatureMismatches.Count)",
  "Immediate request IDs without matching callback: $($unmatchedSendIds.Count)",
  "Callback request IDs without matching immediate result: $($unmatchedReplyIds.Count)",
  "Callback summary: callbacks=$requestCallbackSummary; accepted_by_retcode=$requestAcceptedSummary; other_retcode=$requestOtherSummary",
  "Unique ORDER_REQUEST_SUMMARY record:"
) | Add-Content -LiteralPath $summaryPath -Encoding utf8
$uniqueRequestSummaryLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
if ($unmatchedSendIds.Count -gt 0) { "Unmatched send request IDs: $($unmatchedSendIds -join ',')" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
if ($unmatchedReplyIds.Count -gt 0) { "Unmatched callback request IDs: $($unmatchedReplyIds -join ',')" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
if ($requestResultOtherRetcodeLines.Count -gt 0) {
  "Request-result callbacks outside the existing DONE/DONE_PARTIAL/PLACED allow-list:" | Add-Content -LiteralPath $summaryPath -Encoding utf8
  $requestResultOtherRetcodeLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
}
if ($requestResultIds.Count -ne ($uniqueRequestResultLines.Count - $requestResultZeroIds)) {
  throw "Duplicate nonzero request IDs occurred across request-result callbacks."
}
if ($uniqueRequestResultLines.Count -lt 1) { throw "No unique request response callbacks were observed." }
if ($signatureMismatches.Count -gt 0) {
  throw "Immediate/server response signatures mismatch for request IDs: $($signatureMismatches -join ',')."
}
if ($unmatchedSendIds.Count -gt 0 -or $unmatchedReplyIds.Count -gt 0) {
  throw "Request ID correlation mismatch: inspect unmatched IDs in run-summary.txt."
}
if ($requestOtherSummary -gt 0) {
  throw "$requestOtherSummary server request result(s) were outside the accepted retcode allow-list; inspect the recorded callback details before acceptance."
}
"Request-result correlation gate: PASS (matched nonzero IDs=$matchedRequestIds; verified zero-ID signature fallbacks=$matchedZeroIdFallback; callbacks=$requestCallbackSummary; signature mismatches=0; other retcodes=0)." | Add-Content -LiteralPath $summaryPath -Encoding utf8

# Reconcile the HTML report with the deal-level CSV; requests/callbacks are not trade counts.
$qaFailures = [System.Collections.Generic.List[string]]::new()
$qaReportPath = Join-Path $reports "GoldLab_ordercheck_adx25_min23_stop035_2026-08-05_to-2026-10-20.htm"
$qaCsvDir = Join-Path $reports "trade-audit"
$qaCsvFiles = @()
if (Test-Path -LiteralPath $qaCsvDir) { $qaCsvFiles = @(Get-ChildItem -LiteralPath $qaCsvDir -Filter "*.csv" -File -ErrorAction SilentlyContinue) }
$qaPeriod = ""; $qaQuality = ""; $qaNet = [double]::NaN; $qaTrades = -1; $qaDeals = -1
$qaRows = @(); $qaCsvNet = [double]::NaN; $qaOpens = 0; $qaExits = 0; $qaDateViolations = 0
$qaIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
if (!(Test-Path -LiteralPath $qaReportPath)) {
  $qaFailures.Add("Expected MT5 report is missing.")
} else {
  $qaHtml = Get-Content -LiteralPath $qaReportPath -Raw
  $m = [regex]::Match($qaHtml,'(?is)Period:</td>\s*<td[^>]*><b>\s*M5\s*\((\d{4}\.\d{2}\.\d{2})\s*-\s*(\d{4}\.\d{2}\.\d{2})\)\s*</b>')
  if ($m.Success) {
    $qaPeriod = "M5 ($($m.Groups[1].Value) - $($m.Groups[2].Value))"
    if ($m.Groups[1].Value -ne "2026.08.05" -or $m.Groups[2].Value -ne "2026.10.20") { $qaFailures.Add("Unexpected MT5 report period: $qaPeriod") }
  } else { $qaFailures.Add("Could not parse MT5 report period.") }
  $m = [regex]::Match($qaHtml,'(?is)History Quality:</td>\s*<td[^>]*><b>\s*([^<]+?)\s*</b>')
  if ($m.Success) { $qaQuality = $m.Groups[1].Value.Trim() }
  if ($qaQuality -ne "100% real ticks") { $qaFailures.Add("Expected 100% real ticks, report shows '$qaQuality'.") }
  $m = [regex]::Match($qaHtml,'(?is)Total Net Profit:</td>\s*<td[^>]*><b>\s*(-?[\d,]+(?:\.\d+)?)\s*</b>')
  if ($m.Success) { $qaNet = [double]::Parse($m.Groups[1].Value.Replace(",",""),[Globalization.CultureInfo]::InvariantCulture) } else { $qaFailures.Add("Could not parse Total Net Profit.") }
  $m = [regex]::Match($qaHtml,'(?is)Total Trades:</td>\s*<td[^>]*><b>\s*(\d+)\s*</b>')
  if ($m.Success) { $qaTrades = [int]$m.Groups[1].Value } else { $qaFailures.Add("Could not parse Total Trades.") }
  $m = [regex]::Match($qaHtml,'(?is)Total Deals:</td>\s*<td[^>]*><b>\s*(\d+)\s*</b>')
  if ($m.Success) { $qaDeals = [int]$m.Groups[1].Value } else { $qaFailures.Add("Could not parse Total Deals.") }
}
if ($qaCsvFiles.Count -ne 1) {
  $qaFailures.Add("Expected exactly one deal CSV, found $($qaCsvFiles.Count).")
} else {
  try { $qaRows = @(Import-Csv -LiteralPath $qaCsvFiles[0].FullName -ErrorAction Stop) } catch { $qaFailures.Add("Could not parse deal CSV: $($_.Exception.Message)") }
  if ($qaRows.Count -eq 0) { $qaFailures.Add("Deal CSV is empty.") }
  $qaCsvNet = 0.0
  $qaStart = [datetime]::ParseExact("2026.08.05 00:00:00","yyyy.MM.dd HH:mm:ss",[Globalization.CultureInfo]::InvariantCulture)
  # MT5 ToDate is exclusive; reject even a single deal at or after 2026-10-20 00:00.
  $qaEnd = [datetime]::ParseExact("2026.10.20 00:00:00","yyyy.MM.dd HH:mm:ss",[Globalization.CultureInfo]::InvariantCulture)
  foreach ($row in $qaRows) {
    if ([string]::IsNullOrWhiteSpace([string]$row.deal) -or [string]::IsNullOrWhiteSpace([string]$row.time)) {
      $qaFailures.Add("Deal row is missing deal ID or timestamp."); continue
    }
    if (!$qaIds.Add([string]$row.deal)) { $qaFailures.Add("Duplicate deal ID $($row.deal).") }
    if ([string]$row.symbol -ne "XAUUSD") { $qaFailures.Add("Unexpected symbol in deal CSV: $($row.symbol).") }
    try {
      $dt = [datetime]::ParseExact([string]$row.time,"yyyy.MM.dd HH:mm:ss",[Globalization.CultureInfo]::InvariantCulture)
      if ($dt -lt $qaStart -or $dt -ge $qaEnd) { $qaDateViolations++; $qaFailures.Add("Deal timestamp outside permitted interval: $($row.time).") }
    } catch { $qaFailures.Add("Invalid deal timestamp: $($row.time).") }
    if ([string]$row.entry -eq "0") { $qaOpens++ }
    if ([string]$row.entry -eq "1") { $qaExits++ }
    try {
      $qaCsvNet += [double]::Parse([string]$row.profit,[Globalization.CultureInfo]::InvariantCulture)
      $qaCsvNet += [double]::Parse([string]$row.commission,[Globalization.CultureInfo]::InvariantCulture)
      $qaCsvNet += [double]::Parse([string]$row.swap,[Globalization.CultureInfo]::InvariantCulture)
    } catch { $qaFailures.Add("Invalid profit/commission/swap on deal $($row.deal).") }
  }
  if ($qaDeals -ge 0 -and $qaRows.Count -ne $qaDeals) { $qaFailures.Add("CSV rows $($qaRows.Count) != MT5 Total Deals $qaDeals.") }
  if ($qaIds.Count -ne $qaRows.Count) { $qaFailures.Add("CSV deal IDs are not unique.") }
  # GoldLab v1.014 closes each position in full; one entry and one full exit per completed trade.
  if ($qaTrades -ge 0 -and ($qaOpens -ne $qaTrades -or $qaExits -ne $qaTrades)) { $qaFailures.Add("CSV open/exit counts ($qaOpens/$qaExits) do not match MT5 Total Trades $qaTrades.") }
  if (![double]::IsNaN($qaNet) -and [Math]::Abs([Math]::Round($qaCsvNet,2)-[Math]::Round($qaNet,2)) -gt 0.05) { $qaFailures.Add("CSV net ($([Math]::Round($qaCsvNet,2))) != MT5 net ($([Math]::Round($qaNet,2))).") }
}
@(
  "",
  "## MT5 HTML ↔ deal CSV/date-quality gate",
  "Period: $qaPeriod",
  "History Quality: $qaQuality",
  "MT5 Total Trades: $qaTrades",
  "MT5 Total Deals: $qaDeals",
  "CSV rows: $($qaRows.Count)",
  "Unique deal IDs: $($qaIds.Count)",
  "CSV entries/exits: $qaOpens/$qaExits",
  "MT5 net profit: $qaNet",
  "CSV sum(profit+commission+swap): $([Math]::Round($qaCsvNet,2))",
  "Out-of-window CSV deals: $qaDateViolations",
  "Gate failures: $($qaFailures.Count)"
) | Add-Content -LiteralPath $summaryPath -Encoding utf8
if ($qaFailures.Count -gt 0) {
  $qaFailures | ForEach-Object { "FAIL: $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
  throw "MT5 HTML/CSV/date reconciliation gate failed; see run-summary.txt."
}
"MT5 HTML/CSV/date reconciliation gate: PASS." | Add-Content -LiteralPath $summaryPath -Encoding utf8

Get-Content -LiteralPath $summaryPath
