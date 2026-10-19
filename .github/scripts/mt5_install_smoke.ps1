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
$process = $null

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
    if ($null -eq $terminal) {\n        $entries = @(Get-ChildItem -LiteralPath $installDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { $_.FullName })\n        "Install directory entries: $($entries -join "; ")" | Add-Content -LiteralPath $report -Encoding utf8\n        throw "Installer exit code $($install.ExitCode); terminal64.exe/terminal.exe was not found in the requested install directory."\n    }
    "Terminal path: $($terminal.FullName)" | Add-Content -LiteralPath $report -Encoding utf8
    $version = (Get-Item -LiteralPath $terminal.FullName).VersionInfo
    "Product version: $($version.ProductVersion)" | Add-Content -LiteralPath $report -Encoding utf8
    "File version: $($version.FileVersion)" | Add-Content -LiteralPath $report -Encoding utf8

    # Use a disposable installation and no login/account parameters. No trading account is connected.
    $process = Start-Process -FilePath $terminal.FullName -ArgumentList @("/portable") -WorkingDirectory $installDir -PassThru
    Start-Sleep -Seconds 15
    $stillRunning = $null -ne (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)
    "Launch PID: $($process.Id)" | Add-Content -LiteralPath $report -Encoding utf8
    "Terminal process alive after 15s: $stillRunning" | Add-Content -LiteralPath $report -Encoding utf8
    if (!$stillRunning) { throw "MetaTrader terminal process exited during startup smoke test." }

    "RESULT: PASS — official installer installed a terminal executable and it remained running for 15 seconds." | Add-Content -LiteralPath $report -Encoding utf8
    "LIMIT: this is an installation/process smoke test, not a GUI interaction, broker login, demo-account, Expert Advisor compilation, or Strategy Tester result." | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
}
catch {
    "RESULT: FAIL — $($_.Exception.Message)" | Add-Content -LiteralPath $report -Encoding utf8
    Get-Content -LiteralPath $report
    throw
}
finally {
    if ($null -ne $process) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}
