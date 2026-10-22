$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "goldlab-environment-preflight"
$install = Join-Path $root "terminal"
$reports = Join-Path $PWD "goldlab-environment-results"
New-Item -ItemType Directory -Path $install,$reports -Force | Out-Null
$summary = Join-Path $reports "environment-preflight.txt"
$started = [DateTime]::UtcNow
@("GoldLab environment preflight (no strategy test, no trade)","UTC start: $($started.ToString('o'))","Runner OS: $([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)","Runner architecture: $([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture)","Strategy source and inputs are not modified.") | Set-Content -LiteralPath $summary -Encoding utf8

$credentialRaw = [string]$env:MT5_CREDENTIALS
if ([string]::IsNullOrWhiteSpace($credentialRaw)) { throw "Missing Actions secret 'mt5'; account-connectivity check cannot run." }
$credentialObject = $null
try { $credentialObject = ConvertFrom-Json -InputObject $credentialRaw -ErrorAction Stop } catch { }
$login = ""; $password = ""; $server = "mt5.demo.trade-hw.online"
if ($null -ne $credentialObject) {
  $login = [string]$credentialObject.login
  if ([string]::IsNullOrWhiteSpace($login)) { $login = [string]$credentialObject.account }
  $password = [string]$credentialObject.password
  if (![string]::IsNullOrWhiteSpace([string]$credentialObject.server)) { $server = [string]$credentialObject.server }
} else {
  $lines = @($credentialRaw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  $fields = @{}
  foreach ($line in $lines) { if ($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$') { $fields[$matches[1].ToLowerInvariant()] = $matches[2] } }
  if ($fields.ContainsKey("login") -or $fields.ContainsKey("account")) {
    $login = [string]$fields["login"]; if (!$login) { $login = [string]$fields["account"] }
    $password = [string]$fields["password"]; if ($fields["server"]) { $server = [string]$fields["server"] }
  } elseif ($lines.Count -ge 2) {
    $login = [string]$lines[0]; $password = [string]$lines[1]; if ($lines.Count -ge 3) { $server = [string]$lines[2] }
  }
}
if ($login -notmatch '^\d{4,20}$' -or [string]::IsNullOrWhiteSpace($password)) { throw "Invalid MT5 secret format; values are suppressed." }
Write-Output "::add-mask::$login"
Write-Output "::add-mask::$password"
Write-Output "::add-mask::$server"
$credentialRaw = $null; $credentialObject = $null; $fields = $null; $lines = $null

$installer = Join-Path $root "mt5setup.exe"
Invoke-WebRequest -Uri "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" -OutFile $installer -TimeoutSec 180
if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) { throw "Official MT5 installer missing or too small." }
$setup = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:$install") -PassThru -Wait
$terminal = Get-ChildItem -LiteralPath $install -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$editor = Get-ChildItem -LiteralPath $install -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$terminal -or !$editor) { throw "MT5 terminal or MetaEditor not found after installation; installer exit=$($setup.ExitCode)." }
"MT5 terminal version: $((Get-Item $terminal.FullName).VersionInfo.ProductVersion)" | Add-Content $summary -Encoding utf8
"MetaEditor version: $((Get-Item $editor.FullName).VersionInfo.ProductVersion)" | Add-Content $summary -Encoding utf8

$smokeDir = Join-Path $install "MQL5\Experts\GoldLabEnvironmentSmoke"
New-Item -ItemType Directory -Path $smokeDir -Force | Out-Null
$smokeSource = Join-Path $smokeDir "EnvironmentSmoke.mq5"
$smokeLog = Join-Path $smokeDir "EnvironmentSmoke.log"
$smokeText = @'
#property strict
#property version "1.00"
int OnInit()
{
   Print("GoldLab environment compile smoke test; no trade logic.");
   return(INIT_SUCCEEDED);
}
void OnTick() {}
'@
[System.IO.File]::WriteAllText($smokeSource,$smokeText,[System.Text.UTF8Encoding]::new($false))
$compiler = Start-Process -FilePath $editor.FullName -ArgumentList ('/compile:"' + $smokeSource + '" /log') -WorkingDirectory $install -PassThru
if (!$compiler.WaitForExit(90000)) { Stop-Process -Id $compiler.Id -Force -ErrorAction SilentlyContinue; throw "MetaEditor smoke compile timed out." }
Start-Sleep -Seconds 2
if (!(Test-Path $smokeLog)) { throw "MetaEditor smoke compile log was not produced." }
$compileText = Get-Content -LiteralPath $smokeLog -Raw
$totals = [regex]::Match($compileText,'(?im)^\s*Result:\s*(\d+)\s+errors,\s*(\d+)\s+warnings')
if (!$totals.Success) { throw "Could not parse MetaEditor smoke compile result." }
$errors = [int]$totals.Groups[1].Value
$warnings = [int]$totals.Groups[2].Value
if (!(Test-Path (Join-Path $smokeDir "EnvironmentSmoke.ex5")) -or $errors -ne 0) { throw "MetaEditor smoke compile failed: errors=$errors warnings=$warnings." }
@("MetaEditor smoke compile: PASS","Compile errors: $errors","Compile warnings: $warnings") | Add-Content $summary -Encoding utf8
$compileText | Set-Content (Join-Path $reports "compile-smoke-log.txt") -Encoding utf8

$config = Join-Path $root "login-preflight.ini"
$ini = @"
[Common]
Login=$login
Password=$password
Server=$server
ProxyEnable=0
KeepPrivate=1
NewsEnable=0
CertInstall=0

[Experts]
Enabled=0
AllowLiveTrading=0
AllowDllImport=0
"@
[System.IO.File]::WriteAllText($config,$ini,[System.Text.UTF8Encoding]::new($false))
$password = $null
$proc = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable", "/config:$config") -WorkingDirectory $install -PassThru
Start-Sleep -Seconds 45
$terminalLogs = Join-Path $install "logs"
$logs = @()
if (Test-Path $terminalLogs) { $logs = @(Get-ChildItem -LiteralPath $terminalLogs -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 8) }
$logText = ($logs | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue }) -join [Environment]::NewLine
$loginRedacted = $logText -replace [regex]::Escape($login), "[ACCOUNT REDACTED]" -replace [regex]::Escape($server), "[SERVER REDACTED]"
$loginRedacted = $loginRedacted -replace '(?i)(password|passwd)\s*[:=]\s*\S+', '$1=[REDACTED]'
$loginRedacted | Set-Content (Join-Path $reports "terminal-login-log-sanitized.txt") -Encoding utf8
if ($logText -match '(?i)authorization on .* successful|authorized on .* successful|connected to .*successfully|connection established') {
  "Headway demo login evidence: PASS (success marker found; no trade/tester launched)." | Add-Content $summary -Encoding utf8
} else {
  "Headway demo login evidence: INCONCLUSIVE (no recognized success marker in recent logs)." | Add-Content $summary -Encoding utf8
  if ($proc -and !$proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  throw "Terminal/compiler setup passed, but demo login could not be confirmed from recognized log markers."
}
if ($proc -and !$proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
"UTC end: $([DateTime]::UtcNow.ToString('o'))" | Add-Content $summary -Encoding utf8
"Environment preflight: PASS (MT5 installed, MetaEditor smoke compile passed, demo login success marker found; no strategy test and no trade)." | Add-Content $summary -Encoding utf8
Get-Content $summary
