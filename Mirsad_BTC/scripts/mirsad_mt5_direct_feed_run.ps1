#requires -Version 5.1
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$root = Join-Path $env:RUNNER_TEMP 'mirsad-mt5-observer-check'
$installDir = Join-Path $root 'terminal'
$evidence = Join-Path $root 'evidence'
New-Item -ItemType Directory -Path $installDir, $evidence -Force | Out-Null
$report = Join-Path $evidence 'mirsad-observer-report.txt'
$installer = Join-Path $root 'mt5setup.exe'
$loginConfig = $null
$terminalProcess = $null
$credentialRaw = [string]$env:MT5_CREDENTIALS
$accountPassword = $null

function Add-Report([string]$Line) {
    $Line | Add-Content -LiteralPath $report -Encoding utf8
}

function Get-CommonObserverDirectory {
    $candidates = @(
        (Join-Path $installDir 'Common\Files\MirsadBTC\observer'),
        (Join-Path $installDir 'Terminal\Common\Files\MirsadBTC\observer'),
        (Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC\observer'),
        (Join-Path $env:LOCALAPPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC\observer')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }

    $roots = @(
        (Join-Path $installDir 'Common\Files'),
        (Join-Path $installDir 'Terminal\Common\Files'),
        (Join-Path $env:APPDATA 'MetaQuotes\Terminal'),
        (Join-Path $env:LOCALAPPDATA 'MetaQuotes\Terminal')
    ) | Where-Object { Test-Path -LiteralPath $_ }

    foreach ($searchRoot in $roots) {
        $found = Get-ChildItem -LiteralPath $searchRoot -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -like 'capture_*.json' -or
                $_.Name -in @('candles.json','indicators.json','observer_status.json')
            } |
            Where-Object { $_.Directory.Name -eq 'observer' -and $_.Directory.Parent.Name -eq 'MirsadBTC' } |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($found) { return $found.Directory.FullName }
    }
    return $null
}

function Get-ObserverStatusSnapshot {
    $candidates = @(
        (Join-Path $installDir 'Common\Files\MirsadBTC\observer\observer_status.json'),
        (Join-Path $installDir 'Terminal\Common\Files\MirsadBTC\observer\observer_status.json'),
        (Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC\observer\observer_status.json'),
        (Join-Path $env:LOCALAPPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC\observer\observer_status.json')
    )
    if ($observerDir) {
        $candidates = @((Join-Path $observerDir 'observer_status.json')) + $candidates
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (!(Test-Path -LiteralPath $candidate)) { continue }
        try {
            return (Get-Content -LiteralPath $candidate -Raw | ConvertFrom-Json -ErrorAction Stop)
        }
        catch {
            return $null
        }
    }
    return $null
}

function Test-HeadwayAuthorizationLog {
    $logRoots = @(
        (Join-Path $installDir 'Logs'),
        (Join-Path $installDir 'MQL5\Logs'),
        (Join-Path $installDir 'Terminal\Logs'),
        (Join-Path $installDir 'Terminal\MQL5\Logs')
    ) | Where-Object { Test-Path -LiteralPath $_ }

    foreach ($logRoot in $logRoots) {
        $logs = Get-ChildItem -LiteralPath $logRoot -Filter '*.log' -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 12
        foreach ($logFile in $logs) {
            if ($logFile.LastWriteTimeUtc -lt $loginStarted.AddSeconds(-3)) { continue }
            $content = Get-Content -LiteralPath $logFile.FullName -Raw -ErrorAction SilentlyContinue
            if ([string]::IsNullOrWhiteSpace($content)) { continue }
            foreach ($line in ($content -split "\r?\n")) {
                if ($line -match '(?i)(Headway-Demo|mt5\.demo\.trade-hw\.online)' -and
                    $line -match '(?i)(authorized on|successfully authorized|authorization successful|login successful)' -and
                    $line -notmatch '(?i)(failed|invalid|not authorized|authorization error)') {
                    return $true
                }
            }
        }
    }
    return $false
}

function Add-ObserverDiagnostics {
    Add-Report ("Terminal process alive: {0}" -f [bool]($terminalProcess -and !$terminalProcess.HasExited))

    $statusCandidates = @()
    if ($observerDir) {
        $statusCandidates += (Join-Path $observerDir 'observer_status.json')
    }
    $statusCandidates += @(
        (Join-Path $installDir 'Common\Files\MirsadBTC\observer\observer_status.json'),
        (Join-Path $installDir 'Terminal\Common\Files\MirsadBTC\observer\observer_status.json'),
        (Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC\observer\observer_status.json'),
        (Join-Path $env:LOCALAPPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC\observer\observer_status.json')
    )
    foreach ($statusPath in ($statusCandidates | Select-Object -Unique)) {
        if (!(Test-Path -LiteralPath $statusPath)) { continue }
        try {
            $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json -ErrorAction Stop
            Add-Report ("Observer EA status: state={0}; symbol={1}; timeframe={2}; message={3}" -f $status.state,$status.symbol,$status.timeframe,$status.message)
        }
        catch {
            Add-Report ("Observer EA status file exists but could not be parsed: {0}" -f $_.Exception.Message)
        }
        break
    }

    $logRoots = @(
        (Join-Path $installDir 'Logs'),
        (Join-Path $installDir 'MQL5\Logs'),
        (Join-Path $installDir 'Terminal\Logs'),
        (Join-Path $installDir 'Terminal\MQL5\Logs')
    ) | Where-Object { Test-Path -LiteralPath $_ }

    foreach ($logRoot in $logRoots) {
        $latestLogs = Get-ChildItem -LiteralPath $logRoot -Filter '*.log' -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 2
        foreach ($logFile in $latestLogs) {
            $matches = Get-Content -LiteralPath $logFile.FullName -ErrorAction SilentlyContinue |
                Select-String -Pattern '(?i)(Mirsad|expert|authorization|authorized|connection|failed|cannot|error|invalid|BTC|screenshot|chart)'
            foreach ($match in ($matches | Select-Object -Last 30)) {
                $line = [string]$match.Line
                if (-not [string]::IsNullOrWhiteSpace($login)) {
                    $line = $line.Replace($login, '[masked-login]')
                }
                if (-not [string]::IsNullOrWhiteSpace($server)) {
                    $line = $line.Replace($server, '[broker-server]')
                }
                $line = [regex]::Replace($line, '(?<!\d)\d{5,}(?!\d)', '[numeric-id]')
                if ($line -match '(?i)password\s*[:=]') { continue }
                Add-Report ("MT5 log [{0}]: {1}" -f $logFile.Name,$line)
            }
        }
    }
}

try {
    'Mirsad Chart Observer — isolated MT5 read-only account connection test' | Set-Content -LiteralPath $report -Encoding utf8
    Add-Report ("UTC start: {0}" -f [DateTime]::UtcNow.ToString('o'))
    Add-Report 'Mode: read-only Observer EA only. No execution EA, no trading commands, no MIR1 writes.'

    # Hosted Windows runners may start with a small virtual desktop. A
    # maximized terminal cannot enlarge its chart beyond that desktop. Request
    # a larger display before launching MT5; native viewport dimensions remain
    # the authoritative quality gate even if this request is unavailable.
    try {
        Import-Module ServerManager -ErrorAction SilentlyContinue
        $displayCommand = Get-Command Set-DisplayResolution -ErrorAction SilentlyContinue
        if ($displayCommand) {
            Set-DisplayResolution -Width 1920 -Height 1080 -Force -ErrorAction Stop
            Start-Sleep -Seconds 2
            Add-Report 'PASS — Hosted display resolution set to 1920x1080 before MT5 launch.'
        }
        else {
            Add-Report 'WARN — Set-DisplayResolution is unavailable; native MT5 viewport dimensions remain the authoritative quality gate.'
        }
    }
    catch {
        Add-Report ("WARN — Could not change hosted display resolution: {0}. Native viewport quality gate remains active." -f $_.Exception.Message)
    }

    if ([string]::IsNullOrWhiteSpace($credentialRaw)) {
        throw "Repository Actions secret 'mt5' is unavailable."
    }

    $login = ''
    $accountPassword = ''
    $server = [string]$env:MIRSAD_MT5_SERVER
    $observerSymbol = [string]$env:MIRSAD_MT5_OBSERVER_SYMBOL
    $observerTimeframe = [string]$env:MIRSAD_MT5_OBSERVER_TIMEFRAME
    $obj = $null
    if ($credentialRaw.TrimStart().StartsWith('{')) {
        try { $obj = ConvertFrom-Json -InputObject $credentialRaw -ErrorAction Stop }
        catch { throw 'MT5 secret JSON is invalid.' }
    }

    if ($null -ne $obj) {
        $login = [string]$obj.login
        if ([string]::IsNullOrWhiteSpace($login)) { $login = [string]$obj.account }
        $accountPassword = [string]$obj.password
        if (-not [string]::IsNullOrWhiteSpace([string]$obj.server)) { $server = [string]$obj.server }
        if ([string]::IsNullOrWhiteSpace($observerSymbol) -and -not [string]::IsNullOrWhiteSpace([string]$obj.symbol)) { $observerSymbol = [string]$obj.symbol }
        if ([string]::IsNullOrWhiteSpace($observerTimeframe) -and -not [string]::IsNullOrWhiteSpace([string]$obj.timeframe)) { $observerTimeframe = [string]$obj.timeframe }
    }
    else {
        $lines = @($credentialRaw -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
        $fields = @{}
        foreach ($line in $lines) {
            if ($line -match '(?i)^(login|account|password|server|symbol|timeframe)\s*[:=]\s*(.*)$') {
                $fields[$matches[1].ToLowerInvariant()] = $matches[2]
            }
        }
        if ($fields.ContainsKey('login') -or $fields.ContainsKey('account') -or $fields.ContainsKey('password')) {
            $login = [string]$fields['login']
            if ([string]::IsNullOrWhiteSpace($login)) { $login = [string]$fields['account'] }
            $accountPassword = [string]$fields['password']
            if (-not [string]::IsNullOrWhiteSpace([string]$fields['server'])) { $server = [string]$fields['server'] }
            if ([string]::IsNullOrWhiteSpace($observerSymbol) -and -not [string]::IsNullOrWhiteSpace([string]$fields['symbol'])) { $observerSymbol = [string]$fields['symbol'] }
            if ([string]::IsNullOrWhiteSpace($observerTimeframe) -and -not [string]::IsNullOrWhiteSpace([string]$fields['timeframe'])) { $observerTimeframe = [string]$fields['timeframe'] }
        }
        elseif ($lines.Count -ge 2) {
            $login = [string]$lines[0]
            $accountPassword = [string]$lines[1]
            if ($lines.Count -ge 3) { $server = [string]$lines[2] }
        }
        else {
            throw 'MT5 secret format is not recognized.'
        }
    }

    if ([string]::IsNullOrWhiteSpace($login) -or [string]::IsNullOrWhiteSpace($accountPassword)) {
        throw 'MT5 account login/password are incomplete.'
    }
    if ([string]::IsNullOrWhiteSpace($server)) {
        throw "MT5 server is missing. Set server=... in the mt5 secret or enter the broker's exact server name in the workflow input."
    }
    $server = $server.Trim()
    $observerSymbol = $observerSymbol.Trim()
    if ([string]::IsNullOrWhiteSpace($observerSymbol)) { $observerSymbol = 'BTC' }
    $observerTimeframe = $observerTimeframe.Trim().ToUpperInvariant()
    if ([string]::IsNullOrWhiteSpace($observerTimeframe)) { $observerTimeframe = 'M1' }
    # Do not restrict broker-specific symbols or the MT5 timeframe catalogue.
    # MT5 itself will report an unknown symbol/period during startup or CopyRates.
    Write-Output "::add-mask::$login"
    Write-Output "::add-mask::$accountPassword"
    Write-Output "::add-mask::$server"
    Add-Report ("MT5 server accepted: {0}. Account type is unrestricted; login values and password are masked and excluded from evidence." -f $server)
    Add-Report ("Observer target: {0},{1}." -f $observerSymbol, $observerTimeframe)

    $download = 'https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe'
    Invoke-WebRequest -Uri $download -OutFile $installer -TimeoutSec 240
    if (!(Test-Path -LiteralPath $installer) -or (Get-Item -LiteralPath $installer).Length -lt 100000) {
        throw 'Official MT5 installer download failed.'
    }

    $installArg = '/path:"' + $installDir + '"'
    $install = Start-Process -FilePath $installer -ArgumentList @('/auto', $installArg) -PassThru -Wait
    Add-Report ("MT5 installer process exit code: {0}" -f $install.ExitCode)

    $terminal = Get-ChildItem -LiteralPath $installDir -Filter 'terminal64.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (!$terminal) {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter 'terminal.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    $editor = Get-ChildItem -LiteralPath $installDir -Filter 'metaeditor64.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (!$terminal -or !$editor) { throw 'MT5 terminal or MetaEditor was not found after installer verification.' }
    Add-Report ("MetaTrader version: {0}" -f $terminal.VersionInfo.ProductVersion)

    $source = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\mt5\Mirsad_ChartObserver.mq5'
    if (!(Test-Path -LiteralPath $source)) { throw 'Mirsad Chart Observer source is missing.' }
    $sourceText = Get-Content -LiteralPath $source -Raw
    if ($sourceText -match '(?i)\b(OrderSend|OrderSendAsync|CTrade|PositionOpen|PositionClose)\s*\(') {
        throw 'Safety stop: read-only Observer source contains a trading API.'
    }
    if ($sourceText -match '(?im)^\s*#import\b') {
        throw 'Safety stop: Observer must not import external DLL functions.'
    }

    $expertsDir = Join-Path $installDir 'MQL5\Experts'
    New-Item -ItemType Directory -Path $expertsDir -Force | Out-Null
    $eaSource = Join-Path $expertsDir 'Mirsad_ChartObserver.mq5'
    $eaBinary = Join-Path $expertsDir 'Mirsad_ChartObserver.ex5'
    $compileLog = Join-Path $expertsDir 'Mirsad_ChartObserver.log'
    $directOnlySourceText = $sourceText.Replace(
        'input bool InpEnableImageCapture = true;',
        'input bool InpEnableImageCapture = false;'
    )
    if ($directOnlySourceText -eq $sourceText) {
        throw 'Direct-only EA build could not disable InpEnableImageCapture.'
    }
    [IO.File]::WriteAllText($eaSource, $directOnlySourceText, [Text.UTF8Encoding]::new($false))
    Add-Report 'PASS — Direct-only Observer build sets InpEnableImageCapture=false.'

    $compiler = Start-Process -FilePath $editor.FullName -ArgumentList ('/compile:"' + $eaSource + '" /log') -WorkingDirectory $installDir -PassThru
    if (!$compiler.WaitForExit(90000)) {
        Stop-Process -Id $compiler.Id -Force -ErrorAction SilentlyContinue
        throw 'MetaEditor Observer compilation timed out.'
    }
    Start-Sleep -Seconds 2
    if (!(Test-Path -LiteralPath $compileLog) -or !(Test-Path -LiteralPath $eaBinary)) {
        throw 'MetaEditor did not create the Observer compile log and EX5 binary.'
    }
    $compileText = Get-Content -LiteralPath $compileLog -Raw
    $compileText | Set-Content -LiteralPath (Join-Path $evidence 'Mirsad_ChartObserver_compile.log') -Encoding utf8
    if ($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors') {
        throw 'MetaEditor did not report zero Observer compile errors.'
    }
    if ($compileText -notmatch '(?i)0 warnings' -or $compileText -match '(?i)[1-9][0-9]* warnings') {
        throw 'MetaEditor did not report zero Observer compile warnings.'
    }
    Copy-Item -LiteralPath $eaBinary -Destination (Join-Path $evidence 'Mirsad_ChartObserver.ex5') -Force
    Add-Report ("PASS — Observer compiled with zero errors and zero warnings; EX5 bytes={0}." -f (Get-Item -LiteralPath $eaBinary).Length)

    $loginConfig = Join-Path $root 'mt5-observer-demo.ini'
    $ini = @"
[Common]
Login=$login
Password=$accountPassword
Server=$server
ProxyEnable=0
KeepPrivate=0
NewsEnable=0
CertInstall=0

[Experts]
Enabled=1
AllowLiveTrading=0
AllowDllImport=0

[Charts]
ProfileLast=Default
MaxBars=50000

[StartUp]
Expert=Mirsad_ChartObserver
Symbol=$observerSymbol
Period=$observerTimeframe
"@
    [IO.File]::WriteAllText($loginConfig, $ini, [Text.UTF8Encoding]::new($false))
    $accountPassword = $null
    $credentialRaw = $null
    $obj = $null

    $loginStarted = [DateTime]::UtcNow
    $terminalProcess = Start-Process -FilePath $terminal.FullName -ArgumentList @('/portable', "/config:$loginConfig", "/login:$login") -WorkingDirectory $installDir -PassThru
    Add-Report ("MT5 terminal launched with the read-only Observer on {0},{1}. Automated trading permission is disabled." -f $observerSymbol, $observerTimeframe)

    # Maximize the hosted terminal before the Observer's delayed first capture.
    if (-not ("MirsadNativeWindow" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class MirsadNativeWindow {
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    private delegate bool EnumWindowProc(IntPtr hwnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] private static extern IntPtr FindWindowEx(IntPtr parent, IntPtr childAfter, string className, string windowName);
    [DllImport("user32.dll")] private static extern IntPtr GetParent(IntPtr hwnd);
    [DllImport("user32.dll", CharSet=CharSet.Auto)] private static extern int GetClassName(IntPtr hwnd, StringBuilder className, int maxCount);
    [DllImport("user32.dll")] private static extern bool EnumChildWindows(IntPtr parent, EnumWindowProc callback, IntPtr lParam);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
    [StructLayout(LayoutKind.Sequential)]
    private struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    public static int MaximizeMdiChildren(IntPtr topWindow) {
        IntPtr mdi = FindWindowEx(topWindow, IntPtr.Zero, "MDIClient", null);
        if (mdi == IntPtr.Zero) return -1;
        var children = new List<IntPtr>();
        EnumWindowProc callback = (hwnd, lParam) => {
            if (GetParent(hwnd) == mdi) children.Add(hwnd);
            return true;
        };
        EnumChildWindows(mdi, callback, IntPtr.Zero);
        foreach (IntPtr child in children) PostMessage(mdi, 0x0225, child, IntPtr.Zero);
        return children.Count;
    }
    public static IntPtr GetMdiChildWindow(IntPtr chartWindow) {
        IntPtr current = chartWindow;
        for (int depth = 0; depth < 12 && current != IntPtr.Zero; depth++) {
            IntPtr parent = GetParent(current);
            if (parent == IntPtr.Zero) return IntPtr.Zero;
            var className = new StringBuilder(256);
            GetClassName(parent, className, className.Capacity);
            if (className.ToString() == "MDIClient") return current;
            current = parent;
        }
        return IntPtr.Zero;
    }
    public static bool MaximizeMdiChartWindow(IntPtr topWindow, IntPtr chartWindow) {
        IntPtr mdi = FindWindowEx(topWindow, IntPtr.Zero, "MDIClient", null);
        IntPtr mdiChild = GetMdiChildWindow(chartWindow);
        if (mdiChild == IntPtr.Zero || mdi == IntPtr.Zero)
            return ShowWindowAsync(chartWindow, 3);
        bool posted = PostMessage(mdi, 0x0225, mdiChild, IntPtr.Zero);
        bool shown = ShowWindowAsync(mdiChild, 3);
        SetForegroundWindow(mdiChild);
        return posted || shown;
    }
    public static string WindowChainText(IntPtr hwnd) {
        var parts = new List<string>();
        IntPtr current = hwnd;
        for (int depth = 0; depth < 8 && current != IntPtr.Zero; depth++) {
            var className = new StringBuilder(256);
            GetClassName(current, className, className.Capacity);
            parts.Add(className.ToString() + "[" + WindowRectText(current) + "]");
            current = GetParent(current);
        }
        return String.Join(" <- ", parts);
    }
    public static string WindowRectText(IntPtr hwnd) {
        RECT r;
        if (!GetWindowRect(hwnd, out r)) return "unavailable";
        return (r.Right-r.Left).ToString() + "x" + (r.Bottom-r.Top).ToString();
    }
}
"@
    }
    $windowDeadline = [DateTime]::UtcNow.AddSeconds(20)
    $terminalWindow = $null
    do {
        $terminalProcess.Refresh()
        if ($terminalProcess.MainWindowHandle -ne 0) { $terminalWindow = $terminalProcess; break }
        $terminalWindow = Get-Process -Name 'terminal64','terminal' -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne 0 -and $_.Path -eq $terminal.FullName } |
            Select-Object -First 1
        if (!$terminalWindow) { Start-Sleep -Seconds 1 }
    } while ([DateTime]::UtcNow -lt $windowDeadline)
    if ($terminalWindow) {
        [MirsadNativeWindow]::ShowWindowAsync($terminalWindow.MainWindowHandle, 3) | Out-Null
        [MirsadNativeWindow]::SetForegroundWindow($terminalWindow.MainWindowHandle) | Out-Null
        $windowRect = [MirsadNativeWindow]::WindowRectText($terminalWindow.MainWindowHandle)
        Add-Report ("PASS — MT5 main terminal maximized; main window={0}; HWND={1}." -f $windowRect,$terminalWindow.MainWindowHandle)

        # Wait for the Observer EA to publish the HWND of its exact BTC chart.
        $chartHandleDeadline = [DateTime]::UtcNow.AddSeconds(25)
        $observerChartStatus = $null
        do {
            $observerDir = Get-CommonObserverDirectory
            $observerChartStatus = Get-ObserverStatusSnapshot
            if ($observerChartStatus -and [long]$observerChartStatus.chart_window_handle -gt 0) { break }
            Start-Sleep -Seconds 1
        } while ([DateTime]::UtcNow -lt $chartHandleDeadline)
        $allMdiChildren = [MirsadNativeWindow]::MaximizeMdiChildren($terminalWindow.MainWindowHandle)
        if ($observerChartStatus -and [long]$observerChartStatus.chart_window_handle -gt 0) {
            $observerChartHwnd = [IntPtr]([long]$observerChartStatus.chart_window_handle)
            $mdiChartHwnd = [MirsadNativeWindow]::GetMdiChildWindow($observerChartHwnd)
            $targetedMaximize = [MirsadNativeWindow]::MaximizeMdiChartWindow($terminalWindow.MainWindowHandle,$observerChartHwnd)
            $directMaximize = $false
            if ($mdiChartHwnd -ne [IntPtr]::Zero) {
                $directMaximize = [MirsadNativeWindow]::ShowWindowAsync($mdiChartHwnd,3)
                [MirsadNativeWindow]::SetForegroundWindow($mdiChartHwnd) | Out-Null
            }
            Start-Sleep -Seconds 3
            if ($mdiChartHwnd -ne [IntPtr]::Zero) {
                $chartWindowRect = [MirsadNativeWindow]::WindowRectText($mdiChartHwnd)
            } else {
                $chartWindowRect = [MirsadNativeWindow]::WindowRectText($observerChartHwnd)
            }
            $chartHierarchy = [MirsadNativeWindow]::WindowChainText($observerChartHwnd)
            Add-Report ("PASS — MDI windows maximized={0}; targeted MDI maximize={1}; direct maximize={2}; chart HWND={3}; MDI child HWND={4}; MDI child rect={5}; hierarchy={6}; symbol={7}; timeframe={8}." -f $allMdiChildren,$targetedMaximize,$directMaximize,$observerChartHwnd,$mdiChartHwnd,$chartWindowRect,$chartHierarchy,$observerChartStatus.symbol,$observerChartStatus.timeframe)
        } else {
            Add-Report ("WARN — Observer chart HWND was not published; MDI windows maximized={0}; source viewport quality gate remains in force." -f $allMdiChildren)
        }
    } else {
        Add-Report 'WARN — MT5 main window handle was not found for maximize; Observer will still apply its viewport safety gate.'
    }
    $observerDir = $null
    $lastObserverStatus = $null
    $authorizationConfirmed = $false
    $nextLogScan = [DateTime]::MinValue
    # Login log scan started immediately before launching MT5.
    $marketSymbol = [string]$env:MIRSAD_MT5_MARKET_SYMBOL
    if ([string]::IsNullOrWhiteSpace($marketSymbol)) { $marketSymbol = 'BTCUSDT' }
    $marketSymbol = $marketSymbol.Trim()
    if ($marketSymbol.Length -gt 32) { throw 'Configured Mirsad market symbol is too long.' }
    $expectedAccountServer = [string]$env:MIRSAD_MT5_EXPECTED_ACCOUNT_SERVER
    if ([string]::IsNullOrWhiteSpace($expectedAccountServer)) {
        throw 'Expected MT5 account server is not configured for direct-feed validation.'
    }
    $expectedAccountServer = $expectedAccountServer.Trim()

    Add-Report 'Direct-only mode: chart screenshots and capture manifests are disabled.'
    $directFeedsReady = $false
    $directFeedData = @{}
    $directDeadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $directDeadline) {
        $observerDir = Get-CommonObserverDirectory
        if ((Get-Date) -ge $nextLogScan) {
            $authorizationConfirmed = Test-HeadwayAuthorizationLog
            $nextLogScan = (Get-Date).AddSeconds(9)
        }
        $statusSnapshot = Get-ObserverStatusSnapshot
        if ($statusSnapshot) { $lastObserverStatus = $statusSnapshot }

        if ($observerDir) {
            $marketPath = Join-Path (Split-Path -Parent $observerDir) 'market.json'
            $candlePath = Join-Path $observerDir 'candles.json'
            $indicatorPath = Join-Path $observerDir 'indicators.json'
            $paths = @{
                market = $marketPath
                candles = $candlePath
                indicators = $indicatorPath
            }
            $loaded = @{}
            $allPresent = $true
            foreach ($name in @('market','candles','indicators')) {
                $feedPath = $paths[$name]
                if (!(Test-Path -LiteralPath $feedPath)) {
                    $allPresent = $false
                    break
                }
                try {
                    $loaded[$name] = Get-Content -LiteralPath $feedPath -Raw | ConvertFrom-Json -ErrorAction Stop
                }
                catch {
                    $allPresent = $false
                    break
                }
            }

            if ($allPresent) {
                $market = $loaded.market
                $candles = $loaded.candles
                $indicators = $loaded.indicators
                $feedServer = [string]$market.account.server
                $serverOk = (
                    -not [string]::IsNullOrWhiteSpace($feedServer) -and
                    $feedServer -ieq $expectedAccountServer -and
                    [string]$candles.account.server -ieq $feedServer -and
                    [string]$indicators.account.server -ieq $feedServer
                )
                $identityOk = (
                    [bool]$market.terminal_connected -and
                    [bool]$candles.terminal_connected -and
                    [bool]$indicators.terminal_connected -and
                    [string]$market.broker_symbol -eq $observerSymbol -and
                    [string]$candles.broker_symbol -eq $observerSymbol -and
                    [string]$indicators.broker_symbol -eq $observerSymbol -and
                    [string]$market.market_symbol -eq $marketSymbol -and
                    [string]$candles.market_symbol -eq $marketSymbol -and
                    [string]$indicators.market_symbol -eq $marketSymbol
                )
                $schemaOk = (
                    [string]$market.schema -eq 'MIR-MT5-MARKET-2' -and
                    [string]$candles.schema -eq 'MIR-ENGINE2-CANDLES-1' -and
                    [string]$indicators.schema -eq 'MIR-MT5-INDICATORS-1'
                )
                $timeframesOk = (
                    @($candles.timeframes.PSObject.Properties).Count -eq 6 -and
                    @($indicators.timeframes.PSObject.Properties).Count -eq 6
                )
                $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
                $fresh = (
                    ($nowMs - [int64]$market.captured_at_utc_ms) -le 15000 -and
                    ($nowMs - [int64]$candles.captured_at_utc_ms) -le 15000 -and
                    ($nowMs - [int64]$indicators.captured_at_utc_ms) -le 15000
                )
                if ($serverOk -and $identityOk -and $schemaOk -and $timeframesOk -and $fresh) {
                    $directFeedData = $loaded
                    $directFeedsReady = $true
                    break
                }
            }
        }

        if ($terminalProcess.HasExited) {
            Add-Report 'MT5 terminal exited before direct data files became ready.'
            break
        }
        Start-Sleep -Seconds 2
    }

    if (!$directFeedsReady -or !$observerDir) {
        Add-Report ("Headway authorization detected in terminal logs: {0}" -f $authorizationConfirmed)
        if ($lastObserverStatus) {
            Add-Report ("Last Observer state: {0}; symbol={1}; timeframe={2}; message={3}" -f $lastObserverStatus.state,$lastObserverStatus.symbol,$lastObserverStatus.timeframe,$lastObserverStatus.message)
        }
        Add-ObserverDiagnostics
        throw 'Image-free direct MT5 feeds did not become fresh, connected and identity-matched within 180 seconds.'
    }
    Add-Report ("PASS — MT5 terminal feeds confirm an active account on {0}; authorization log match={1}." -f $feedServer,$authorizationConfirmed)
    foreach ($name in @('market','candles','indicators')) {
        $feedPath = switch ($name) {
            'market' { Join-Path (Split-Path -Parent $observerDir) 'market.json' }
            'candles' { Join-Path $observerDir 'candles.json' }
            'indicators' { Join-Path $observerDir 'indicators.json' }
        }
        Add-Report ("PASS — Direct feed present without image capture: {0}; schema={1}; bytes={2}." -f [IO.Path]::GetFileName($feedPath),$directFeedData[$name].schema,(Get-Item -LiteralPath $feedPath).Length)
    }

    $imageDir = Join-Path $observerDir 'images'
    $captureManifests = @(Get-ChildItem -LiteralPath $observerDir -Filter 'capture_*.json' -File -ErrorAction SilentlyContinue)
    $capturedImages = @()
    if (Test-Path -LiteralPath $imageDir) {
        $capturedImages = @(Get-ChildItem -LiteralPath $imageDir -Filter '*.png' -File -ErrorAction SilentlyContinue)
    }
    if ($captureManifests.Count -gt 0 -or $capturedImages.Count -gt 0) {
        throw 'Direct-only test found screenshot images or capture manifests; image capture was not fully disabled.'
    }
    Add-Report 'PASS — No chart PNGs or capture manifests were created during the direct-only test.'

    $commonFilesRoot = Split-Path -Parent (Split-Path -Parent $observerDir)
    $validator = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\validate_mt5_direct_feed.py'
    $directOutput = Join-Path $evidence 'direct-feed-validation.json'
    if (!(Test-Path -LiteralPath $validator)) {
        throw 'Direct MT5 feed validation script is missing.'
    }
    $validatorArgs = @(
        $validator,
        '--common-files', $commonFilesRoot,
        '--market-symbol', $marketSymbol,
        '--broker-symbol', $observerSymbol,
        '--expected-server', $feedServer,
        '--output', $directOutput
    )
    $validatorLines = & python @validatorArgs 2>&1
    $validatorExitCode = $LASTEXITCODE
    foreach ($line in $validatorLines) {
        Add-Report ("Direct feed validator: {0}" -f [string]$line)
    }
    if ($validatorExitCode -ne 0 -or !(Test-Path -LiteralPath $directOutput)) {
        throw 'Image-free direct MT5 feed reader validation failed.'
    }
    $directSummary = Get-Content -LiteralPath $directOutput -Raw | ConvertFrom-Json
    if ([string]$directSummary.status -ne 'READY') {
        throw 'Image-free direct MT5 feed summary is not READY.'
    }
    Add-Report ("PASS — Market feed={0}; OHLC candles={1}; native MT5 indicators={2}; ready frames={3}." -f $directSummary.market.status,$directSummary.candles.status,$directSummary.native_indicators.status,$directSummary.native_indicators.ready_timeframe_count)
    Add-Report ("Direct movement: quote ticks={0}; Last ticks={1}; volume updates={2}; depth={3}." -f $directSummary.market.quote_tick_count,$directSummary.market.last_price_tick_count,$directSummary.market.volume_update_count,$directSummary.market.depth_of_market_status)
    $priceActionAnalyzer = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\\scripts\\analyze_mt5_native_price_action.py'
    $priceActionOutput = Join-Path $evidence 'engine2-price-action-analysis.json'
    if (!(Test-Path -LiteralPath $priceActionAnalyzer)) {
        throw 'Engine 2 native price-action analysis script is missing.'
    }
    $priceActionArgs = @(
        $priceActionAnalyzer,
        '--common-files', $commonFilesRoot,
        '--market-symbol', $marketSymbol,
        '--broker-symbol', $observerSymbol,
        '--expected-server', $feedServer,
        '--output', $priceActionOutput
    )
    $priceActionLines = & python @trendArgs 2>&1
    $priceActionExitCode = $LASTEXITCODE
    foreach ($line in $priceActionLines) {
        Add-Report ("Engine 2 price action: {0}" -f [string]$line)
    }
    if ($priceActionExitCode -ne 0 -or !(Test-Path -LiteralPath $priceActionOutput)) {
        throw 'Engine 2 native MT5 multi-timeframe trend analysis did not reach READY.'
    }
    $priceActionSummary = Get-Content -LiteralPath $priceActionOutput -Raw | ConvertFrom-Json
    Add-Report ("PASS — Engine 2 price-action direction={0}; structure score={1}; alignment={2}; eligible frames={3}." -f $priceActionSummary.direction,$priceActionSummary.summary.structure_score,$priceActionSummary.summary.timeframe_alignment,($priceActionSummary.summary.eligible_timeframes -join ','))
    Add-Report 'PASS — Candle formations and price structure were computed from completed native OHLC only; no chart image was used.'
    Add-Report 'PASS — Native MT5 data path validated with InpEnableImageCapture=false; no screenshot is needed.'
    Add-Report 'Safety — Read-only Observer only; automated trading permission disabled; no execution EA, order API or MIR1 command.'
    Add-Report ("UTC finish: {0}" -f [DateTime]::UtcNow.ToString('o'))
    Get-Content -LiteralPath $report
}

catch {
    Add-Report ("FAIL — {0}" -f $_.Exception.Message)
    Add-Report ("UTC finish: {0}" -f [DateTime]::UtcNow.ToString('o'))
    Get-Content -LiteralPath $report
    throw
}
finally {
    if ($terminalProcess -and !$terminalProcess.HasExited) {
        Stop-Process -Id $terminalProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($loginConfig -and (Test-Path -LiteralPath $loginConfig)) {
        Remove-Item -LiteralPath $loginConfig -Force -ErrorAction SilentlyContinue
    }
    $accountPassword = $null
    $credentialRaw = $null
}
