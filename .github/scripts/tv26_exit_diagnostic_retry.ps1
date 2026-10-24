$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Retry at most once, and only when the preserved terminal log proves that MT5
# aborted because broker tick history download was canceled. Never retry a
# strategy loss, invalid audit, compile error, or arbitrary tester failure.
$runner = Join-Path $PWD ".github/scripts/tv26_strategy_backtest.ps1"
$results = Join-Path $PWD "tv26-strategy-results"
$firstAttempt = Join-Path $PWD "tv26-exit-diagnostic-attempt-1"
$credentials = [string]$env:MT5_CREDENTIALS
if (!(Test-Path -LiteralPath $runner)) { throw "TV26 Strategy Tester runner is missing." }

try {
  & $runner
}
catch {
  $firstError = $_.Exception.Message
  $logFiles = @(Get-ChildItem -LiteralPath $results -Filter "*.txt" -File -Recurse -ErrorAction SilentlyContinue)
  $logText = ($logFiles | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue }) -join "`n"
  $historyCancelled = ($logText -match "preliminary downloading of history ticks canceled") -and
                      ($logText -match "no history data, stop testing") -and
                      ($firstError -match "audit CSV was not found")
  if (!$historyCancelled) {
    throw
  }

  if (Test-Path -LiteralPath $firstAttempt) {
    Remove-Item -LiteralPath $firstAttempt -Recurse -Force
  }
  if (Test-Path -LiteralPath $results) {
    Move-Item -LiteralPath $results -Destination $firstAttempt
  }
  @(
    "# MT5 history-download retry",
    "",
    "Attempt 1 ended without an audit CSV because the MT5 log explicitly reported canceled preliminary tick-history download and 'no history data, stop testing'.",
    "This is an infrastructure-only retry, not a strategy-performance retry.",
    "Original error: $firstError",
    "UTC retry start: $([DateTime]::UtcNow.ToString('o'))"
  ) | Set-Content -LiteralPath (Join-Path $firstAttempt "retry-note.md") -Encoding utf8

  # The main runner intentionally clears this variable in its finally block.
  $env:MT5_CREDENTIALS = $credentials
  & $runner

  $expectedSummary = Join-Path $results "strategy-backtest-summary.txt"
  if (!(Test-Path -LiteralPath $expectedSummary)) {
    throw "Retry finished without a Strategy Tester summary."
  }
  @(
    "",
    "Retry note: an earlier attempt was discarded by MT5 during broker tick-history download; the final report above is from the single allowed retry.",
    "UTC retry finish: $([DateTime]::UtcNow.ToString('o'))"
  ) | Add-Content -LiteralPath $expectedSummary -Encoding utf8
}
finally {
  $env:MT5_CREDENTIALS = $null
}
