# Installs the official MetaTrader 5 terminal into a temporary CI folder and smoke-tests launch.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Join-Path $env:RUNNER_TEMP "aurora-mt5-smoke"
$installDir = Join-Path $root "terminal"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Path $installDir, $logDir -Force | Out-Null
$report = Join-Path $logDir "mt5-smoke-report.txt"
$installer = Join-Path $root "mt5setup.exe"
$terminal = $null

try {
    "Aurora MT5 integration smoke test" | Set-Content -LiteralPath $report -Encoding utf8
    "UTC start: $([DateTime]::UtcNow.ToString('o'))" | Add-Content -LiteralPath $report -Encoding utf8
    "Source: official MetaTrader 5 installer (MetaQuotes)" | Add-Content -LiteralPath $report -Encoding utf8
    $uri = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    Invoke-WebRequest -Uri $uri -OutFile $installer -TimeoutSec 180
    if (!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000) {
        throw "Official installer download is missing or unexpectedly small."
    }
    "Installer bytes: $((Get-Item $installer).Length)" | Add-Content -LiteralPath $report -Encoding utf8
    $install = Start-Process -FilePath $installer -ArgumentList @("/auto", "/path:`"$installDir`"") -PassThru -Wait
    "Installer exit code: $($install.ExitCode)" | Add-Content -LiteralPath $report -Encoding utf8
    if ($install.ExitCode -ne 0) { "Installer returned nonzero; inspect the installed files before deciding whether installation failed." | Add-Content -LiteralPath $report -Encoding utf8 }

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal64.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter "terminal.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($null -eq $terminal) {
        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })
        $joinedEntries = $entries -join "; "
        "Install directory entries: $joinedEntries" | Add-Content -LiteralPath $report -Encoding utf8
        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."
    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Exercise the same launch/window-enumeration helpers used by the assistant. No account credentials are supplied.
    $sourceDir = Join-Path $PWD "ci_mt5_source"
    if (!(Test-Path (Join-Path $sourceDir "windows_tools.py"))) { throw "Assistant source was not extracted for the MT5 integration test." }
    $env:PYTHONPATH = $sourceDir
    python .github/scripts/mt5_assistant_launch_probe.py --source-dir "$sourceDir" --terminal-path "$($terminal.FullName)" --install-dir "$installDir" --report "$report"
    if ($LASTEXITCODE -ne 0) { throw "Aurora's launch_program integration probe failed." }
    "LIMIT: no broker login, demo account, EA compilation, Strategy Tester run, or trade was performed." | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
    throw
}
finally { }
