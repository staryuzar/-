$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $projectRoot "mql5\BitcoinIntelligenceLabEA.mq5"
$artifactDir = Join-Path $projectRoot "artifacts"
$root = Join-Path $env:RUNNER_TEMP "btc-mt5-compile"
$installDir = Join-Path $root "terminal"
$installer = Join-Path $root "mt5setup.exe"
$report = Join-Path $artifactDir "mql5_compile_report.txt"

New-Item -ItemType Directory -Path $installDir,$artifactDir -Force | Out-Null
if (!(Test-Path -LiteralPath $source)) { throw "BitcoinIntelligenceLabEA.mq5 source file was not found." }

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("Bitcoin Intelligence Lab — MetaEditor compile-only check")
$lines.Add("UTC start: $([DateTime]::UtcNow.ToString('o'))")
$lines.Add("Source: mql5/BitcoinIntelligenceLabEA.mq5")
$lines.Add("Mode: compile only; no terminal launch, account login, EA attachment or trade execution.")

try {
    $uri = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    Invoke-WebRequest -Uri $uri -OutFile $installer -TimeoutSec 180
    if (!(Test-Path -LiteralPath $installer) -or (Get-Item -LiteralPath $installer).Length -lt 100000) {
        throw "Official MetaTrader installer is missing or unexpectedly small."
    }
    $lines.Add("Installer bytes: $((Get-Item -LiteralPath $installer).Length)")

    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    $lines.Add("Installer exit code: $($install.ExitCode)")
    if ($install.ExitCode -ne 0) {
        $lines.Add("Installer returned nonzero; installed binaries are still checked before failure is declared.")
    }

    $metaEditor = Get-ChildItem -LiteralPath $installDir -Filter "metaeditor64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $metaEditor) { throw "MetaEditor64.exe was not found after official MT5 installation." }
    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) { throw "Terminal64.exe was not found after official MT5 installation." }

    $expertsDir = Join-Path (Split-Path -Parent $metaEditor.FullName) "MQL5\Experts"
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir "BitcoinIntelligenceLabEA.mq5"
    $eaBinary = Join-Path $expertsDir "BitcoinIntelligenceLabEA.ex5"
    $compileLog = Join-Path $expertsDir "BitcoinIntelligenceLabEA.log"
    Copy-Item -LiteralPath $source -Destination $eaSource -Force
    Remove-Item -LiteralPath $eaBinary,$compileLog -Force -ErrorAction SilentlyContinue

    $lines.Add("MetaEditor path: $($metaEditor.FullName)")
    $lines.Add("Terminal path: $($terminal.FullName)")
    $lines.Add("Terminal build: $((Get-Item -LiteralPath $terminal.FullName).VersionInfo.ProductVersion)")

    $compileArgs = '/compile:"' + $eaSource + '" /log'
    $compiler = Start-Process -FilePath $metaEditor.FullName -ArgumentList $compileArgs -WorkingDirectory (Split-Path -Parent $metaEditor.FullName) -PassThru
    if (!$compiler.WaitForExit(90000)) {
        Stop-Process -Id $compiler.Id -Force -ErrorAction SilentlyContinue
        throw "MetaEditor compilation timed out after 90 seconds."
    }
    Start-Sleep -Seconds 1

    if (!(Test-Path -LiteralPath $compileLog)) { throw "MetaEditor did not create the expected compile log." }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    $lines.Add("MetaEditor compile log:")
    $lines.Add($compileText.Trim())
    if (!(Test-Path -LiteralPath $eaBinary) -or (Get-Item -LiteralPath $eaBinary).Length -le 0) {
        throw "MetaEditor did not produce a non-empty BitcoinIntelligenceLabEA.ex5 file."
    }
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -notmatch '(?i)0 warnings' -or $compileText -match '(?i)[1-9][0-9]* (errors|warnings)') {
        throw "EA compilation must report zero errors and zero warnings."
    }

    Copy-Item -LiteralPath $eaBinary -Destination (Join-Path $artifactDir "BitcoinIntelligenceLabEA.ex5") -Force
    Copy-Item -LiteralPath $compileLog -Destination (Join-Path $artifactDir "BitcoinIntelligenceLabEA_metaeditor.log") -Force
    $lines.Add("Compiled EX5 bytes: $((Get-Item -LiteralPath $eaBinary).Length)")
    $lines.Add("RESULT: PASS — BitcoinIntelligenceLabEA.mq5 compiled with zero errors and zero warnings.")
    $lines.Add("UTC end: $([DateTime]::UtcNow.ToString('o'))")
    $lines | Set-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
}
catch {
    $lines.Add("RESULT: FAIL — $($_.Exception.Message)")
    $lines.Add("UTC end: $([DateTime]::UtcNow.ToString('o'))")
    $lines | Set-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
    throw
}
