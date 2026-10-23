$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "goldlab-dukascopy-mt5"
$install = Join-Path $root "terminal"
$reports = Join-Path $PWD "goldlab-results"
New-Item -ItemType Directory -Path $install,$reports -Force | Out-Null

$credentialRaw = [string]$env:MT5_CREDENTIALS
if ([string]::IsNullOrWhiteSpace($credentialRaw)) { throw "Missing MT5_CREDENTIALS." }
$accountLogin = ""; $accountPassword = ""; $accountServer = "mt5.demo.trade-hw.online"
$credentialObject = $null
if ($credentialRaw.TrimStart().StartsWith("{")) { try { $credentialObject = ConvertFrom-Json -InputObject $credentialRaw -ErrorAction Stop } catch { $credentialObject = $null } }
if ($null -ne $credentialObject) {
  $accountLogin = [string]$credentialObject.login
  if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$credentialObject.account }
  $accountPassword = [string]$credentialObject.password
  if (-not [string]::IsNullOrWhiteSpace([string]$credentialObject.server)) { $accountServer = [string]$credentialObject.server }
} else {
  $lines = @($credentialRaw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
  $fields = @{}
  foreach ($line in $lines) { if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$') { $fields[$matches[1].ToLowerInvariant()] = $matches[2] } }
  if ($fields.ContainsKey("login") -or $fields.ContainsKey("account") -or $fields.ContainsKey("password")) {
    $accountLogin = [string]$fields["login"]; if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$fields["account"] }
    $accountPassword = [string]$fields["password"]; if ($fields.ContainsKey("server")) { $accountServer = [string]$fields["server"] }
  } elseif ($lines.Count -ge 2) { $accountLogin = [string]$lines[0]; $accountPassword = [string]$lines[1]; if ($lines.Count -ge 3) { $accountServer = [string]$lines[2] } }
}
if ($accountLogin -notmatch '^\d{4,20}$' -or [string]::IsNullOrWhiteSpace($accountPassword)) { throw "Invalid MT5 secret format; values suppressed." }
Write-Output "::add-mask::$accountLogin"; Write-Output "::add-mask::$accountPassword"; Write-Output "::add-mask::$accountServer"
$credentialRaw = $null; $credentialObject = $null; $fields = $null; $lines = $null

$diagnosticsDir = Join-Path $reports "diagnostics"
New-Item -ItemType Directory -Path $diagnosticsDir -Force | Out-Null
function Save-MT5Diagnostics {
  $candidates = @()
  $roots = @($install,(Join-Path $env:APPDATA "MetaQuotes\Terminal"))
  foreach ($r in $roots) {
    if (!(Test-Path -LiteralPath $r)) { continue }
    try {
      $candidates += @(Get-ChildItem -LiteralPath $r -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".log",".txt") } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 20)
    } catch {}
  }
  $unique = @($candidates | Sort-Object LastWriteTime -Descending | Select-Object -Unique -First 30)
  $i = 0
  foreach ($item in $unique) {
    try {
      $rawLog = Get-Content -LiteralPath $item.FullName -Raw -ErrorAction Stop
      $rawLog = $rawLog -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]"
      $rawLog = $rawLog -replace [regex]::Escape($accountPassword), "[PASSWORD REDACTED]"
      $rawLog = $rawLog -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
      $rawLog = $rawLog -replace '(?i)(password|passwd)\s*[:=]\s*\S+', '$1=[REDACTED]'
      $i++
      $rawLog | Set-Content -LiteralPath (Join-Path $diagnosticsDir ("mt5-diagnostic-{0:D2}.txt" -f $i)) -Encoding utf8
    } catch {}
  }
  @(
    "MT5 diagnostics captured at $([DateTime]::UtcNow.ToString('o'))",
    "Candidate log files copied: $i",
    "Install directory: $install",
    "Portable mode requested for both importer and tester: true"
  ) | Set-Content -LiteralPath (Join-Path $diagnosticsDir "diagnostic-manifest.txt") -Encoding utf8
}

$tickSource = Get-ChildItem -LiteralPath (Join-Path $PWD "external-ticks") -Filter "xauusd-tick-2026-03-26-2026-03-27.csv" -File -Recurse | Select-Object -First 1
$ratesSource = Get-ChildItem -LiteralPath (Join-Path $PWD "dukascopy-warmup") -Filter "*.csv" -File -Recurse | Select-Object -First 1
if (!$tickSource -or !$ratesSource) { throw "External tick artifact or M1 warm-up CSV is missing." }

$installer = Join-Path $root "mt5setup.exe"
Invoke-WebRequest -Uri "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" -OutFile $installer -TimeoutSec 180
if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) { throw "Official MT5 installer missing or too small." }
$proc = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:$install") -PassThru -Wait
$terminal = Get-ChildItem -LiteralPath $install -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$editor = Get-ChildItem -LiteralPath $install -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$terminal -or !$editor) { throw "MT5 terminal or MetaEditor missing after install (exit $($proc.ExitCode))." }

$expertDir = Join-Path $install "MQL5\Experts\GoldLab"
$scriptDir = Join-Path $install "MQL5\Scripts\GoldLab"
$filesDir = Join-Path $install "MQL5\Files"
$testerSetDir = Join-Path $install "MQL5\Profiles\Tester"
New-Item -ItemType Directory -Path $expertDir,$scriptDir,$filesDir,$testerSetDir,(Join-Path $install "goldlab-results") -Force | Out-Null
$eaSource = Join-Path $PWD "trading-lab\gold-xauusd\GoldLabEA.mq5"
$importSource = Join-Path $PWD "trading-lab\gold-xauusd\DukascopyCustomSymbolImport.mq5"
$eaPath = Join-Path $expertDir "GoldLabEA.mq5"
$importPath = Join-Path $scriptDir "DukascopyCustomSymbolImport.mq5"
Copy-Item -LiteralPath $eaSource -Destination $eaPath -Force
Copy-Item -LiteralPath $importSource -Destination $importPath -Force
Copy-Item -LiteralPath $tickSource.FullName -Destination (Join-Path $filesDir "dukascopy-tick.csv") -Force
Copy-Item -LiteralPath $ratesSource.FullName -Destination (Join-Path $filesDir "dukascopy-m1.csv") -Force

function Compile-Mql5([string]$sourcePath,[string]$logPath) {
  $p = Start-Process -FilePath $editor.FullName -ArgumentList ('/compile:"' + $sourcePath + '" /log') -WorkingDirectory $install -PassThru
  if (!$p.WaitForExit(90000)) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; throw "MetaEditor compile timed out." }
  Start-Sleep -Seconds 2
  $candidate = [System.IO.Path]::ChangeExtension($sourcePath,".log")
  if (!(Test-Path $candidate)) { throw "MetaEditor compile log missing for $sourcePath." }
  $raw = Get-Content -LiteralPath $candidate -Raw
  $raw | Set-Content -LiteralPath $logPath -Encoding utf8
  if ($raw -notmatch '(?i)Result:\s*0 errors,\s*0 warnings' -or !(Test-Path ([System.IO.Path]::ChangeExtension($sourcePath,".ex5")))) { throw "Compilation was not clean; see $logPath." }
}
Compile-Mql5 $eaPath (Join-Path $reports "compile-ea-log.txt")
Compile-Mql5 $importPath (Join-Path $reports "compile-importer-log.txt")

$importIni = Join-Path $root "dukascopy-import.ini"
$importConfig = @"
[Common]
Login=$accountLogin
Password=$accountPassword
Server=$accountServer
ProxyEnable=0
KeepPrivate=1
NewsEnable=0
CertInstall=0

[Experts]
Enabled=1
AllowLiveTrading=0
AllowDllImport=0

[StartUp]
Script=GoldLab\DukascopyCustomSymbolImport
Symbol=XAUUSD
Period=M1
ShutdownTerminal=1
"@
[System.IO.File]::WriteAllText($importIni,$importConfig,[System.Text.UTF8Encoding]::new($false))
$resultFile = Join-Path $filesDir "dukascopy-import-result.txt"
if (Test-Path $resultFile) { Remove-Item $resultFile -Force }
$p = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", ('/config:"' + $importIni + '"')) -WorkingDirectory $install -PassThru
if (!$p.WaitForExit(240000)) {
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  Save-MT5Diagnostics
  throw "MT5 importer exceeded four-minute timeout; sanitized terminal logs were captured."
}
if (!(Test-Path $resultFile)) {
  Save-MT5Diagnostics
  $nearby = @(Get-ChildItem -LiteralPath $install -Filter "dukascopy-import-result.txt" -File -Recurse -ErrorAction SilentlyContinue)
  ("Importer result missing. Expected portable Files path: $resultFile; same-name results elsewhere: $($nearby.Count)") | Add-Content -LiteralPath (Join-Path $diagnosticsDir "diagnostic-manifest.txt") -Encoding utf8
  throw "Importer result file missing after portable startup; sanitized terminal logs were captured."
}
Copy-Item -LiteralPath $resultFile -Destination (Join-Path $reports "dukascopy-import-result.txt") -Force
$importSummary = Get-Content -LiteralPath $resultFile -Raw
if ($importSummary -notmatch '(?m)^status=PASS\s*$' -or $importSummary -notmatch '(?m)^ticks_imported=480416\s*$' -or $importSummary -notmatch '(?m)^rates_bad_rows=0\s*$') { throw "Custom-symbol import validation failed." }

$setName = "GoldLabDukascopy.set"
$setPath = Join-Path $testerSetDir $setName
$setContent = @"
InpMagic=2026102301||2026102301||1||2026102301||N
InpEntryTF=5||5||1||5||N
InpBiasTF=16385||16385||1||16385||N
InpRiskPercent=0.5||0.5||0.1||0.5||N
InpFastEMA=20||20||1||20||N
InpSlowEMA=50||50||1||50||N
InpBiasFastEMA=50||50||1||50||N
InpBiasSlowEMA=200||200||1||200||N
InpRSIPeriod=14||14||1||14||N
InpRSIMidline=50.0||50.0||1.0||50.0||N
InpADXPeriod=14||14||1||14||N
InpMinADX=23.0||23.0||1.0||23.0||N
InpMaxADX=25.0||25.0||1.0||25.0||N
InpAllowLong=false||true||0||true||N
InpMaxSpreadPoints=1000.0||1000.0||10.0||1000.0||N
InpATRPeriod=14||14||1||14||N
InpStopATR=0.45||0.45||0.05||0.45||N
InpStopRetryBufferATR=0.50||0.50||0.05||0.50||N
InpTargetATR=2.4||2.4||0.1||2.4||N
InpTrailATR=1.4||1.4||0.1||1.4||N
InpCloseOnOpposite=true||false||0||true||N
InpWriteTradeCSV=true||false||0||true||N
InpRequireSignalCandleDirection=true||true||0||true||N
InpRequireFastEMARejection=true||true||0||true||N
InpTestForceInvalidStopsOnce=false||false||0||true||N
"@
[System.IO.File]::WriteAllText($setPath,$setContent,[System.Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath $setPath -Destination (Join-Path $reports $setName) -Force

$testerIni = Join-Path $root "dukascopy-tester.ini"
$testerConfig = @"
[Common]
Login=$accountLogin
Password=$accountPassword
Server=$accountServer
ProxyEnable=0
KeepPrivate=1
NewsEnable=0
CertInstall=0

[Experts]
Enabled=1
AllowLiveTrading=0
AllowDllImport=0

[Tester]
Expert=GoldLab\GoldLabEA.ex5
ExpertParameters=$setName
Symbol=XAUUSD_DUKA
Period=M5
Login=$accountLogin
Deposit=500
Currency=USD
Leverage=1:1000
Model=4
ExecutionMode=-1
FromDate=2026.03.26
ToDate=2026.03.27
Report=goldlab-results\GoldLab_Dukascopy_customsymbol_2026-03-26
ReplaceReport=1
ShutdownTerminal=1
"@
[System.IO.File]::WriteAllText($testerIni,$testerConfig,[System.Text.UTF8Encoding]::new($false))
$testProc = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", ('/config:"' + $testerIni + '"')) -WorkingDirectory $install -PassThru
if (!$testProc.WaitForExit(600000)) {
  Stop-Process -Id $testProc.Id -Force -ErrorAction SilentlyContinue
  Save-MT5Diagnostics
  throw "Custom-symbol Strategy Tester exceeded ten-minute timeout; sanitized terminal logs were captured."
}
$report = Get-ChildItem -LiteralPath $install -Filter "GoldLab_Dukascopy_customsymbol_2026-03-26.htm" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$report) { $report = Get-ChildItem -LiteralPath $install -Filter "GoldLab_Dukascopy_customsymbol_2026-03-26.html" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 }
if (!$report) { Save-MT5Diagnostics; throw "No custom-symbol Strategy Tester HTML report was produced; sanitized terminal logs were captured." }
$reportOut = Join-Path $reports "GoldLab_Dukascopy_customsymbol_2026-03-26.htm"
Copy-Item -LiteralPath $report.FullName -Destination $reportOut -Force
$html = Get-Content -LiteralPath $reportOut -Raw
$checks = @(
  ($html -match '(?is)Symbol:</td>\s*<td[^>]*><b>XAUUSD_DUKA</b>'),
  ($html -match '(?is)InpMaxSpreadPoints=1000(?:\.0+)?</b>'),
  ($html -match '(?is)InpStopRetryBufferATR=0\.5(?:0+)?</b>'),
  ($html -match '(?is)InpTestForceInvalidStopsOnce=false</b>'),
  ($qualityMatch.Success -and $qualityMatch.Groups[1].Value.Trim() -eq "100% real ticks"),
  ($html -match '(?is)Period:</td>\s*<td[^>]*><b>M5 \(2026\.03\.26 - 2026\.03\.27\)</b>')
)
if ($checks -contains $false) { throw "Tester report failed custom-symbol/input/date verification." }
$barMatch = [regex]::Match($html,'(?is)Bars:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
$qualityMatch = [regex]::Match($html,'(?is)History Quality:</td>\s*<td[^>]*><b>\s*([^<]+?)\s*</b>')
$tickMatch = [regex]::Match($html,'(?is)Ticks:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
$tradeMatch = [regex]::Match($html,'(?is)Total Trades:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
$dealMatch = [regex]::Match($html,'(?is)Total Deals:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
$netMatch = [regex]::Match($html,'(?is)Total Net Profit:</td>\s*<td[^>]*><b>\s*([-+\d,.]+)\s*</b>')
$pfMatch = [regex]::Match($html,'(?is)Profit Factor:</td>\s*<td[^>]*><b>\s*([\d,.]+)\s*</b>')
$historyQuality = if($qualityMatch.Success){$qualityMatch.Groups[1].Value.Trim()}else{"UNKNOWN"}
$bars = if($barMatch.Success){[long]$barMatch.Groups[1].Value.Replace(",","")}else{-1}
$ticks = if($tickMatch.Success){[long]$tickMatch.Groups[1].Value.Replace(",","")}else{-1}
$trades = if($tradeMatch.Success){[long]$tradeMatch.Groups[1].Value.Replace(",","")}else{-1}
$deals = if($dealMatch.Success){[long]$dealMatch.Groups[1].Value.Replace(",","")}else{-1}
$net = if($netMatch.Success){[double]::Parse($netMatch.Groups[1].Value,[Globalization.CultureInfo]::InvariantCulture)}else{[double]::NaN}
$pf = if($pfMatch.Success){[double]::Parse($pfMatch.Groups[1].Value,[Globalization.CultureInfo]::InvariantCulture)}else{[double]::NaN}
if ($historyQuality -ne "100% real ticks" -or $bars -lt 200 -or $ticks -lt 400000 -or $trades -lt 0 -or $deals -lt 0 -or [double]::IsNaN($net)) { throw "Custom-symbol report data gates failed (quality=$historyQuality bars=$bars ticks=$ticks trades=$trades deals=$deals net=$net)." }

$auditFiles = @(Get-ChildItem -LiteralPath $install -Filter "GoldLab_trade_audit.csv" -File -Recurse -ErrorAction SilentlyContinue)
$csvRows = 0; $csvNet = 0.0; $csvIds = [System.Collections.Generic.HashSet[string]]::new()
Save-MT5Diagnostics

if ($auditFiles.Count -gt 0) {
  $auditOut = Join-Path $reports "trade-audit"; New-Item -ItemType Directory -Path $auditOut -Force | Out-Null
  $index = 0
  foreach ($audit in $auditFiles) {
    $index++; $dest = Join-Path $auditOut ("GoldLab_trade_audit-{0:D2}.csv" -f $index); Copy-Item -LiteralPath $audit.FullName -Destination $dest -Force
    foreach ($row in @(Import-Csv -LiteralPath $dest)) {
      if ([string]::IsNullOrWhiteSpace([string]$row.deal)) { continue }
      $csvRows++
      if (!$csvIds.Add([string]$row.deal)) { throw "Duplicate deal ID in custom-symbol audit CSV." }
      $csvNet += [double]::Parse([string]$row.profit,[Globalization.CultureInfo]::InvariantCulture)
      $csvNet += [double]::Parse([string]$row.commission,[Globalization.CultureInfo]::InvariantCulture)
      $csvNet += [double]::Parse([string]$row.swap,[Globalization.CultureInfo]::InvariantCulture)
    }
  }
}
if ($deals -gt 0 -and ($csvRows -ne $deals -or [Math]::Abs([Math]::Round($csvNet,2)-[Math]::Round($net,2)) -gt 0.05)) { throw "Custom-symbol HTML/CSV reconciliation failed." }

@(
  "GoldLab v1.018 — Dukascopy custom-symbol import and tester smoke test",
  "EA SHA-256: $((Get-FileHash -LiteralPath $eaSource -Algorithm SHA256).Hash.ToLowerInvariant())",
  "Importer SHA-256: $((Get-FileHash -LiteralPath $importSource -Algorithm SHA256).Hash.ToLowerInvariant())",
  "Data source: Dukascopy ticks plus Dukascopy M1 warm-up bars; NOT Headway broker history.",
  "Symbol: XAUUSD_DUKA; digits=3; point=0.001; spread cap=1000 points ($1.00 nominal).",
  "Model=4; Random Delay; tester covers 2026.03.26 only (ToDate 2026.03.27 is exclusive), matching the one-day imported tick sample.",
  "Compile: EA and importer both 0 errors/0 warnings.",
  "Import summary: $importSummary",
  "History quality=$historyQuality; report bars=$bars ticks=$ticks trades=$trades deals=$deals net=$net PF=$pf.",
  "CSV rows=$csvRows unique IDs=$($csvIds.Count) CSV net=$([Math]::Round($csvNet,2)).",
  "Interpretation: ingestion/strategy smoke test on an independent custom symbol, not broker execution or profitability validation."
) | Set-Content -LiteralPath (Join-Path $reports "dukascopy-custom-symbol-test-summary.txt") -Encoding utf8
Get-Content -LiteralPath (Join-Path $reports "dukascopy-custom-symbol-test-summary.txt")
