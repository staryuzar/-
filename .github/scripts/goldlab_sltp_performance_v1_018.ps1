$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$runnerPath = ".github/scripts/goldlab_mt5_test.ps1"
$eaPath = "trading-lab/gold-xauusd/GoldLabEA.mq5"
if (!(Test-Path -LiteralPath $runnerPath)) { throw "Generic MT5 runner is missing." }
if (!(Test-Path -LiteralPath $eaPath)) { throw "GoldLabEA source is missing." }

$source = Get-Content -LiteralPath $eaPath -Raw
if ($source -notmatch '(?m)^#property version\s+"1\.018"' -or
    $source -notmatch 'PreflightTradeRequest\(request,"open"\)' -or
    $source -notmatch 'PreflightTradeRequest\(request,"close"\)' -or
    $source -notmatch 'PreflightTradeRequest\(request,"modify-sltp"\)' -or
    $source -notmatch 'ORDER_CHECK_SUMMARY' -or
    $source -notmatch 'if\(!ok\s*\|\|\s*check\.retcode\s*!=\s*0\)' -or
    $source -notmatch 'call_ok=' -or
    $source -notmatch 'Research candidate v1\.018;' -or
    $source -notmatch 'RecordOrderSendTelemetry\(' -or
    $source -notmatch 'ORDER_SEND_FAIL' -or
    $source -notmatch 'ORDER_SEND_SUMMARY' -or
    $source -notmatch 'ORDER_SEND_RESULT' -or
    $source -notmatch 'ORDER_REQUEST_RESULT' -or
    $source -notmatch 'ORDER_REQUEST_SUMMARY' -or
    $source -notmatch 'void OnTradeTransaction\(' -or
    $source -notmatch 'TRADE_TRANSACTION_REQUEST' -or
    $source -notmatch 'SLTP_MODIFY_STATE' -or
    $source -notmatch 'requestedRetryBufferDistance=InpStopRetryBufferATR\*retryATR' -or
    $source -notmatch 'OPEN_STOP_RETRY_BUFFER_CAPPED' -or
    $source -notmatch 'for\(int capIteration=0;capIteration<24;capIteration\+\+\)' -or
    $source -notmatch 'candidateLots>=minLot' -or
    $source -notmatch 'double retryRiskDistance=retryBaseRiskDistance+retryBufferDistance;') {
  throw "EA source does not contain the intended v1.018 OrderCheck, retry-buffer, OrderSend, and request-result telemetry gates."
}
$sourceHash = (Get-FileHash -LiteralPath $eaPath -Algorithm SHA256).Hash.ToLowerInvariant()
$content = Get-Content -LiteralPath $runnerPath -Raw

$writeCsvMarker = "InpWriteTradeCSV=true||false||0||true||N"
$writeCsvReplacement = $writeCsvMarker + [Environment]::NewLine + "InpRequireSignalCandleDirection=true||true||0||true||N" + [Environment]::NewLine + "InpRequireFastEMARejection=true||false||0||false||N" + [Environment]::NewLine + "InpStopRetryBufferATR=0.50||0.50||0.05||0.50||N" + [Environment]::NewLine + "InpTestForceInvalidStopsOnce=false||false||0||true||N"
$replacements = @(
  @("2026-09-01 through 2026-10-19 (short-side-only diagnostic)", "2026-08-05 through 2026-10-20 (OrderCheck execution-safety diagnostic; short-only)"),
  @("model 1 (1-minute OHLC diagnostic; not real-tick validation)", "model 4 (Every tick based on real ticks; Random Delay ExecutionMode=-1 diagnostic)"),
  @("Parameter experiment: risk=0.50%, stop=0.45 ATR, max spread=100 points, max ADX=40, long entries disabled for one-sided diagnostic. OHLC only, not production validation.", "Execution robustness experiment: frozen ADX25 baseline rules; short-only; candle direction and fast EMA rejection enabled; Model 4 real ticks; Random Delay ExecutionMode=-1. The one-off invalid-stop retry requests up to 0.50 ATR extra cushion; v1.018 caps it to the largest affordable value that preserves the cash risk budget."),
  @("GoldLabShortOnlyADX40Stop045.set", "GoldLabADX25Min23OrderCheckStop045_RANDOM_DELAY.set"),
  @("InpMinADX=18.0||18.0||1.0||18.0||N", "InpMinADX=23.0||23.0||1.0||23.0||N"),
  @("InpMaxADX=40.0||40.0||1.0||40.0||N", "InpMaxADX=25.0||25.0||1.0||25.0||N"),
  @("InpWriteTradeCSV=true||false||0||true||N", $writeCsvReplacement),
  @("ADX 18-40, long entries disabled", "ADX 23-25, long entries disabled, candle direction=true, fast EMA rejection=true"),
  @("GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-10-19", "GoldLab_ordercheck_adx25_min23_stop045_randomdelay_2026-08-05_to_2026-10-20"),
  @("GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19.htm", "GoldLab_ordercheck_adx25_min23_stop045_slptrace_2026-08-05_to-2026-10-20.htm")
)
foreach ($pair in $replacements) {
  if (!$content.Contains($pair[0])) { throw "Exact generic-runner replacement marker is missing: $($pair[0])" }
  $content = $content.Replace($pair[0], $pair[1])
}
$content = [regex]::Replace($content, '(?m)^ExecutionMode=0\r?$', 'ExecutionMode=-1')
$content = [regex]::Replace($content, '(?m)^Model=1\r?$', 'Model=4')
$content = [regex]::Replace($content, '(?m)^FromDate=2026\.09\.01\r?$', 'FromDate=2026.08.05')
$content = [regex]::Replace($content, '(?m)^ToDate=2026\.10\.19\r?$', 'ToDate=2026.10.20')
$oldMax = '($html -match ''(?is)InpMaxADX=40(?:\.0+)?</b>'')'
$newChecks = '($html -match ''(?is)InpRiskPercent=0\.5</b>'') -and ($html -match ''(?is)InpStopATR=0\.45</b>'') -and ($html -match ''(?is)InpTargetATR=2\.4</b>'') -and ($html -match ''(?is)InpTrailATR=1\.4</b>'') -and ($html -match ''(?is)InpMaxSpreadPoints=100(?:\.0+)?</b>'') -and ($html -match ''(?is)InpAllowLong=false</b>'') -and ($html -match ''(?is)InpMinADX=23(?:\.0+)?</b>'') -and ($html -match ''(?is)InpMaxADX=25(?:\.0+)?</b>'') -and ($html -match ''(?is)InpRequireSignalCandleDirection=true</b>'') -and ($html -match ''(?is)InpRequireFastEMARejection=true</b>'') -and ($html -match ''(?is)InpStopRetryBufferATR=0\.5(?:0+)?</b>'') -and ($html -match ''(?is)InpTestForceInvalidStopsOnce=false</b>'') -and ($html -match ''(?is)Period:</td>\s*<td[^>]*><b>M5 \(2026\.08\.05 - 2026\.10\.20\)</b>'')'
if (!$content.Contains($oldMax)) { throw "Parameter verification source marker not found." }
$content = $content.Replace($oldMax, $newChecks)
$content = $content.Replace("Input verification: PASS (risk=0.5, stop=0.45 ATR, max spread=100, max ADX=40, long entries disabled)", "Input/date/execution verification: PASS (ADX25 baseline rules confirmed; requested retry-buffer maximum=0.50 ATR (effective cushion is risk-capped on retry); Model 4 real ticks; ExecutionMode=-1 Random Delay; period ends 2026-10-20)")

$checks = @(
  ($content -match 'InpMinADX=23\.0'),
  ($content -match 'InpMaxADX=25\.0'),
  ($content -match 'InpRequireSignalCandleDirection=true'),
  ($content -match 'InpRequireFastEMARejection=true'),
  ($content -match 'InpStopRetryBufferATR=0.50'),
  ($content -match 'InpTestForceInvalidStopsOnce=false'),
  ($content -match '(?m)^Model=4\r?$'),
  ($content -match '(?m)^ExecutionMode=-1\r?$'),
  ($content -match '(?m)^FromDate=2026\.08\.05\r?$'),
  ($content -match '(?m)^ToDate=2026\.10\.20\r?$'),
  ($content -match 'GoldLab_ordercheck_adx25_min23_stop045_slptrace_2026-08-05_to-2026-10-20'),
  ($content -match '2026\.10\.20'),
  ($content -match 'Random Delay ExecutionMode=-1 diagnostic')
)
if ($checks -contains $false) {
  $checkNames = @("InpMinADX=23.0","InpMaxADX=25.0","InpRequireSignalCandleDirection=true","InpRequireFastEMARejection=true","InpStopRetryBufferATR=0.50","InpTestForceInvalidStopsOnce=false","Model=4","ExecutionMode=-1 Random Delay","FromDate=2026.08.05","ToDate=2026.10.20","report basename","OrderCheck period guard","Random Delay execution label")
  for ($i=0; $i -lt $checks.Count; $i++) { Write-Host ("PRECHECK " + $checkNames[$i] + "=" + [bool]$checks[$i]) }
  throw "OrderCheck diagnostic runner preflight failed; see named PRECHECK results above."
}
$runtimeRunner = Join-Path $env:RUNNER_TEMP "goldlab_mt5_ordercheck_runner.ps1"
[System.IO.File]::WriteAllText($runtimeRunner, $content, [System.Text.UTF8Encoding]::new($false))
@(
  "OrderCheck execution-safety diagnostic",
  "EA source SHA-256: $sourceHash",
  "EA version: 1.018",
  "Period: 2026-08-05 through 2026-10-20",
  "Model: 4 — every tick based on real ticks",
  "Execution: Random Delay (ExecutionMode=-1); EA inputs match the frozen ADX25 development baseline; requested retry-buffer maximum=0.50 ATR is applied only after INVALID_STOPS; InpTestForceInvalidStopsOnce=false.",
  "Expected inputs: risk=0.50%; stop=0.45 ATR; target=2.4 ATR; trail=1.4 ATR; spread=100; ADX=23-25; short-only; candle direction=true; EMA rejection=true; retry-only buffer=0.50 ATR.",
  "OrderCheck preflight, immediate OrderSend results, and TRADE_TRANSACTION_REQUEST replies are logged separately. This is diagnostics only; deal history remains the execution audit.",
  "UTC preflight: $([DateTime]::UtcNow.ToString('o'))"
) | Set-Content -LiteralPath (Join-Path $PWD "goldlab-ordercheck-preflight.txt") -Encoding utf8

& $runtimeRunner
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
$evidenceFiles = @(Get-ChildItem -LiteralPath $reports -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in @(".txt",".log") })
$failedModifyRequestIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$retryableOpenRequestIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$failedOpenRetryRequestIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$recoveredOpenRequestIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$safeAbortedOpenRequestIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$rejectedOpenRetryTriggerRequestIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$staleClosedRequestIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$stillOpenFailureRequestIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$seenFailedSendSequences = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$unclassifiableSendFailureSequences = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$recoverySummaryPayloads = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$recoverySummaryLines = @()
$recoveryStaleModifyCount = -1
$openStopRetryAttempts = -1
$openStopRetryRecovered = -1
$openStopRetryFailed = -1
foreach ($file in $evidenceFiles) {
  foreach ($line in (Get-Content -LiteralPath $file.FullName -ErrorAction SilentlyContinue)) {
    if ($line -match 'GoldLab\|ORDER_SEND_RESULT\|[^|]+\|seq=(\d+);context=([^;]+);sent=(true|false);accepted=false;request_id=(\d+);retcode=(\d+);') {
      $seq = [string]$Matches[1]
      $ctx = [string]$Matches[2]
      $sentFlag = [string]$Matches[3]
      $rid = [string]$Matches[4]
      $retcode = [int]$Matches[5]
      if ($seenFailedSendSequences.Add($seq)) {
        if ($ctx -eq "modify-sltp" -and $sentFlag -eq "false" -and $rid -ne "0" -and $retcode -eq 3) {
          [void]$failedModifyRequestIds.Add($rid)
        } elseif ($ctx -eq "open-retryable-stop-reject" -and $rid -ne "0" -and $retcode -eq 10016) {
          # Original invalid-stop attempt remains a raw failure whether retry recovers or is safely refused.
          [void]$retryableOpenRequestIds.Add($rid)
        } elseif ($ctx -eq "open-retry" -and $rid -ne "0" -and $retcode -eq 10016 -and $line -match ';order=0;deal=0;') {
          # Bounded retry itself got INVALID_STOPS and produced no order/deal: a safe refusal, not a fill.
          [void]$failedOpenRetryRequestIds.Add($rid)
        } else {
          [void]$unclassifiableSendFailureSequences.Add($seq)
        }
      }
    }
    if ($line -match 'GoldLab\|OPEN_STOP_RETRY_SUCCESS\|[^|]+\|trigger_request_id=(\d+);outcome=recovered;') {
      [void]$recoveredOpenRequestIds.Add([string]$Matches[1])
    }
    if ($line -match 'GoldLab\|OPEN_STOP_RETRY_ABORT\|[^|]+\|trigger_request_id=(\d+);outcome=safe_no_retry_send;reason=[^;]+') {
      [void]$safeAbortedOpenRequestIds.Add([string]$Matches[1])
    }
    if ($line -match 'GoldLab\|OPEN_STOP_RETRY_FAIL\|[^|]+\|trigger_request_id=(\d+);outcome=retry_send_rejected;retcode=\d+') {
      [void]$rejectedOpenRetryTriggerRequestIds.Add([string]$Matches[1])
    }
    if ($line -match 'GoldLab\|SLTP_MODIFY_STATE\|[^|]+\|request_id=(\d+);ticket=\d+;position_exists_after=false;classification=closed_before_response;sent=false;accepted=false;retcode=3;last_error=4756;') {
      [void]$staleClosedRequestIds.Add([string]$Matches[1])
    }
    if ($line -match 'GoldLab\|SLTP_MODIFY_STATE\|[^|]+\|request_id=(\d+);ticket=\d+;position_exists_after=true;classification=position_still_open;') {
      [void]$stillOpenFailureRequestIds.Add([string]$Matches[1])
    }
    if ($line -match 'GoldLab\|ORDER_SEND_RECOVERY_SUMMARY\|') {
      $marker = "GoldLab|ORDER_SEND_RECOVERY_SUMMARY|"
      $markerIndex = $line.IndexOf($marker,[System.StringComparison]::Ordinal)
      if ($markerIndex -lt 0) { throw "Malformed ORDER_SEND_RECOVERY_SUMMARY record." }
      $payload = $line.Substring($markerIndex + $marker.Length).Trim()
      if ($payload -notmatch '^[^|]+\|stale_modify=(\d+);open_stop_retry_attempts=(\d+);open_stop_retry_recovered=(\d+);open_stop_retry_failed=(\d+);deinit_reason=\d+$') {
        throw "Unexpected ORDER_SEND_RECOVERY_SUMMARY payload: $payload"
      }
      if ($recoverySummaryPayloads.Add($payload)) {
        $recoverySummaryLines += $line
        $recoveryStaleModifyCount = [int]$Matches[1]
        $openStopRetryAttempts = [int]$Matches[2]
        $openStopRetryRecovered = [int]$Matches[3]
        $openStopRetryFailed = [int]$Matches[4]
      }
    }
  }
}
if ($recoverySummaryPayloads.Count -ne 1) {
  throw "Expected exactly one unique ORDER_SEND_RECOVERY_SUMMARY; got $($recoverySummaryPayloads.Count)."
}
$staleModifySummaryMatches = ($recoveryStaleModifyCount -eq $staleClosedRequestIds.Count)
$openRetrySummaryMatches = ($openStopRetryAttempts -eq $retryableOpenRequestIds.Count)
$retryOutcomeCorrelationValid = $true
foreach ($rid in $recoveredOpenRequestIds) {
  if (!$retryableOpenRequestIds.Contains($rid) -or $safeAbortedOpenRequestIds.Contains($rid) -or $rejectedOpenRetryTriggerRequestIds.Contains($rid)) { $retryOutcomeCorrelationValid = $false }
}
foreach ($rid in $safeAbortedOpenRequestIds) {
  if (!$retryableOpenRequestIds.Contains($rid) -or $recoveredOpenRequestIds.Contains($rid) -or $rejectedOpenRetryTriggerRequestIds.Contains($rid)) { $retryOutcomeCorrelationValid = $false }
}
foreach ($rid in $rejectedOpenRetryTriggerRequestIds) {
  if (!$retryableOpenRequestIds.Contains($rid) -or $recoveredOpenRequestIds.Contains($rid) -or $safeAbortedOpenRequestIds.Contains($rid)) { $retryOutcomeCorrelationValid = $false }
}
$openRetryOutcomeCountersMatch = (
  $openStopRetryAttempts -eq $retryableOpenRequestIds.Count -and
  ($openStopRetryRecovered + $openStopRetryFailed) -eq $openStopRetryAttempts -and
  $recoveredOpenRequestIds.Count -eq $openStopRetryRecovered -and
  ($safeAbortedOpenRequestIds.Count + $rejectedOpenRetryTriggerRequestIds.Count) -eq $openStopRetryFailed -and
  ($recoveredOpenRequestIds.Count + $safeAbortedOpenRequestIds.Count + $rejectedOpenRetryTriggerRequestIds.Count) -eq $retryableOpenRequestIds.Count -and
  $retryOutcomeCorrelationValid
)
$allSendFailuresClassified = (
  $sendFailTotal -gt 0 -and
  $unclassifiableSendFailureSequences.Count -eq 0 -and
  ($failedModifyRequestIds.Count + $retryableOpenRequestIds.Count + $failedOpenRetryRequestIds.Count) -eq $sendFailTotal -and
  $failedModifyRequestIds.Count -eq $staleClosedRequestIds.Count -and
  $stillOpenFailureRequestIds.Count -eq 0 -and
  $staleModifySummaryMatches -and
  $openRetrySummaryMatches -and
  $openRetryOutcomeCountersMatch
)
if ($sendFailTotal -gt 0) {
  foreach ($rid in $failedModifyRequestIds) {
    if (!$staleClosedRequestIds.Contains($rid)) { $allSendFailuresClassified = $false }
  }
  if (!$allSendFailuresClassified) {
    @(
      "OrderSend failure classification: FAIL",
      "Raw OrderSend failures: $sendFailTotal",
      "Failed modify-SLTP request IDs: $($failedModifyRequestIds.Count)",
      "Verified local stale-close modifications: $($staleClosedRequestIds.Count)",
      "Retryable INVALID_STOPS first attempts: $($retryableOpenRequestIds.Count)",
      "Open-stop retries attempted/recovered/failed: $openStopRetryAttempts/$openStopRetryRecovered/$openStopRetryFailed",
      "Recovery summary stale-modify count: $recoveryStaleModifyCount",
      "Still-open modify failure IDs: $($stillOpenFailureRequestIds.Count)",
      "Unclassifiable unique OrderSend failure sequences: $($unclassifiableSendFailureSequences.Count)",
  "Original invalid-stop triggers: $($retryableOpenRequestIds.Count)",
      "Bounded retry-send rejected requests: $($failedOpenRetryRequestIds.Count)",
      "Bounded retry outcomes by trigger ID: recovered=$($recoveredOpenRequestIds.Count); safe_abort_before_send=$($safeAbortedOpenRequestIds.Count); send_rejected=$($rejectedOpenRetryTriggerRequestIds.Count)",
      "OrderSend summary failure count: $sendFailTotal"
    ) | Add-Content -LiteralPath $summaryPath -Encoding utf8
    throw "OrderSend failures include an unexplained request, an unsafe retry outcome, an open-position SLTP failure, or a stale-close mismatch; reject robustness run."
  }
  @(
    "OrderSend failure classification: PASS — all raw failures are explained, none is relabelled accepted",
    "Raw OrderSend failures: $sendFailTotal",
    "Failed modify-SLTP requests with position already closed: $($failedModifyRequestIds.Count)",
    "Retryable invalid-stop first attempts: $($retryableOpenRequestIds.Count)",
    "Bounded open-stop retries attempted/recovered/failed: $openStopRetryAttempts/$openStopRetryRecovered/$openStopRetryFailed",
    "Bounded retry outcomes by original trigger ID: recovered=$($recoveredOpenRequestIds.Count); safe_abort_before_second_send=$($safeAbortedOpenRequestIds.Count); second_send_rejected=$($rejectedOpenRetryTriggerRequestIds.Count)",
    "Stale-close modifications remain failed. Each invalid-stop entry trigger is paired with exactly one bounded retry; each retry is either accepted or explicitly classified as a safe rejection with no order/deal.",
    "Still-open modify failure IDs: 0; unexplained failure sequences: 0"
  ) | Add-Content -LiteralPath $summaryPath -Encoding utf8
}
$sendFailClassificationCount = $failedModifyRequestIds.Count + $openStopRetryRecovered
"OrderSend telemetry/classification gate: PASS (calls=$sendCallTotal; accepted=$sendAcceptedTotal; raw failed requests=$sendFailTotal; verified stale-close races=$($failedModifyRequestIds.Count); recovered invalid-stop attempts=$openStopRetryRecovered; unresolved failures=0; duplicate summary copies ignored=$sendDuplicateCount)." | Add-Content -LiteralPath $summaryPath -Encoding utf8

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
$sendResultZeroSentCount = 0
$sendResultSignatures = @{}
$sendResultSentById = @{}
$sendResultZeroSignatures = @()
foreach ($line in $uniqueImmediateResultLines) {
  $markerIndex = $line.IndexOf("GoldLab|ORDER_SEND_RESULT|", [System.StringComparison]::Ordinal)
  $payload = $line.Substring($markerIndex + "GoldLab|ORDER_SEND_RESULT|".Length)
  $sentMatch = [regex]::Match($payload,'^[^|]+\|seq=\d+;context=[^;]+;sent=(true|false);accepted=(true|false);request_id=\d+;')
  if (!$sentMatch.Success) { throw "Cannot parse sent flag from ORDER_SEND_RESULT: $payload" }
  $wasSent = ($sentMatch.Groups[1].Value -eq "true")
  if ($payload -match ';request_id=(\d+);retcode=(\d+);order=(\d+);deal=(\d+);volume=([\d.]+);price=([\d.]+);comment=') {
    $rid = [string]$Matches[1]
    $signature = "$($Matches[2])|$($Matches[3])|$($Matches[4])|$($Matches[5])|$($Matches[6])"
    if ($rid -eq "0") {
      $sendResultZeroIds++
            if ($wasSent) {
        if ($Matches[3] -eq "0" -and $Matches[4] -eq "0") { throw "sent=true with request_id=0 has neither an order nor a deal ticket; no safe fallback key exists." }
        $sendResultZeroSentCount++
        $sendResultZeroSignatures += $signature
      } elseif ($Matches[3] -ne "0" -or $Matches[4] -ne "0") {
        throw "sent=false request_id=0 unexpectedly carries an order/deal ticket; inspect terminal result."
      }
    } else {
      [void]$sendResultIds.Add($rid)
      $sendResultSignatures[$rid] = $signature
      $sendResultSentById[$rid] = $wasSent
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
$requestResultStaleClosureLines = @()
$requestResultOpenRetryTriggerLines = @()
$requestResultFailedOpenRetryLines = @()
foreach ($line in $uniqueRequestResultLines) {
  $markerIndex = $line.IndexOf("GoldLab|ORDER_REQUEST_RESULT|", [System.StringComparison]::Ordinal)
  $payload = $line.Substring($markerIndex + "GoldLab|ORDER_REQUEST_RESULT|".Length)
  if ($payload -match '^[^|]+\|request_id=(\d+);action=[^;]+;type=[^;]+;magic=\d+;retcode=(\d+);accepted_by_retcode=(true|false);comment=.*?;order=(\d+);deal=(\d+);volume=([\d.]+);price=([\d.]+);retcode_external=(-?\d+)$') {
    $rid = [string]$Matches[1]
    $requestResultRetcode = [int]$Matches[2]
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
  if ($payload -match ';accepted_by_retcode=false;') {
    if ($rid -ne "0" -and $staleClosedRequestIds.Contains($rid)) {
      $requestResultStaleClosureLines += $line
    } elseif ($rid -ne "0" -and $retryableOpenRequestIds.Contains($rid) -and $requestResultRetcode -eq 10016 -and ($openStopRetryRecovered + $openStopRetryFailed) -eq $openStopRetryAttempts) {
      # Keep the original rejection visible; the next bounded attempt may recover or be safely refused.
      $requestResultOpenRetryTriggerLines += $line
    } elseif ($rid -ne "0" -and $failedOpenRetryRequestIds.Contains($rid) -and $requestResultRetcode -eq 10016) {
      # The retry itself was refused with INVALID_STOPS; retain this failed callback separately.
      $requestResultFailedOpenRetryLines += $line
    } else {
      $requestResultOtherRetcodeLines += $line
    }
  }
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
$verifiedLocalStaleNoReplyIds = @()
$verifiedLocalOpenRetryTriggerNoReplyIds = @()
$verifiedLocalFailedOpenRetryNoReplyIds = @()
$signatureMismatches = @()
foreach ($id in $sendResultIds) {
  if ($requestResultIds.Contains($id)) {
    if ($sendResultSignatures[$id] -eq $requestResultSignatures[$id]) { $matchedRequestIds++ }
    else { $signatureMismatches += $id }
  } elseif (($sendResultSentById.ContainsKey($id)) -and (-not [bool]$sendResultSentById[$id]) -and $staleClosedRequestIds.Contains($id)) {
    # A local SLTP failure is correlated only when a separate state log proves the position had closed.
    $verifiedLocalStaleNoReplyIds += $id
  } elseif (($sendResultSentById.ContainsKey($id)) -and (-not [bool]$sendResultSentById[$id]) -and $failedOpenRetryRequestIds.Contains($id)) {
    # Retry itself was locally rejected, with no order/deal: no server callback is expected.
    $verifiedLocalFailedOpenRetryNoReplyIds += $id
  } elseif (($sendResultSentById.ContainsKey($id)) -and (-not [bool]$sendResultSentById[$id]) -and $retryableOpenRequestIds.Contains($id) -and ($openStopRetryRecovered + $openStopRetryFailed) -eq $openStopRetryAttempts) {
    # Original invalid-stop request may fail locally; correlate only if the summary accounts for its one bounded retry.
    $verifiedLocalOpenRetryTriggerNoReplyIds += $id
  } else {
    $unmatchedSendIds += $id
  }
}
foreach ($id in $requestResultIds) {
  if (!$sendResultIds.Contains($id)) { $unmatchedReplyIds += $id }
}
if ($sendResultZeroSentCount -ne $requestResultZeroIds) {
  throw "sent=true request_id=0 results ($sendResultZeroSentCount) do not match server callbacks ($requestResultZeroIds); sent=false local failures do not require server callbacks."
}
if ($sendResultZeroSentCount -gt 1) {
  throw "More than one sent=true request_id=0 encountered; signature fallback is ambiguous."
}
$matchedZeroIdFallback = 0
if ($sendResultZeroSentCount -eq 1) {
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
  "Expected server callbacks for request_id=0 (sent=true): $sendResultZeroSentCount",
  "Raw ORDER_REQUEST_RESULT lines: $($rawRequestResultLines.Count)",
  "Unique ORDER_REQUEST_RESULT records: $($uniqueRequestResultLines.Count)",
  "Mirrored request-result copies ignored: $requestResultDuplicateCount",
  "Distinct nonzero callback request IDs: $($requestResultIds.Count)",
  "Callback records with request_id=0: $requestResultZeroIds",
  "Matched distinct nonzero request IDs (including result signature): $matchedRequestIds",
  "Verified request_id=0 fallback matches by retcode/order/deal/volume/price: $matchedZeroIdFallback",
  "Request-result signature mismatches: $($signatureMismatches.Count)",
  "Immediate request IDs without matching callback: $($unmatchedSendIds.Count)",
  "Verified sent=false stale-close requests without server callback: $($verifiedLocalStaleNoReplyIds.Count)",
  "Verified sent=false original invalid-stop triggers without callback: $($verifiedLocalOpenRetryTriggerNoReplyIds.Count)",
  "Verified sent=false failed bounded retries without callback: $($verifiedLocalFailedOpenRetryNoReplyIds.Count)",
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
$rawNonAcceptedCallbackCount = $requestResultOtherRetcodeLines.Count + $requestResultStaleClosureLines.Count + $requestResultOpenRetryTriggerLines.Count + $requestResultFailedOpenRetryLines.Count
if ($requestOtherSummary -ne $rawNonAcceptedCallbackCount) {
  throw "Raw other-retcode summary ($requestOtherSummary) does not reconcile with recorded callback lines ($rawNonAcceptedCallbackCount)."
}
$verifiedStaleCloseTotal = $requestResultStaleClosureLines.Count + $verifiedLocalStaleNoReplyIds.Count
if ($verifiedStaleCloseTotal -ne $failedModifyRequestIds.Count) {
  throw "Verified stale-close server callbacks ($($requestResultStaleClosureLines.Count)) plus local sent=false/no-callback races ($($verifiedLocalStaleNoReplyIds.Count)) do not match failed modify requests ($($failedModifyRequestIds.Count))."
}
$verifiedOpenRetryTriggerTotal = $requestResultOpenRetryTriggerLines.Count + $verifiedLocalOpenRetryTriggerNoReplyIds.Count
if ($verifiedOpenRetryTriggerTotal -ne $retryableOpenRequestIds.Count) {
  throw "Original INVALID_STOPS triggers observed ($verifiedOpenRetryTriggerTotal) do not match identified trigger requests ($($retryableOpenRequestIds.Count))."
}
if ($openStopRetryAttempts -ne $retryableOpenRequestIds.Count -or ($openStopRetryRecovered + $openStopRetryFailed) -ne $openStopRetryAttempts) {
  throw "Retry attempts/recovered/failed counters do not reconcile with original invalid-stop triggers."
}
$safeRetryRefusalCount = $safeAbortedOpenRequestIds.Count + $rejectedOpenRetryTriggerRequestIds.Count
if ($safeRetryRefusalCount -ne $openStopRetryFailed) {
  throw "Safe retry outcomes by trigger ID ($safeRetryRefusalCount) do not match retry-failed counter ($openStopRetryFailed)."
}
$verifiedFailedOpenRetryTotal = $requestResultFailedOpenRetryLines.Count + $verifiedLocalFailedOpenRetryNoReplyIds.Count
if ($verifiedFailedOpenRetryTotal -ne $failedOpenRetryRequestIds.Count) {
  throw "Failed retry server callbacks ($($requestResultFailedOpenRetryLines.Count)) plus local no-callback failures ($($verifiedLocalFailedOpenRetryNoReplyIds.Count)) do not reconcile with failed retry IDs ($($failedOpenRetryRequestIds.Count))."
}
if ($requestOtherSummary -gt ($requestResultStaleClosureLines.Count + $requestResultOpenRetryTriggerLines.Count + $requestResultFailedOpenRetryLines.Count)) {
  throw "$($requestOtherSummary - $requestResultStaleClosureLines.Count - $requestResultOpenRetryTriggerLines.Count - $requestResultFailedOpenRetryLines.Count) callback(s) were not verified as stale-close races or explicitly accounted invalid-stop trigger/retry responses."
}
if ($requestResultStaleClosureLines.Count -gt 0) {
  "Callbacks classified as stale closed-position races (retcode remains non-accepted):" | Add-Content -LiteralPath $summaryPath -Encoding utf8
  $requestResultStaleClosureLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
}
if ($requestResultOpenRetryTriggerLines.Count -gt 0) {
  "Original server INVALID_STOPS trigger callbacks (each followed by one bounded retry):" | Add-Content -LiteralPath $summaryPath -Encoding utf8
  $requestResultOpenRetryTriggerLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
}
if ($requestResultFailedOpenRetryLines.Count -gt 0) {
  "Bounded retry server INVALID_STOPS rejections (safe refusal, not a successful retry):" | Add-Content -LiteralPath $summaryPath -Encoding utf8
  $requestResultFailedOpenRetryLines | ForEach-Object { "- $_" | Add-Content -LiteralPath $summaryPath -Encoding utf8 }
}
"Request-result correlation gate: PASS (matched nonzero server IDs=$matchedRequestIds; zero-ID fallback=$matchedZeroIdFallback; server callbacks=$requestCallbackSummary; local stale-close no-callback=$($verifiedLocalStaleNoReplyIds.Count); original invalid-stop triggers without callback=$($verifiedLocalOpenRetryTriggerNoReplyIds.Count); failed retry without callback=$($verifiedLocalFailedOpenRetryNoReplyIds.Count); trigger callbacks=$($requestResultOpenRetryTriggerLines.Count); failed retry callbacks=$($requestResultFailedOpenRetryLines.Count); unresolved correlation mismatches=0)." | Add-Content -LiteralPath $summaryPath -Encoding utf8

# Reconcile the HTML report with the deal-level CSV; requests/callbacks are not trade counts.
$qaFailures = [System.Collections.Generic.List[string]]::new()
$qaReportPath = Join-Path $reports "GoldLab_ordercheck_adx25_min23_stop045_slptrace_2026-08-05_to-2026-10-20.htm"
$qaCsvDir = Join-Path $reports "trade-audit"
$qaCsvFiles = @()
if (Test-Path -LiteralPath $qaCsvDir) { $qaCsvFiles = @(Get-ChildItem -LiteralPath $qaCsvDir -Filter "*.csv" -File -ErrorAction SilentlyContinue) }
$qaPeriod = ""; $qaQuality = ""; $qaNet = [double]::NaN; $qaTrades = -1; $qaDeals = -1; $qaBars = -1; $qaTicks = -1
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
  $m = [regex]::Match($qaHtml,'(?is)Bars:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
  if ($m.Success) { $qaBars = [int64]::Parse($m.Groups[1].Value.Replace(",",""),[Globalization.CultureInfo]::InvariantCulture) } else { $qaFailures.Add("Could not parse Bars from MT5 HTML.") }
  $m = [regex]::Match($qaHtml,'(?is)Ticks:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
  if ($m.Success) { $qaTicks = [int64]::Parse($m.Groups[1].Value.Replace(",",""),[Globalization.CultureInfo]::InvariantCulture) } else { $qaFailures.Add("Could not parse Ticks from MT5 HTML.") }
  if ($qaBars -lt 10000) { $qaFailures.Add("Insufficient development-window coverage: Bars=$qaBars, minimum 10000.") }
  if ($qaTicks -lt 1000000) { $qaFailures.Add("Insufficient development-window tick coverage: Ticks=$qaTicks, minimum 1000000.") }
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
  "MT5 Bars: $qaBars (minimum 10000)",
  "MT5 Ticks: $qaTicks (minimum 1000000)",
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
"MT5 HTML/CSV/date/coverage reconciliation gate: PASS (period, real-tick quality, minimum bars/ticks, deal count, profit, and timestamps verified)." | Add-Content -LiteralPath $summaryPath -Encoding utf8

Get-Content -LiteralPath $summaryPath
