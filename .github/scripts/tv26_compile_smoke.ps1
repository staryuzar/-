$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "tv26-compile"
$installDir = Join-Path $root "terminal"
$installer = Join-Path $root "mt5setup.exe"
$source = Join-Path $PWD "trading-lab\tv26\TV26_FiveTF_Arabic_CANDIDATE.mq5"
$reportDir = Join-Path $PWD "tv26-results"
New-Item -ItemType Directory -Path $root,$installDir,$reportDir -Force | Out-Null
$report = Join-Path $reportDir "compile-report.txt"
"TV26 MetaEditor compile-only validation" | Set-Content -LiteralPath $report -Encoding utf8
"UTC start: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $report -Encoding utf8
if (-not (Test-Path -LiteralPath $source)) { throw "EA source not found: $source" }
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
"Compile result: EX5 generated; inspect full compiler log for exact warnings/errors." | Add-Content -LiteralPath $report -Encoding utf8
"EX5 bytes: $((Get-Item $ex5).Length)" | Add-Content -LiteralPath $report -Encoding utf8
"UTC end: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $report -Encoding utf8
Write-Output "TV26 compile smoke completed; artifact report saved."
