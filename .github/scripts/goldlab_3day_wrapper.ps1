$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Three-day diagnostic override. This edits only the checked-out runner workspace;
# it does not change the committed production/test script in the repository.
$scriptPath = ".github/scripts/goldlab_mt5_test.ps1"
if (!(Test-Path -LiteralPath $scriptPath)) { throw "GoldLab tester script not found." }
$content = Get-Content -LiteralPath $scriptPath -Raw

$changes = @(
  @("2026-09-01 through 2026-10-19 (short-side-only diagnostic)", "2026-09-01 through 2026-09-03 (3-day short-side-only diagnostic)"),
  @("GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-10-19", "GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-09-03"),
  @("ToDate=2026.10.19", "ToDate=2026.09.03"),
  @("GoldLab_spreadsafe_stop045_diagnostic_2026-09-01_to_2026-10-19", "GoldLab_shortonly_adx40_stop045_2026-09-01_to_2026-09-03")
)
foreach ($change in $changes) {
  if (!$content.Contains($change[0])) { throw "Expected tester date/report marker not found; refusing to run an unverified date range." }
  $content = $content.Replace($change[0], $change[1])
}

Set-Content -LiteralPath $scriptPath -Value $content -Encoding utf8
$verified = Get-Content -LiteralPath $scriptPath -Raw
if ($verified -notmatch 'FromDate=2026\.09\.01\s*\r?\nToDate=2026\.09\.03' -or
    $verified -notmatch '2026-09-01 through 2026-09-03' -or
    $verified -notmatch 'InpAllowLong=false') {
  throw "Three-day tester configuration verification failed."
}
Write-Output "Verified diagnostic period: 2026-09-01 through 2026-09-03; short-only; ADX 18-40; 0.50% target risk; 0.45 ATR stop."
& $scriptPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
