$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "goldlab-environment-preflight"
$install = Join-Path $root "terminal"
$reports = Join-Path $PWD "goldlab-environment-results"
New-Item -ItemType Directory -Path $install,$reports -Force | Out-Null
$summary = Join-Path $reports "environment-preflight.txt"
$started = [DateTime]::UtcNow
@("GoldLab environment preflight (no strategy test, no trade)","UTC start: $($started.ToString('o'))","Runner OS: $([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)","Runner architecture: $([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture)","Strategy source and inputs are not modified.") | Set-Content -LiteralPath $summary -Encoding utf8

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

@(
  "The separate GoldLab Advisor OrderCheck workflow verifies Headway connectivity during the actual Strategy Tester run.",
  "This preflight does not change strategy source, tester parameters, or the protected holdout period.",
  "UTC end: $([DateTime]::UtcNow.ToString('o'))",
  "Environment preflight: PASS (MT5 installed, Terminal and MetaEditor found, independent MQL5 smoke EA compiled with 0 errors)."
) | Add-Content -LiteralPath $summary -Encoding utf8
Get-Content $summary
