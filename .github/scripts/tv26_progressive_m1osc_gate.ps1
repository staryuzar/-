$ErrorActionPreference = "Stop"
$culture = [Globalization.CultureInfo]::InvariantCulture
$oscMin = [string]$env:TV26_TEST_M1_OSC_MIN
if ([string]::IsNullOrWhiteSpace($oscMin)) { $oscMin = "0.00" }
$oscMin = ([decimal]::Parse($oscMin,$culture)).ToString("0.00",$culture)
$originalCredentials = [string]$env:MT5_CREDENTIALS
if ([string]::IsNullOrWhiteSpace($originalCredentials)) { throw "GitHub Actions secret mt5 is missing; no tester run attempted." }
$anchor = [datetime]::ParseExact("2026.10.22","yyyy.MM.dd",$culture)
$root = Join-Path $PWD "tv26-progressive-results"
New-Item -ItemType Directory -Path $root -Force | Out-Null
$rows = [System.Collections.Generic.List[object]]::new()
$technicalFailure = $false
$stopReason = "Reached the configured 10-day limit."
$lastPassed = 0

function MetricText([string]$text,[string]$label) {
  $m = [regex]::Match($text,'(?m)^' + [regex]::Escape($label) + '\s*(.*)$')
  if (!$m.Success) { throw "Missing metric: $label" }
  return $m.Groups[1].Value.Trim()
}
function MetricNumber([string]$text,[string]$label) {
  $raw = MetricText $text $label
  $m = [regex]::Match($raw,'[-+]?\d+(?:\.\d+)?')
  if (!$m.Success) { throw "Invalid metric: $label = $raw" }
  return [decimal]::Parse($m.Value,[Globalization.NumberStyles]::Float,$culture)
}

for ($days=1; $days -le 10; $days++) {
  $from = $anchor.AddDays(-($days-1))
  $to = $anchor.AddDays(1)
  $magic = 26102420 + $days
  $stage = Join-Path $root ("day-{0:D2}" -f $days)
  New-Item -ItemType Directory -Path $stage -Force | Out-Null
  $env:TV26_TEST_FROM = $from.ToString("yyyy.MM.dd",$culture)
  $env:TV26_TEST_TO = $to.ToString("yyyy.MM.dd",$culture)
  $env:TV26_TEST_MAGIC = $magic.ToString($culture)
  $env:PYTHONIOENCODING = "utf-8"
  $results = Join-Path $PWD "tv26-strategy-results"
  Remove-Item -LiteralPath $results -Recurse -Force -ErrorAction SilentlyContinue
  $done = $false
  $err = $null

  for ($attempt=1; $attempt -le 2; $attempt++) {
    $env:MT5_CREDENTIALS = $originalCredentials
    try {
      & ./.github/scripts/tv26_strategy_cooldown_backtest.ps1
      if (!(Test-Path (Join-Path $results "strategy-backtest-summary.txt"))) { throw "Tester summary is missing." }
      $done = $true
      break
    } catch {
      $err = $_.Exception.Message
      $transient = $false
      $diag = Join-Path $results "diagnostics"
      if (Test-Path $diag) {
        $logs = Get-ChildItem -LiteralPath $diag -Filter "*.txt" -File -Recurse -ErrorAction SilentlyContinue
        foreach ($log in $logs) {
          if ((Get-Content -LiteralPath $log.FullName -Raw -ErrorAction SilentlyContinue) -match "(?i)no history data, stop testing|preliminary downloading of history ticks canceled") { $transient=$true; break }
        }
      }
      if ($attempt -ge 2 -or !$transient) { break }
      $saved = Join-Path $results "retry-attempt-1-diagnostics"
      if (Test-Path $saved) { Remove-Item $saved -Recurse -Force }
      if (Test-Path $diag) { Move-Item $diag $saved -Force }
      foreach ($pattern in @("TV26_Audit_XAUUSD_*.csv","TV26_OHLC_History_XAUUSD.csv","strategy-tester-report.html","data-integrity-report.*","formula-parity-report.*","formula-parity-details.csv")) {
        Get-ChildItem -LiteralPath $results -Filter $pattern -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
      }
      Remove-Item (Join-Path $results "diagnostic-logs") -Recurse -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 3
    }
  }

  if (!$done) {
    if (Test-Path $results) { Copy-Item (Join-Path $results "*") $stage -Recurse -Force -ErrorAction SilentlyContinue }
    "STAGE FAILURE: tester did not complete. $err" | Set-Content (Join-Path $stage "stage-status.txt") -Encoding utf8
    $rows.Add([pscustomobject]@{Days=$days;From=$from.ToString("yyyy-MM-dd");Through=$anchor.ToString("yyyy-MM-dd");Net="—";PF="—";DD="—";Trades="—";Losses="—";Audit="NOT RUN";Gate="TESTER FAILURE"})
    $technicalFailure=$true
    $stopReason="Stopped at $days day(s): MT5 tester failure; no longer window was run."
    break
  }
  Copy-Item (Join-Path $results "*") $stage -Recurse -Force

  try {
    $audit = Join-Path $stage ("TV26_Audit_XAUUSD_{0}.csv" -f $magic)
    $history = Join-Path $stage "TV26_OHLC_History_XAUUSD.csv"
    if (!(Test-Path $audit) -or !(Test-Path $history)) { throw "Required audit/history export missing." }
    & python trading-lab/tv26/validate_tv26_mt5_audit.py --csv $audit --report (Join-Path $stage "data-integrity-report.md") --json (Join-Path $stage "data-integrity-report.json")
    if ($LASTEXITCODE -ne 0) { throw "OHLC integrity audit failed." }
    & python trading-lab/tv26/reference_tv26_formulas.py --audit $audit --history $history --report (Join-Path $stage "formula-parity-report.md") --details (Join-Path $stage "formula-parity-details.csv") --json (Join-Path $stage "formula-parity-report.json")
    if ($LASTEXITCODE -ne 0) { throw "Independent indicator-formula audit failed." }

    $summary = Get-Content (Join-Path $stage "strategy-backtest-summary.txt") -Raw
    $net = MetricNumber $summary "Total Net Profit:"
    $pf = MetricNumber $summary "Profit Factor:"
    $trades = [int](MetricNumber $summary "Total Trades:")
    $losses = [int](MetricNumber $summary "Loss Trades (% of total):")
    $ddText = MetricText $summary "Equity Drawdown Maximal:"
    $ddMatch = [regex]::Match($ddText,'\(([0-9]+(?:\.[0-9]+)?)%\)')
    if (!$ddMatch.Success) { throw "Equity drawdown percentage missing." }
    $dd = [decimal]::Parse($ddMatch.Groups[1].Value,[Globalization.NumberStyles]::Float,$culture)

    if ($days -eq 1) {
      $required = [decimal]5.00
      $ddLimit = [decimal]1.00
      $pass = ($trades -ge 1) -and ($losses -eq 0) -and ($net -ge $required) -and ($dd -le $ddLimit)
      $rule = "one day: net >= 5.00 USD, at least 1 trade, zero losses, DD <= 1%"
    } else {
      $required = [decimal]2.50 * $days
      $ddLimit = [decimal][Math]::Min(5.0,[Math]::Max(2.0,[double]$days))
      $pass = ($trades -ge 1) -and ($net -ge $required) -and ($dd -le $ddLimit) -and (($losses -eq 0) -or ($pf -ge [decimal]1.15))
      $rule = "$days days: net >= average 2.50 USD/day, PF >= 1.15 if losses, DD <= $ddLimit%"
    }
    $gate = if ($pass) { "PASS — EXPAND" } else { "STOP — GATE FAILED" }
    $rows.Add([pscustomobject]@{Days=$days;From=$from.ToString("yyyy-MM-dd");Through=$anchor.ToString("yyyy-MM-dd");Net=("{0:F2}" -f $net);PF=("{0:F2}" -f $pf);DD=("{0:F2}%" -f $dd);Trades=$trades;Losses=$losses;Audit="PASS";Gate=$gate})
    @("Stage: $gate","Window: $($from.ToString('yyyy-MM-dd')) through $($anchor.ToString('yyyy-MM-dd'))","Net: $net; PF: $pf; equity DD: $dd%; trades: $trades; losses: $losses","Rule: $rule") | Set-Content (Join-Path $stage "stage-status.txt") -Encoding utf8
    Write-Output "Stage $days day(s): net=$net PF=$pf DD=$dd% trades=$trades losses=$losses => $gate"
    if (!$pass) { $stopReason="Stopped at $days day(s): profitability/risk gate not met; no longer window was run."; break }
    $lastPassed=$days
  } catch {
    $err=$_.Exception.Message
    "AUDIT/METRIC FAILURE: $err" | Set-Content (Join-Path $stage "stage-status.txt") -Encoding utf8
    $rows.Add([pscustomobject]@{Days=$days;From=$from.ToString("yyyy-MM-dd");Through=$anchor.ToString("yyyy-MM-dd");Net="—";PF="—";DD="—";Trades="—";Losses="—";Audit="FAIL";Gate="STOP — UNVERIFIED"})
    $technicalFailure=$true
    $stopReason="Stopped at $days day(s): audit or metric validation failed."
    break
  }
}

$report = [System.Collections.Generic.List[string]]::new()
$report.Add("# TV26 Progressive Daily Gate")
$report.Add("")
$report.Add("Anchor date: 2026-10-22. One day first, then 2, 3... up to 10 days backward from the same end date. Only a passing stage allows the next longer test.")
$report.Add("Settings: XAUUSD M1; Model 4; USD 500 starting deposit; 1% risk; SL 2 ATR; TP 4 ATR; M1 close-breakout enabled; M1 oscillator confirmation minimum $oscMin; tester-only guard; unique magic per stage.")
$report.Add("")
$report.Add("Gate: day 1 requires net >= 5.00 USD, at least one trade, zero losses and DD <= 1%. For stages >= 2 days: net >= 2.50 USD per tested day, at least one trade, PF >= 1.15 if losses exist, DD <= 1% per day capped at 5%. Every stage must pass both OHLC integrity and independent formula audits.")
$report.Add("")
$report.Add("| Days | From | Through | Net profit | PF | Equity DD | Trades | Losses | Audit | Decision |")
$report.Add("|---:|---|---|---:|---:|---:|---:|---:|---|---|")
foreach ($r in $rows) { $report.Add("| $($r.Days) | $($r.From) | $($r.Through) | $($r.Net) | $($r.PF) | $($r.DD) | $($r.Trades) | $($r.Losses) | $($r.Audit) | $($r.Gate) |") }
$report.Add("")
$report.Add("Stop reason: $stopReason")
$report.Add("Last passed stage: $lastPassed day(s).")
$report.Add("A passing screen is not proof of statistical robustness, direct live TradingView chart parity, or future profitability.")
$report | Set-Content (Join-Path $root "PROGRESSIVE_GATE_REPORT.md") -Encoding utf8
$report | Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Encoding utf8
if ($technicalFailure) { throw $stopReason }
