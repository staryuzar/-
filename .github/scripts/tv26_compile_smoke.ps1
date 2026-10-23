$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "tv26-compile"
$installDir = Join-Path $root "terminal"
$installer = Join-Path $root "mt5setup.exe"
$source = Join-Path $PWD "trading-lab\tv26\TV26_FiveTF_Arabic_CANDIDATE.mq5"
$pine = Join-Path $PWD "trading-lab\tv26\TradingView_Parity_5TF.pine"
$readme = Join-Path $PWD "trading-lab\tv26\README_AR.md"
$reportDir = Join-Path $PWD "tv26-results"
New-Item -ItemType Directory -Path $root,$installDir,$reportDir -Force | Out-Null
$report = Join-Path $reportDir "compile-report.txt"
"TV26 MetaEditor compile-only validation" | Set-Content -LiteralPath $report -Encoding utf8
"UTC start: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $report -Encoding utf8
if (-not (Test-Path -LiteralPath $source)) { throw "EA source not found: $source" }
if (-not (Test-Path -LiteralPath $pine)) { throw "Pine comparator not found: $pine" }
if (-not (Test-Path -LiteralPath $readme)) { throw "Arabic README not found: $readme" }

# Static regression audit: guard the known TechnicalRating v3 parity rules before compiling.
$sourceText = Get-Content -LiteralPath $source -Raw
$pineText = Get-Content -LiteralPath $pine -Raw
$auditChecks = @(
  @{ Name = "five timeframe inputs"; File = "EA"; Text = "#define N_TF 5" },
  @{ Name = "26-rating component set"; File = "EA"; Text = "#define N_RATINGS 26" },
  @{ Name = "Bulls Power EMA(13)"; File = "EA"; Text = "g_bulls[t]=iBullsPower(_Symbol,g_tfs[t],13);" },
  @{ Name = "Bears Power EMA(13)"; File = "EA"; Text = "g_bears[t]=iBearsPower(_Symbol,g_tfs[t],13);" },
  @{ Name = "Ichimoku Span A uses lead[26] on closed candle"; File = "EA"; Text = "g_handles[t][j],2,27,spanA" },
  @{ Name = "Ichimoku Span B uses lead[26] on closed candle"; File = "EA"; Text = "g_handles[t][j],3,27,spanB" },
  @{ Name = "ADX sell rule matches TechnicalRating v3 source"; File = "EA"; Text = "a>20 && b<c && a>prevADX ? -1" },
  @{ Name = "Momentum is close difference"; File = "EA"; Text = "double momNow=closes[0]-closes[10];" },
  @{ Name = "MACD signal uses EMA(9)"; File = "EA"; Text = "const double alpha=2.0/(9.0+1.0);" },
  @{ Name = "demo-only trade guard"; File = "EA"; Text = "if(InpDemoOnly && AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)" },
  @{ Name = "same-signal re-entry latch"; File = "EA"; Text = "sig==g_lastExecutedSignal" },
  @{ Name = "closed-candle component audit export"; File = "EA"; Text = "void ExportAuditIfNeeded()" },
  @{ Name = "Pine uses TechnicalRating v3"; File = "PINE"; Text = "import TradingView/TechnicalRating/3 as tvRating" },
  @{ Name = "Pine outputs prior confirmed rating bar"; File = "PINE"; Text = "[totalRating[1], maRating[1], oscillatorRating[1]]" },
  @{ Name = "Pine shifts values before lookahead_on"; File = "PINE"; Text = "lookahead=barmerge.lookahead_on" }
)
$auditFailures = @()
foreach ($check in $auditChecks) {
  $subject = if ($check.File -eq "PINE") { $pineText } else { $sourceText }
  if ($subject.Contains($check.Text)) {
    "STATIC AUDIT PASS: $($check.Name)" | Add-Content -LiteralPath $report -Encoding utf8
  } else {
    "STATIC AUDIT FAIL: $($check.Name) (missing expected expression)" | Add-Content -LiteralPath $report -Encoding utf8
    $auditFailures += $check.Name
  }
}
if ($auditFailures.Count -gt 0) {
  throw ("Static parity audit failed: " + ($auditFailures -join "; "))
}
"Static regression audit: PASS ($($auditChecks.Count) checks)" | Add-Content -LiteralPath $report -Encoding utf8

$uri = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
Invoke-WebRequest -Uri $uri -OutFile $installer -UseBasicParsing
"Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
$install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:$installDir") -PassThru -Wait
"Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
$editor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $editor) { throw "MetaEditor64.exe not found after installer run. Installer exit code: $($install.ExitCode)" }
$experts = Join-Path (Split-Path $editor.FullName -Parent) "MQL5\Experts"
New-Item -ItemType Directory -Path $experts -Force | Out-Null
$compileSource = Join-Path $experts "TV26_FiveTF_Arabic_CANDIDATE.mq5"
Copy-Item -LiteralPath $source -Destination $compileSource -Force
$compileLog = Join-Path $reportDir "metaeditor-compile.log"
$args = '/compile:"' + $compileSource + '" /log'
$p = Start-Process -FilePath $editor.FullName -ArgumentList $args -WorkingDirectory (Split-Path $editor.FullName -Parent) -PassThru
if (-not $p.WaitForExit(120000)) {
  try { $p.Kill() } catch {}
  throw "MetaEditor compile timed out after 120 seconds."
}
Start-Sleep -Seconds 2
$ex5 = [System.IO.Path]::ChangeExtension($compileSource, ".ex5")
$logs = @(Get-ChildItem -LiteralPath (Split-Path $editor.FullName -Parent) -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue |
  Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-10) } |
  Sort-Object LastWriteTime -Descending)
$lines = @()
foreach ($log in $logs) {
  try {
    $txt = Get-Content -LiteralPath $log.FullName -Raw -ErrorAction Stop
    if ($txt -match "TV26_FiveTF_Arabic_CANDIDATE|error|warning|Result:") {
      $lines += "===== $($log.FullName) ====="
      $lines += $txt
    }
  } catch {}
}
$lines | Set-Content -LiteralPath $compileLog -Encoding utf8
$lines | Add-Content -LiteralPath $report -Encoding utf8
if (-not (Test-Path -LiteralPath $ex5)) {
  "Compile result: FAIL - EX5 output missing" | Add-Content -LiteralPath $report -Encoding utf8
  throw "Compilation failed: EX5 output missing. See tv26-results artifacts."
}
$reportText = ($lines -join [Environment]::NewLine)
if ($reportText -match "(?i)\b[1-9]\d*\s+errors?\b") {
  "Compile result: FAIL - compiler log reports errors" | Add-Content -LiteralPath $report -Encoding utf8
  throw "Compilation failed: compiler log reports errors. See tv26-results artifacts."
}
if ($reportText -match "(?i)\b[1-9]\d*\s+warnings?\b") {
  "Compile result: FAIL - compiler log reports warnings" | Add-Content -LiteralPath $report -Encoding utf8
  throw "Compilation failed: compiler log reports warnings. See tv26-results artifacts."
}
$sourceText = Get-Content -LiteralPath $source -Raw
$versionMatch = [regex]::Match($sourceText, '#property\s+version\s+"([^"]+)"')
$version = if ($versionMatch.Success) { $versionMatch.Groups[1].Value } else { "unknown" }
$sourceCommit = (git rev-parse HEAD).Trim()
$ex5Bytes = (Get-Item $ex5).Length
"Compile result: PASS - 0 errors, 0 warnings" | Add-Content -LiteralPath $report -Encoding utf8
"EA version: $version" | Add-Content -LiteralPath $report -Encoding utf8
"Source commit: $sourceCommit" | Add-Content -LiteralPath $report -Encoding utf8
"EX5 bytes: $ex5Bytes" | Add-Content -LiteralPath $report -Encoding utf8
"UTC end: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $report -Encoding utf8

Copy-Item -LiteralPath $ex5 -Destination (Join-Path $reportDir "TV26_FiveTF_Arabic_CANDIDATE.ex5") -Force
Copy-Item -LiteralPath $source -Destination (Join-Path $reportDir "TV26_FiveTF_Arabic_CANDIDATE.mq5") -Force
Copy-Item -LiteralPath $pine -Destination (Join-Path $reportDir "TradingView_Parity_5TF.pine") -Force
Copy-Item -LiteralPath $readme -Destination (Join-Path $reportDir "README_AR.md") -Force
@"
TV26 Arabic candidate package
EA version: $version
Source commit: $sourceCommit
MetaEditor result: 0 errors, 0 warnings
EX5 bytes: $ex5Bytes

MT5 installation:
1. In MT5 choose File > Open Data Folder.
2. Open MQL5\Experts.
3. Copy TV26_FiveTF_Arabic_CANDIDATE.mq5 and TV26_FiveTF_Arabic_CANDIDATE.ex5 there.
4. Refresh Navigator > Expert Advisors or restart MT5.
5. Attach the EA to XAUUSD on an M1 chart. Its rating calculations default to M1/M5/M15/M30/H1.
6. Find TV26_Audit_<symbol>_<magic>.csv inside the terminal Common\Files folder after the EA runs.

Safety and validation:
- This package has compile proof only; no Strategy Tester or live TradingView parity result is implied.
- InpDemoOnly defaults to true; do not disable it until independent validation is complete.
- The Pine comparison script must be accepted by TradingView Pine Editor before being used as a reference.
"@ | Set-Content -LiteralPath (Join-Path $reportDir "PACKAGE_README_AR.txt") -Encoding utf8
Write-Output "TV26 package created: version $version, EX5 $ex5Bytes bytes, source $sourceCommit."
