$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "goldlab-mt5"
$install = Join-Path $root "terminal"
$reports = Join-Path $PWD "goldlab-results"
New-Item -ItemType Directory -Path $install,$reports -Force | Out-Null
$installer = Join-Path $root "mt5setup.exe"
$summary = Join-Path $reports "run-summary.txt"
$credentialRaw = [string]$env:MT5_CREDENTIALS
if ([string]::IsNullOrWhiteSpace($credentialRaw)) { throw "Missing Actions secret 'mt5'; no MT5 tester run attempted." }

$accountLogin = ""; $accountPassword = ""; $accountServer = "mt5.demo.trade-hw.online"
$credentialObject = $null
if ($credentialRaw.TrimStart().StartsWith("{")) {
  try { $credentialObject = ConvertFrom-Json -InputObject $credentialRaw -ErrorAction Stop } catch { $credentialObject = $null }
}
if ($null -ne $credentialObject) {
  $accountLogin = [string]$credentialObject.login
  if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$credentialObject.account }
  $accountPassword = [string]$credentialObject.password
  if (-not [string]::IsNullOrWhiteSpace([string]$credentialObject.server)) { $accountServer = [string]$credentialObject.server }
} else {
  $lines = @($credentialRaw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
  $fields = @{}
  foreach ($line in $lines) {
    if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$') { $fields[$matches[1].ToLowerInvariant()] = $matches[2] }
  }
  if ($fields.ContainsKey("login") -or $fields.ContainsKey("account") -or $fields.ContainsKey("password")) {
    $accountLogin = [string]$fields["login"]
    if ([string]::IsNullOrWhiteSpace($accountLogin)) { $accountLogin = [string]$fields["account"] }
    $accountPassword = [string]$fields["password"]
    if (-not [string]::IsNullOrWhiteSpace([string]$fields["server"])) { $accountServer = [string]$fields["server"] }
  } elseif ($lines.Count -ge 2) {
    $accountLogin = [string]$lines[0]; $accountPassword = [string]$lines[1]
    if ($lines.Count -ge 3) { $accountServer = [string]$lines[2] }
  }
}
if ($accountLogin -notmatch '^\d{4,20}$' -or [string]::IsNullOrWhiteSpace($accountPassword)) {
  throw "Invalid MT5 secret format. Expected JSON login/password/server or separate login and password lines; values suppressed."
}
Write-Output "::add-mask::$accountLogin"
Write-Output "::add-mask::$accountPassword"
Write-Output "::add-mask::$accountServer"
$accountPasswordForConfig = $accountPassword
$credentialRaw = $null; $credentialObject = $null; $fields = $null; $lines = $null

"GoldLab MT5 Strategy Tester run" | Set-Content -LiteralPath $summary -Encoding utf8
"Test date: 2026-09-01" | Add-Content -LiteralPath $summary -Encoding utf8
"EA: GoldLabEA v0.10; Symbol XAUUSD; timeframe M5; model 4 (real ticks when broker data is available)" | Add-Content -LiteralPath $summary -Encoding utf8
"Deposit: 500 USD; leverage 1:1000; trade mode is tester only; no live orders are authorized." | Add-Content -LiteralPath $summary -Encoding utf8
"UTC start: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $summary -Encoding utf8

try {
  $url = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
  Invoke-WebRequest -Uri $url -OutFile $installer -TimeoutSec 180
  if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) { throw "Official MT5 installer missing or too small." }
  $proc = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$install`"") -PassThru -Wait
  $terminal = Get-ChildItem -LiteralPath $install -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  $editor = Get-ChildItem -LiteralPath $install -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if (!$terminal -or !$editor) { throw "MT5 terminal or MetaEditor not found after install (installer exit $($proc.ExitCode))." }
  "MT5 version: $((Get-Item $terminal.FullName).VersionInfo.ProductVersion)" | Add-Content -LiteralPath $summary -Encoding utf8

  $expertDir = Join-Path $install "MQL5\Experts\GoldLab"
  New-Item -ItemType Directory -Path $expertDir -Force | Out-Null
  $source = Join-Path $PWD "trading-lab\gold-xauusd\GoldLabEA.mq5"
  if (!(Test-Path $source)) { throw "GoldLabEA.mq5 source missing." }
  $eaPath = Join-Path $expertDir "GoldLabEA.mq5"
  Copy-Item -LiteralPath $source -Destination $eaPath -Force
  $compileLog = Join-Path $expertDir "GoldLabEA.log"
  $compile = Start-Process -FilePath $editor.FullName -ArgumentList ('/compile:"' + $eaPath + '" /log') -WorkingDirectory $install -PassThru
  if (!$compile.WaitForExit(90000)) { Stop-Process -Id $compile.Id -Force -ErrorAction SilentlyContinue; throw "MetaEditor compile timed out." }
  Start-Sleep -Seconds 2
  if (!(Test-Path $compileLog)) { throw "MetaEditor compile log not produced." }
  $compileText = Get-Content -LiteralPath $compileLog -Raw
  $safeCompile = $compileText -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]" -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
  $safeCompile | Set-Content -LiteralPath (Join-Path $reports "compile-log.txt") -Encoding utf8
  if (!(Test-Path (Join-Path $expertDir "GoldLabEA.ex5")) -or $compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') {
    throw "EA compilation did not confirm zero errors. See sanitized compile-log.txt."
  }
  "Compile result: PASS (0 errors; warnings reported in compile-log.txt)" | Add-Content -LiteralPath $summary -Encoding utf8

  $config = Join-Path $root "goldlab-tester.ini"
  $reportRelative = "goldlab-results\GoldLab_baseline_2026-09-01"
  New-Item -ItemType Directory -Path (Join-Path $install "goldlab-results") -Force | Out-Null
  $ini = @"
[Common]
Login=$accountLogin
Password=$accountPasswordForConfig
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
Symbol=XAUUSD
Period=M5
Model=4
ExecutionMode=0
Optimization=0
FromDate=2026.09.01
ToDate=2026.09.01
ForwardMode=0
Deposit=500
Currency=USD
Leverage=1:1000
Report=$reportRelative
ReplaceReport=1
ShutdownTerminal=1
UseLocal=1
UseRemote=0
UseCloud=0
Visual=0
"@
  [System.IO.File]::WriteAllText($config,$ini,[System.Text.UTF8Encoding]::new($false))
  $env:MT5_CREDENTIALS = $null
  $accountPasswordForConfig = $null
  $terminalProc = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", "/config:$config") -WorkingDirectory $install -PassThru
  if (!$terminalProc.WaitForExit(900000)) {
    Stop-Process -Id $terminalProc.Id -Force -ErrorAction SilentlyContinue
    throw "Tester run exceeded 15 minutes; no completed result accepted."
  }
  $possibleReports = @(
    (Join-Path $install ($reportRelative + ".htm")),
    (Join-Path $install ($reportRelative + ".html")),
    (Join-Path $PWD ($reportRelative + ".htm")),
    (Join-Path $PWD ($reportRelative + ".html"))
  )
  $foundReport = $possibleReports | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (!$foundReport) {
    "Tester report: NOT FOUND" | Add-Content -LiteralPath $summary -Encoding utf8
    "This is a failed/incomplete test, not a zero-trade result." | Add-Content -LiteralPath $summary -Encoding utf8
    throw "MT5 did not produce the expected Strategy Tester report."
  }
  $html = Get-Content -LiteralPath $foundReport -Raw
  $html = $html -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]"
  $html = $html -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
  $safeReport = Join-Path $reports "GoldLab_baseline_2026-09-01.htm"
  [System.IO.File]::WriteAllText($safeReport,$html,[System.Text.UTF8Encoding]::new($false))
  "Tester report: produced at $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $summary -Encoding utf8
  "Report size: $((Get-Item $safeReport).Length) bytes" | Add-Content -LiteralPath $summary -Encoding utf8

  # Copy candidate logs/reports, but redact account identifier before artifact upload.
  $logCandidates = @()
  $logCandidates += Get-ChildItem -LiteralPath $install -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue
  $logCandidates += Get-ChildItem -LiteralPath (Join-Path $env:APPDATA "MetaQuotes\Terminal") -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue
  $logsOut = Join-Path $reports "logs"
  New-Item -ItemType Directory -Path $logsOut -Force | Out-Null
  $idx=0
  foreach ($lf in ($logCandidates | Sort-Object LastWriteTime -Descending | Select-Object -First 20)) {
    try {
      $raw = Get-Content -LiteralPath $lf.FullName -Raw -ErrorAction Stop
      $raw = $raw -replace [regex]::Escape($accountLogin), "[ACCOUNT REDACTED]"
      $raw = $raw -replace [regex]::Escape($accountServer), "[SERVER REDACTED]"
      $raw = $raw -replace '(?i)(password|passwd)\s*[:=]\s*\S+', '$1=[REDACTED]'
      $idx++; $raw | Set-Content -LiteralPath (Join-Path $logsOut ("mt5-log-{0:D2}.txt" -f $idx)) -Encoding utf8
    } catch { }
  }
  "UTC finish: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $summary -Encoding utf8
  "IMPORTANT: only the generated tester report and journal can establish whether trades were actually simulated. Missing report or missing history means FAIL/incomplete, not success." | Add-Content -LiteralPath $summary -Encoding utf8
  Get-Content -LiteralPath $summary
}
finally {
  $env:MT5_CREDENTIALS = $null
  $accountPasswordForConfig = $null
  if (Test-Path (Join-Path $root "goldlab-tester.ini")) { Remove-Item (Join-Path $root "goldlab-tester.ini") -Force -ErrorAction SilentlyContinue }
}
