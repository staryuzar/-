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

$imageCaptureSetting = [string]$env:MIRSAD_MT5_IMAGE_CAPTURE
$imageCaptureEnabled = $true
if ($imageCaptureSetting -match '^(?i:false|0|no|off)
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
        $found = Get-ChildItem -LiteralPath $searchRoot -Filter 'capture_*.json' -File -Recurse -ErrorAction SilentlyContinue |
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
    Add-Report ("Chart image capture enabled: {0}" -f $imageCaptureEnabled)

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
    $marketSymbol = [string]$env:MIRSAD_MT5_MARKET_SYMBOL
    if ([string]::IsNullOrWhiteSpace($marketSymbol)) { $marketSymbol = 'BTCUSDT' }
    $marketSymbol = $marketSymbol.Trim()
    if ($marketSymbol.Length -gt 32) { throw 'Configured Mirsad market symbol is too long.' }
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
    $eaSourceText = $sourceText
    if (-not $imageCaptureEnabled) {
        $imageInputDeclaration = 'input bool InpEnableImageCapture = true;'
        if (-not $eaSourceText.Contains($imageInputDeclaration)) {
            throw 'Direct-only mode could not locate the Observer image-capture input.'
        }
        $eaSourceText = $eaSourceText.Replace(
            $imageInputDeclaration,
            'input bool InpEnableImageCapture = false;'
        )
        Add-Report 'PASS — Observer build configured with InpEnableImageCapture=false; no PNG capture will be requested.'
    }
    [IO.File]::WriteAllText($eaSource, $eaSourceText, [Text.UTF8Encoding]::new($false))

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
    if (-not $imageCaptureEnabled) {
        Add-Report 'Direct-only verification: waiting for market.json, candles.json and indicators.json; image files are not part of this test.'
        $observerDir = $null
        $lastObserverStatus = $null
        $authorizationConfirmed = $false
        $nextLogScan = [DateTime]::MinValue
        $loginStarted = Get-Date
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
                        [string]$candles.account.server -eq $feedServer -and
                        [string]$indicators.account.server -eq $feedServer
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
        if (-not $authorizationConfirmed) {
            throw 'Direct MT5 files appeared, but Headway demo account authorization was not confirmed in terminal logs.'
        }
        Add-Report 'PASS — MT5 demo account authorization confirmed.'
        foreach ($name in @('market','candles','indicators')) {
            $feedPath = switch ($name) {
                'market' { Join-Path (Split-Path -Parent $observerDir) 'market.json' }
                'candles' { Join-Path $observerDir 'candles.json' }
                'indicators' { Join-Path $observerDir 'indicators.json' }
            }
            Add-Report ("PASS — Image-free direct feed present: {0}; schema={1}; bytes={2}." -f [IO.Path]::GetFileName($feedPath),$directFeedData[$name].schema,(Get-Item -LiteralPath $feedPath).Length)
        }

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
        Add-Report ("Data-only details: quote ticks={0}; Last ticks={1}; volume updates={2}; depth={3}." -f $directSummary.market.quote_tick_count,$directSummary.market.last_price_tick_count,$directSummary.market.volume_update_count,$directSummary.market.depth_of_market_status)
        Add-Report 'PASS — Direct MT5 data path validated with InpEnableImageCapture=false. No screenshot was requested or required.'
        Add-Report 'Safety — Read-only Observer only; automated trading permission disabled; no execution EA, order API or MIR1 command.'
        Add-Report ("UTC finish: {0}" -f [DateTime]::UtcNow.ToString('o'))
        Get-Content -LiteralPath $report
        return
    }

    $observerDir = $null
    $manifestFile = $null
    $manifest = $null
    $authorizationConfirmed = $false
    $lastObserverStatus = $null
    $nextLogScan = [DateTime]::MinValue
    $loginStarted = Get-Date
    $deadline = (Get-Date).AddSeconds(180)

    while ((Get-Date) -lt $deadline) {
        $observerDir = Get-CommonObserverDirectory

        if ((Get-Date) -ge $nextLogScan) {
            $authorizationConfirmed = Test-HeadwayAuthorizationLog
            $nextLogScan = (Get-Date).AddSeconds(9)
        }
        $statusSnapshot = Get-ObserverStatusSnapshot
        if ($statusSnapshot) { $lastObserverStatus = $statusSnapshot }

        if ($observerDir) {
            $candidates = Get-ChildItem -LiteralPath $observerDir -Filter 'capture_*.json' -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTimeUtc -Descending
            foreach ($candidate in $candidates) {
                try {
                    $candidateManifest = Get-Content -LiteralPath $candidate.FullName -Raw | ConvertFrom-Json -ErrorAction Stop
                }
                catch {
                    continue
                }
                if ($candidateManifest.account -and [bool]$candidateManifest.account.terminal_connected) {
                    $manifestFile = $candidate
                    $manifest = $candidateManifest
                    break
                }
            }
        }

        if ($manifestFile) { break }
        if ($terminalProcess.HasExited) {
            Add-Report 'Terminal exited before MT5 Observer capture was published.'
            break
        }
        Start-Sleep -Seconds 3
    }

    if (!$manifestFile -or !$observerDir -or !$manifest) {
        Add-Report ("Headway authorization detected in terminal logs: {0}" -f $authorizationConfirmed)
        if ($lastObserverStatus) {
            Add-Report ("Last Observer state: {0}; symbol={1}; timeframe={2}; message={3}" -f $lastObserverStatus.state,$lastObserverStatus.symbol,$lastObserverStatus.timeframe,$lastObserverStatus.message)
        }
        else {
            Add-Report 'No observer_status.json was found; the EA may not have initialized or may not have written to the expected Common Files location.'
        }
        Add-ObserverDiagnostics
        if (-not $authorizationConfirmed) {
            throw 'MT5 Headway authorization was not confirmed and no Observer capture was published. Review sanitized terminal log diagnostics above.'
        }
        if (-not $lastObserverStatus) {
            throw 'Headway authorization was detected, but the Observer EA did not publish its startup status. Review sanitized MT5 log diagnostics above.'
        }
        throw ("Headway authorization was detected, but Observer did not publish a connected capture. Last state={0}. Review the status message and sanitized log diagnostics above." -f $lastObserverStatus.state)
    }
    if (!$manifest.account -or -not [bool]$manifest.account.terminal_connected) {
        throw 'MT5 terminal did not report a connected account.'
    }
    Add-Report ("PASS — MT5 reports a connected account. Server={0}; account type={1}." -f $manifest.account.server,$manifest.account.trade_mode_label)
    if ($manifest.schema -ne 'MIR-CHART-OBSERVATION-1') { throw 'Observer manifest schema is not MIR-CHART-OBSERVATION-1.' }
    if ([string]$manifest.chart.symbol -ne $observerSymbol -or [string]$manifest.chart.timeframe -ne $observerTimeframe) {
        throw ("Observer captured {0},{1}, expected {2},{3}." -f $manifest.chart.symbol,$manifest.chart.timeframe,$observerSymbol,$observerTimeframe)
    }
    if ([int]$manifest.bars_copied -ne @($manifest.bars).Count) {
        throw 'Observer OHLC bar count is inconsistent.'
    }
    if (@($manifest.bars).Count -gt 0) {
        if ([bool]$manifest.bars[-1].is_closed) { throw 'Newest MT5 bar must be marked as forming.' }
        if ($manifest.bars[0].time_server_ms -ge $manifest.bars[-1].time_server_ms) {
            throw 'Observer bars are not in oldest-to-newest order.'
        }
    }

    $imagePath = Join-Path (Join-Path $observerDir 'images') ([string]$manifest.image_file)
    if (!(Test-Path -LiteralPath $imagePath)) { throw 'Observer manifest exists but its PNG image is missing.' }
    $imageBytes = [IO.File]::ReadAllBytes($imagePath)
    if ($imageBytes.Length -ne [int64]$manifest.image_size_bytes) { throw 'Observer PNG size does not match its manifest.' }
    if ($imageBytes.Length -lt 8 -or $imageBytes[0] -ne 137 -or $imageBytes[1] -ne 80 -or
        $imageBytes[2] -ne 78 -or $imageBytes[3] -ne 71) {
        throw 'Observer image does not have a PNG signature.'
    }
    $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    if (($nowMs - [int64]$manifest.capture_at_utc_ms) -gt 180000) {
        throw 'Observer capture is stale.'
    }
    $skew = [int64]$manifest.capture_at_utc_ms - [int64]$manifest.rates_snapshot_at_utc_ms
    if ($skew -lt 0) { throw 'OHLC snapshot timestamp occurs after the screenshot request timestamp.' }

    # The chart image and raw OHLC manifest stay on the ephemeral runner only.
    # The repository is public, so artifacts contain a sanitized summary, never
    # the user's screenshot or full price history.
    $imageHash = (Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $safe = [ordered]@{
        schema = $manifest.schema
        capture_id = $manifest.capture_id
        capture_at_utc_ms = $manifest.capture_at_utc_ms
        rates_snapshot_at_utc_ms = $manifest.rates_snapshot_at_utc_ms
        capture_data_skew_ms = $skew
        server = $manifest.account.server
        account_type = $manifest.account.trade_mode_label
        terminal_connected = [bool]$manifest.account.terminal_connected
        symbol = $manifest.chart.symbol
        timeframe = $manifest.chart.timeframe
        image_width_px = $manifest.image_width_px
        image_height_px = $manifest.image_height_px
        image_size_bytes = $imageBytes.Length
        image_sha256 = $imageHash
        source_width_px = [int]$manifest.chart.source_width_px
        source_main_window_height_px = [int]$manifest.chart.source_main_window_height_px
        chart_window_handle_reported = [bool]([long]$manifest.chart.chart_window_handle -gt 0)
        chart_is_maximized = [bool]$manifest.chart.chart_is_maximized
        visible_bars = [int]$manifest.chart.visible_bars
        windows_total = [int]$manifest.chart.windows_total
        chart_autoscroll = [bool]$manifest.chart.chart_autoscroll
        source_dimensions_usable = [bool]$manifest.chart.source_dimensions_usable
        bars_copied = @($manifest.bars).Count
        rates_status = $manifest.rates_status
        rates_error_code = $manifest.rates_error_code
        newest_bar_is_forming = (@($manifest.bars).Count -gt 0 -and (-not [bool]$manifest.bars[-1].is_closed))
        broker_server_time_basis = $manifest.bars_time_basis
        read_only = $true
        trading_permission_enabled = $false
    }
    $safe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'observer-live-capture-summary.json') -Encoding utf8
 
    # Run Engine 2 on the just-captured MT5 image before cleaning the temporary terminal.
    # The chart image and raw OHLC remain on this runner; only a sanitized result is uploaded.
    # Report the real direct-feed files before image analysis. This distinguishes
    # a missing publication from invalid/stale data without exposing raw prices.
    $candleFeedPath = Join-Path $observerDir 'candles.json'
    $indicatorFeedPath = Join-Path $observerDir 'indicators.json'
    $marketFeedPath = Join-Path (Split-Path -Parent $observerDir) 'market.json'
    foreach ($feedPath in @($marketFeedPath,$candleFeedPath,$indicatorFeedPath)) {
        if (!(Test-Path -LiteralPath $feedPath)) {
            Add-Report ("Direct MT5 feed file missing: {0}" -f [IO.Path]::GetFileName($feedPath))
            continue
        }
        try {
            $feed = Get-Content -LiteralPath $feedPath -Raw | ConvertFrom-Json -ErrorAction Stop
            $schema = [string]$feed.schema
            $connected = [bool]$feed.terminal_connected
            $accountServerPresent = -not [string]::IsNullOrWhiteSpace([string]$feed.account.server)
            $frameCount = 0
            if ($feed.timeframes) { $frameCount = @($feed.timeframes.PSObject.Properties).Count }
            Add-Report ("Direct MT5 feed file: {0}; schema={1}; connected={2}; account_server_present={3}; timeframes={4}; bytes={5}." -f [IO.Path]::GetFileName($feedPath),$schema,$connected,$accountServerPresent,$frameCount,(Get-Item -LiteralPath $feedPath).Length)
        }
        catch {
            Add-Report ("Direct MT5 feed file invalid: {0}; reason={1}" -f [IO.Path]::GetFileName($feedPath),$_.Exception.Message)
        }
    }

    $analysisScript = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\analyze_mt5_observer_capture.py'
    $analysisOutput = Join-Path $evidence 'observer-engine2-analysis.json'
    if (!(Test-Path -LiteralPath $analysisScript)) { throw 'Engine 2 Observer analysis script is missing.' }
    $analysisArgs = @($analysisScript, '--observer-root', $observerDir, '--market-symbol', $marketSymbol,
        '--expected-broker-symbol', $observerSymbol, '--output', $analysisOutput)
    $analysisLines = & python @analysisArgs 2>&1
    $analysisExitCode = $LASTEXITCODE
    foreach ($line in $analysisLines) { Add-Report ("Engine 2 smoke: {0}" -f [string]$line) }
    if ($analysisExitCode -ne 0) {
        Add-Report ("FAIL — MT5 Engine 1/2 validation script exited with code {0}." -f $analysisExitCode)
        throw 'The actual MT5 market/candle/chart validation script failed.'
    }
    if (!(Test-Path -LiteralPath $analysisOutput)) {
        throw 'MT5 Engine 1/2 validation did not create its sanitized summary.'
    }
    $engine2Summary = Get-Content -LiteralPath $analysisOutput -Raw | ConvertFrom-Json
    $engine1Status = [string]$engine2Summary.engine1_market.status
    $engine2CandleStatus = [string]$engine2Summary.engine2_candle_history.status
    Add-Report ("Engine 1 actual MT5 market result: status={0}; price={1}; tick status={2}; tick count={3}; economic calendar={4}; events={5}." -f $engine1Status,$engine2Summary.engine1_market.price,$engine2Summary.engine1_market.microstructure.status,$engine2Summary.engine1_market.microstructure.tick_count,$engine2Summary.engine1_market.economic_calendar.status,$engine2Summary.engine1_market.economic_calendar.event_count)
    Add-Report ("Engine 2 actual MT5 candle result: status={0}; timeframes={1}; closed 1m={2}; 5m={3}; 15m={4}." -f $engine2CandleStatus,($engine2Summary.engine2_candle_history.timeframes | ConvertTo-Json -Compress),$engine2Summary.engine2_candle_history.closed_candles.'1m',$engine2Summary.engine2_candle_history.closed_candles.'5m',$engine2Summary.engine2_candle_history.closed_candles.'15m')
    Add-Report ("Engine 2 native MT5 indicators: status={0}; ready timeframes={1}; missing required={2}." -f $engine2Summary.engine2_native_indicators.status,$engine2Summary.engine2_native_indicators.ready_timeframe_count,($engine2Summary.engine2_native_indicators.missing_required_timeframes -join ','))
    Add-Report ("Engine 2 MT5 image result: status={0}; visual eligible={1}; reference calibration={2}; detected bars={3}." -f $engine2Summary.engine2.status,$engine2Summary.engine2.visual_eligible,$engine2Summary.engine2.reference_calibration_status,$engine2Summary.engine2.detected_bars)

    $engine2VisualStatus = [string]$engine2Summary.engine2.status
    $engine2VisualEligible = [bool]$engine2Summary.engine2.visual_eligible
    if ($engine2CandleStatus -ne 'READY') {
        throw ("Engine 2 actual MT5 candle history is not READY: {0}. {1}" -f $engine2CandleStatus,$engine2Summary.engine2_candle_history.reason)
    }
    if ($engine2VisualStatus -ne 'READY' -or -not $engine2VisualEligible) {
        throw ("Engine 2 actual MT5 chart image is not visually eligible: {0}. {1}" -f $engine2VisualStatus,$engine2Summary.engine2.reason)
    }
    if ($engine1Status -eq 'LIVE') {
        Add-Report 'PASS — Engine 1 MT5 market feed is LIVE.'
    }
    else {
        Add-Report ("WARN — Engine 1 market feed is independently unavailable/stale: {0}. {1}" -f $engine1Status,$engine2Summary.engine1_market.reason)
        Add-Report 'This does not invalidate the Engine 2 image/candle result. Engine 4 must continue to block trading decisions until Engine 1 returns LIVE.'
    }
    Add-Report 'PASS — Engine 2 image and native candle history validated independently from the MT5 Observer capture.'
    Add-Report 'Safety — Observer and diagnostics only. Automated trading permission is disabled; no execution EA or MIR1 command is used.'

    Add-Report ("PASS — Observer capture received from MT5 account/server: {0} / {1} / {2}; account type={3}." -f $manifest.account.server,$manifest.chart.symbol, $manifest.chart.timeframe,$manifest.account.trade_mode_label)
    Add-Report ("PASS — PNG signature and byte size verified: {0} bytes." -f $imageBytes.Length)
    Add-Report ("PASS — MT5 OHLC response recorded: {0} bars; status={1}; error={2}." -f @($manifest.bars).Count,$manifest.rates_status,$manifest.rates_error_code)
    Add-Report ("PASS — Image/OHLC request skew: {0} ms." -f $skew)
    Add-Report 'Safety — Observer only; no execution EA attached; automated trading permission disabled; no MIR1 command created. The Observer source contains no trade API.'
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
) {
    $imageCaptureEnabled = $false
}

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
        $found = Get-ChildItem -LiteralPath $searchRoot -Filter 'capture_*.json' -File -Recurse -ErrorAction SilentlyContinue |
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
    Copy-Item -LiteralPath $source -Destination $eaSource -Force

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
    $manifestFile = $null
    $manifest = $null
    $authorizationConfirmed = $false
    $lastObserverStatus = $null
    $nextLogScan = [DateTime]::MinValue
    $loginStarted = Get-Date
    $deadline = (Get-Date).AddSeconds(180)

    while ((Get-Date) -lt $deadline) {
        $observerDir = Get-CommonObserverDirectory

        if ((Get-Date) -ge $nextLogScan) {
            $authorizationConfirmed = Test-HeadwayAuthorizationLog
            $nextLogScan = (Get-Date).AddSeconds(9)
        }
        $statusSnapshot = Get-ObserverStatusSnapshot
        if ($statusSnapshot) { $lastObserverStatus = $statusSnapshot }

        if ($observerDir) {
            $candidates = Get-ChildItem -LiteralPath $observerDir -Filter 'capture_*.json' -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTimeUtc -Descending
            foreach ($candidate in $candidates) {
                try {
                    $candidateManifest = Get-Content -LiteralPath $candidate.FullName -Raw | ConvertFrom-Json -ErrorAction Stop
                }
                catch {
                    continue
                }
                if ($candidateManifest.account -and [bool]$candidateManifest.account.terminal_connected) {
                    $manifestFile = $candidate
                    $manifest = $candidateManifest
                    break
                }
            }
        }

        if ($manifestFile) { break }
        if ($terminalProcess.HasExited) {
            Add-Report 'Terminal exited before MT5 Observer capture was published.'
            break
        }
        Start-Sleep -Seconds 3
    }

    if (!$manifestFile -or !$observerDir -or !$manifest) {
        Add-Report ("Headway authorization detected in terminal logs: {0}" -f $authorizationConfirmed)
        if ($lastObserverStatus) {
            Add-Report ("Last Observer state: {0}; symbol={1}; timeframe={2}; message={3}" -f $lastObserverStatus.state,$lastObserverStatus.symbol,$lastObserverStatus.timeframe,$lastObserverStatus.message)
        }
        else {
            Add-Report 'No observer_status.json was found; the EA may not have initialized or may not have written to the expected Common Files location.'
        }
        Add-ObserverDiagnostics
        if (-not $authorizationConfirmed) {
            throw 'MT5 Headway authorization was not confirmed and no Observer capture was published. Review sanitized terminal log diagnostics above.'
        }
        if (-not $lastObserverStatus) {
            throw 'Headway authorization was detected, but the Observer EA did not publish its startup status. Review sanitized MT5 log diagnostics above.'
        }
        throw ("Headway authorization was detected, but Observer did not publish a connected capture. Last state={0}. Review the status message and sanitized log diagnostics above." -f $lastObserverStatus.state)
    }
    if (!$manifest.account -or -not [bool]$manifest.account.terminal_connected) {
        throw 'MT5 terminal did not report a connected account.'
    }
    Add-Report ("PASS — MT5 reports a connected account. Server={0}; account type={1}." -f $manifest.account.server,$manifest.account.trade_mode_label)
    if ($manifest.schema -ne 'MIR-CHART-OBSERVATION-1') { throw 'Observer manifest schema is not MIR-CHART-OBSERVATION-1.' }
    if ([string]$manifest.chart.symbol -ne $observerSymbol -or [string]$manifest.chart.timeframe -ne $observerTimeframe) {
        throw ("Observer captured {0},{1}, expected {2},{3}." -f $manifest.chart.symbol,$manifest.chart.timeframe,$observerSymbol,$observerTimeframe)
    }
    if ([int]$manifest.bars_copied -ne @($manifest.bars).Count) {
        throw 'Observer OHLC bar count is inconsistent.'
    }
    if (@($manifest.bars).Count -gt 0) {
        if ([bool]$manifest.bars[-1].is_closed) { throw 'Newest MT5 bar must be marked as forming.' }
        if ($manifest.bars[0].time_server_ms -ge $manifest.bars[-1].time_server_ms) {
            throw 'Observer bars are not in oldest-to-newest order.'
        }
    }

    $imagePath = Join-Path (Join-Path $observerDir 'images') ([string]$manifest.image_file)
    if (!(Test-Path -LiteralPath $imagePath)) { throw 'Observer manifest exists but its PNG image is missing.' }
    $imageBytes = [IO.File]::ReadAllBytes($imagePath)
    if ($imageBytes.Length -ne [int64]$manifest.image_size_bytes) { throw 'Observer PNG size does not match its manifest.' }
    if ($imageBytes.Length -lt 8 -or $imageBytes[0] -ne 137 -or $imageBytes[1] -ne 80 -or
        $imageBytes[2] -ne 78 -or $imageBytes[3] -ne 71) {
        throw 'Observer image does not have a PNG signature.'
    }
    $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    if (($nowMs - [int64]$manifest.capture_at_utc_ms) -gt 180000) {
        throw 'Observer capture is stale.'
    }
    $skew = [int64]$manifest.capture_at_utc_ms - [int64]$manifest.rates_snapshot_at_utc_ms
    if ($skew -lt 0) { throw 'OHLC snapshot timestamp occurs after the screenshot request timestamp.' }

    # The chart image and raw OHLC manifest stay on the ephemeral runner only.
    # The repository is public, so artifacts contain a sanitized summary, never
    # the user's screenshot or full price history.
    $imageHash = (Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $safe = [ordered]@{
        schema = $manifest.schema
        capture_id = $manifest.capture_id
        capture_at_utc_ms = $manifest.capture_at_utc_ms
        rates_snapshot_at_utc_ms = $manifest.rates_snapshot_at_utc_ms
        capture_data_skew_ms = $skew
        server = $manifest.account.server
        account_type = $manifest.account.trade_mode_label
        terminal_connected = [bool]$manifest.account.terminal_connected
        symbol = $manifest.chart.symbol
        timeframe = $manifest.chart.timeframe
        image_width_px = $manifest.image_width_px
        image_height_px = $manifest.image_height_px
        image_size_bytes = $imageBytes.Length
        image_sha256 = $imageHash
        source_width_px = [int]$manifest.chart.source_width_px
        source_main_window_height_px = [int]$manifest.chart.source_main_window_height_px
        chart_window_handle_reported = [bool]([long]$manifest.chart.chart_window_handle -gt 0)
        chart_is_maximized = [bool]$manifest.chart.chart_is_maximized
        visible_bars = [int]$manifest.chart.visible_bars
        windows_total = [int]$manifest.chart.windows_total
        chart_autoscroll = [bool]$manifest.chart.chart_autoscroll
        source_dimensions_usable = [bool]$manifest.chart.source_dimensions_usable
        bars_copied = @($manifest.bars).Count
        rates_status = $manifest.rates_status
        rates_error_code = $manifest.rates_error_code
        newest_bar_is_forming = (@($manifest.bars).Count -gt 0 -and (-not [bool]$manifest.bars[-1].is_closed))
        broker_server_time_basis = $manifest.bars_time_basis
        read_only = $true
        trading_permission_enabled = $false
    }
    $safe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'observer-live-capture-summary.json') -Encoding utf8
 
    # Run Engine 2 on the just-captured MT5 image before cleaning the temporary terminal.
    # The chart image and raw OHLC remain on this runner; only a sanitized result is uploaded.
    # Report the real direct-feed files before image analysis. This distinguishes
    # a missing publication from invalid/stale data without exposing raw prices.
    $candleFeedPath = Join-Path $observerDir 'candles.json'
    $indicatorFeedPath = Join-Path $observerDir 'indicators.json'
    $marketFeedPath = Join-Path (Split-Path -Parent $observerDir) 'market.json'
    foreach ($feedPath in @($marketFeedPath,$candleFeedPath,$indicatorFeedPath)) {
        if (!(Test-Path -LiteralPath $feedPath)) {
            Add-Report ("Direct MT5 feed file missing: {0}" -f [IO.Path]::GetFileName($feedPath))
            continue
        }
        try {
            $feed = Get-Content -LiteralPath $feedPath -Raw | ConvertFrom-Json -ErrorAction Stop
            $schema = [string]$feed.schema
            $connected = [bool]$feed.terminal_connected
            $accountServerPresent = -not [string]::IsNullOrWhiteSpace([string]$feed.account.server)
            $frameCount = 0
            if ($feed.timeframes) { $frameCount = @($feed.timeframes.PSObject.Properties).Count }
            Add-Report ("Direct MT5 feed file: {0}; schema={1}; connected={2}; account_server_present={3}; timeframes={4}; bytes={5}." -f [IO.Path]::GetFileName($feedPath),$schema,$connected,$accountServerPresent,$frameCount,(Get-Item -LiteralPath $feedPath).Length)
        }
        catch {
            Add-Report ("Direct MT5 feed file invalid: {0}; reason={1}" -f [IO.Path]::GetFileName($feedPath),$_.Exception.Message)
        }
    }

    $marketSymbol = [string]$env:MIRSAD_MT5_MARKET_SYMBOL
    if ([string]::IsNullOrWhiteSpace($marketSymbol)) { $marketSymbol = 'BTCUSDT' }
    $marketSymbol = $marketSymbol.Trim()
    if ($marketSymbol.Length -gt 32) { throw 'Configured Mirsad market symbol is too long.' }
    $analysisScript = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\analyze_mt5_observer_capture.py'
    $analysisOutput = Join-Path $evidence 'observer-engine2-analysis.json'
    if (!(Test-Path -LiteralPath $analysisScript)) { throw 'Engine 2 Observer analysis script is missing.' }
    $analysisArgs = @($analysisScript, '--observer-root', $observerDir, '--market-symbol', $marketSymbol,
        '--expected-broker-symbol', $observerSymbol, '--output', $analysisOutput)
    $analysisLines = & python @analysisArgs 2>&1
    $analysisExitCode = $LASTEXITCODE
    foreach ($line in $analysisLines) { Add-Report ("Engine 2 smoke: {0}" -f [string]$line) }
    if ($analysisExitCode -ne 0) {
        Add-Report ("FAIL — MT5 Engine 1/2 validation script exited with code {0}." -f $analysisExitCode)
        throw 'The actual MT5 market/candle/chart validation script failed.'
    }
    if (!(Test-Path -LiteralPath $analysisOutput)) {
        throw 'MT5 Engine 1/2 validation did not create its sanitized summary.'
    }
    $engine2Summary = Get-Content -LiteralPath $analysisOutput -Raw | ConvertFrom-Json
    $engine1Status = [string]$engine2Summary.engine1_market.status
    $engine2CandleStatus = [string]$engine2Summary.engine2_candle_history.status
    Add-Report ("Engine 1 actual MT5 market result: status={0}; price={1}; tick status={2}; tick count={3}; economic calendar={4}; events={5}." -f $engine1Status,$engine2Summary.engine1_market.price,$engine2Summary.engine1_market.microstructure.status,$engine2Summary.engine1_market.microstructure.tick_count,$engine2Summary.engine1_market.economic_calendar.status,$engine2Summary.engine1_market.economic_calendar.event_count)
    Add-Report ("Engine 2 actual MT5 candle result: status={0}; timeframes={1}; closed 1m={2}; 5m={3}; 15m={4}." -f $engine2CandleStatus,($engine2Summary.engine2_candle_history.timeframes | ConvertTo-Json -Compress),$engine2Summary.engine2_candle_history.closed_candles.'1m',$engine2Summary.engine2_candle_history.closed_candles.'5m',$engine2Summary.engine2_candle_history.closed_candles.'15m')
    Add-Report ("Engine 2 native MT5 indicators: status={0}; ready timeframes={1}; missing required={2}." -f $engine2Summary.engine2_native_indicators.status,$engine2Summary.engine2_native_indicators.ready_timeframe_count,($engine2Summary.engine2_native_indicators.missing_required_timeframes -join ','))
    Add-Report ("Engine 2 MT5 image result: status={0}; visual eligible={1}; reference calibration={2}; detected bars={3}." -f $engine2Summary.engine2.status,$engine2Summary.engine2.visual_eligible,$engine2Summary.engine2.reference_calibration_status,$engine2Summary.engine2.detected_bars)

    $engine2VisualStatus = [string]$engine2Summary.engine2.status
    $engine2VisualEligible = [bool]$engine2Summary.engine2.visual_eligible
    if ($engine2CandleStatus -ne 'READY') {
        throw ("Engine 2 actual MT5 candle history is not READY: {0}. {1}" -f $engine2CandleStatus,$engine2Summary.engine2_candle_history.reason)
    }
    if ($engine2VisualStatus -ne 'READY' -or -not $engine2VisualEligible) {
        throw ("Engine 2 actual MT5 chart image is not visually eligible: {0}. {1}" -f $engine2VisualStatus,$engine2Summary.engine2.reason)
    }
    if ($engine1Status -eq 'LIVE') {
        Add-Report 'PASS — Engine 1 MT5 market feed is LIVE.'
    }
    else {
        Add-Report ("WARN — Engine 1 market feed is independently unavailable/stale: {0}. {1}" -f $engine1Status,$engine2Summary.engine1_market.reason)
        Add-Report 'This does not invalidate the Engine 2 image/candle result. Engine 4 must continue to block trading decisions until Engine 1 returns LIVE.'
    }
    Add-Report 'PASS — Engine 2 image and native candle history validated independently from the MT5 Observer capture.'
    Add-Report 'Safety — Observer and diagnostics only. Automated trading permission is disabled; no execution EA or MIR1 command is used.'

    Add-Report ("PASS — Observer capture received from MT5 account/server: {0} / {1} / {2}; account type={3}." -f $manifest.account.server,$manifest.chart.symbol, $manifest.chart.timeframe,$manifest.account.trade_mode_label)
    Add-Report ("PASS — PNG signature and byte size verified: {0} bytes." -f $imageBytes.Length)
    Add-Report ("PASS — MT5 OHLC response recorded: {0} bars; status={1}; error={2}." -f @($manifest.bars).Count,$manifest.rates_status,$manifest.rates_error_code)
    Add-Report ("PASS — Image/OHLC request skew: {0} ms." -f $skew)
    Add-Report 'Safety — Observer only; no execution EA attached; automated trading permission disabled; no MIR1 command created. The Observer source contains no trade API.'
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
) {
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
        $found = Get-ChildItem -LiteralPath $searchRoot -Filter 'capture_*.json' -File -Recurse -ErrorAction SilentlyContinue |
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
    Add-Report ("Chart image capture enabled: {0}" -f $imageCaptureEnabled)

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
    $marketSymbol = [string]$env:MIRSAD_MT5_MARKET_SYMBOL
    if ([string]::IsNullOrWhiteSpace($marketSymbol)) { $marketSymbol = 'BTCUSDT' }
    $marketSymbol = $marketSymbol.Trim()
    if ($marketSymbol.Length -gt 32) { throw 'Configured Mirsad market symbol is too long.' }
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
    $eaSourceText = $sourceText
    if (-not $imageCaptureEnabled) {
        $imageInputDeclaration = 'input bool InpEnableImageCapture = true;'
        if (-not $eaSourceText.Contains($imageInputDeclaration)) {
            throw 'Direct-only mode could not locate the Observer image-capture input.'
        }
        $eaSourceText = $eaSourceText.Replace(
            $imageInputDeclaration,
            'input bool InpEnableImageCapture = false;'
        )
        Add-Report 'PASS — Observer build configured with InpEnableImageCapture=false; no PNG capture will be requested.'
    }
    [IO.File]::WriteAllText($eaSource, $eaSourceText, [Text.UTF8Encoding]::new($false))

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
    if (-not $imageCaptureEnabled) {
        Add-Report 'Direct-only verification: waiting for market.json, candles.json and indicators.json; image files are not part of this test.'
        $observerDir = $null
        $lastObserverStatus = $null
        $authorizationConfirmed = $false
        $nextLogScan = [DateTime]::MinValue
        $loginStarted = Get-Date
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
                        [string]$candles.account.server -eq $feedServer -and
                        [string]$indicators.account.server -eq $feedServer
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
        if (-not $authorizationConfirmed) {
            throw 'Direct MT5 files appeared, but Headway demo account authorization was not confirmed in terminal logs.'
        }
        Add-Report 'PASS — MT5 demo account authorization confirmed.'
        foreach ($name in @('market','candles','indicators')) {
            $feedPath = switch ($name) {
                'market' { Join-Path (Split-Path -Parent $observerDir) 'market.json' }
                'candles' { Join-Path $observerDir 'candles.json' }
                'indicators' { Join-Path $observerDir 'indicators.json' }
            }
            Add-Report ("PASS — Image-free direct feed present: {0}; schema={1}; bytes={2}." -f [IO.Path]::GetFileName($feedPath),$directFeedData[$name].schema,(Get-Item -LiteralPath $feedPath).Length)
        }

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
        Add-Report ("Data-only details: quote ticks={0}; Last ticks={1}; volume updates={2}; depth={3}." -f $directSummary.market.quote_tick_count,$directSummary.market.last_price_tick_count,$directSummary.market.volume_update_count,$directSummary.market.depth_of_market_status)
        Add-Report 'PASS — Direct MT5 data path validated with InpEnableImageCapture=false. No screenshot was requested or required.'
        Add-Report 'Safety — Read-only Observer only; automated trading permission disabled; no execution EA, order API or MIR1 command.'
        Add-Report ("UTC finish: {0}" -f [DateTime]::UtcNow.ToString('o'))
        Get-Content -LiteralPath $report
        return
    }

    $observerDir = $null
    $manifestFile = $null
    $manifest = $null
    $authorizationConfirmed = $false
    $lastObserverStatus = $null
    $nextLogScan = [DateTime]::MinValue
    $loginStarted = Get-Date
    $deadline = (Get-Date).AddSeconds(180)

    while ((Get-Date) -lt $deadline) {
        $observerDir = Get-CommonObserverDirectory

        if ((Get-Date) -ge $nextLogScan) {
            $authorizationConfirmed = Test-HeadwayAuthorizationLog
            $nextLogScan = (Get-Date).AddSeconds(9)
        }
        $statusSnapshot = Get-ObserverStatusSnapshot
        if ($statusSnapshot) { $lastObserverStatus = $statusSnapshot }

        if ($observerDir) {
            $candidates = Get-ChildItem -LiteralPath $observerDir -Filter 'capture_*.json' -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTimeUtc -Descending
            foreach ($candidate in $candidates) {
                try {
                    $candidateManifest = Get-Content -LiteralPath $candidate.FullName -Raw | ConvertFrom-Json -ErrorAction Stop
                }
                catch {
                    continue
                }
                if ($candidateManifest.account -and [bool]$candidateManifest.account.terminal_connected) {
                    $manifestFile = $candidate
                    $manifest = $candidateManifest
                    break
                }
            }
        }

        if ($manifestFile) { break }
        if ($terminalProcess.HasExited) {
            Add-Report 'Terminal exited before MT5 Observer capture was published.'
            break
        }
        Start-Sleep -Seconds 3
    }

    if (!$manifestFile -or !$observerDir -or !$manifest) {
        Add-Report ("Headway authorization detected in terminal logs: {0}" -f $authorizationConfirmed)
        if ($lastObserverStatus) {
            Add-Report ("Last Observer state: {0}; symbol={1}; timeframe={2}; message={3}" -f $lastObserverStatus.state,$lastObserverStatus.symbol,$lastObserverStatus.timeframe,$lastObserverStatus.message)
        }
        else {
            Add-Report 'No observer_status.json was found; the EA may not have initialized or may not have written to the expected Common Files location.'
        }
        Add-ObserverDiagnostics
        if (-not $authorizationConfirmed) {
            throw 'MT5 Headway authorization was not confirmed and no Observer capture was published. Review sanitized terminal log diagnostics above.'
        }
        if (-not $lastObserverStatus) {
            throw 'Headway authorization was detected, but the Observer EA did not publish its startup status. Review sanitized MT5 log diagnostics above.'
        }
        throw ("Headway authorization was detected, but Observer did not publish a connected capture. Last state={0}. Review the status message and sanitized log diagnostics above." -f $lastObserverStatus.state)
    }
    if (!$manifest.account -or -not [bool]$manifest.account.terminal_connected) {
        throw 'MT5 terminal did not report a connected account.'
    }
    Add-Report ("PASS — MT5 reports a connected account. Server={0}; account type={1}." -f $manifest.account.server,$manifest.account.trade_mode_label)
    if ($manifest.schema -ne 'MIR-CHART-OBSERVATION-1') { throw 'Observer manifest schema is not MIR-CHART-OBSERVATION-1.' }
    if ([string]$manifest.chart.symbol -ne $observerSymbol -or [string]$manifest.chart.timeframe -ne $observerTimeframe) {
        throw ("Observer captured {0},{1}, expected {2},{3}." -f $manifest.chart.symbol,$manifest.chart.timeframe,$observerSymbol,$observerTimeframe)
    }
    if ([int]$manifest.bars_copied -ne @($manifest.bars).Count) {
        throw 'Observer OHLC bar count is inconsistent.'
    }
    if (@($manifest.bars).Count -gt 0) {
        if ([bool]$manifest.bars[-1].is_closed) { throw 'Newest MT5 bar must be marked as forming.' }
        if ($manifest.bars[0].time_server_ms -ge $manifest.bars[-1].time_server_ms) {
            throw 'Observer bars are not in oldest-to-newest order.'
        }
    }

    $imagePath = Join-Path (Join-Path $observerDir 'images') ([string]$manifest.image_file)
    if (!(Test-Path -LiteralPath $imagePath)) { throw 'Observer manifest exists but its PNG image is missing.' }
    $imageBytes = [IO.File]::ReadAllBytes($imagePath)
    if ($imageBytes.Length -ne [int64]$manifest.image_size_bytes) { throw 'Observer PNG size does not match its manifest.' }
    if ($imageBytes.Length -lt 8 -or $imageBytes[0] -ne 137 -or $imageBytes[1] -ne 80 -or
        $imageBytes[2] -ne 78 -or $imageBytes[3] -ne 71) {
        throw 'Observer image does not have a PNG signature.'
    }
    $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    if (($nowMs - [int64]$manifest.capture_at_utc_ms) -gt 180000) {
        throw 'Observer capture is stale.'
    }
    $skew = [int64]$manifest.capture_at_utc_ms - [int64]$manifest.rates_snapshot_at_utc_ms
    if ($skew -lt 0) { throw 'OHLC snapshot timestamp occurs after the screenshot request timestamp.' }

    # The chart image and raw OHLC manifest stay on the ephemeral runner only.
    # The repository is public, so artifacts contain a sanitized summary, never
    # the user's screenshot or full price history.
    $imageHash = (Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $safe = [ordered]@{
        schema = $manifest.schema
        capture_id = $manifest.capture_id
        capture_at_utc_ms = $manifest.capture_at_utc_ms
        rates_snapshot_at_utc_ms = $manifest.rates_snapshot_at_utc_ms
        capture_data_skew_ms = $skew
        server = $manifest.account.server
        account_type = $manifest.account.trade_mode_label
        terminal_connected = [bool]$manifest.account.terminal_connected
        symbol = $manifest.chart.symbol
        timeframe = $manifest.chart.timeframe
        image_width_px = $manifest.image_width_px
        image_height_px = $manifest.image_height_px
        image_size_bytes = $imageBytes.Length
        image_sha256 = $imageHash
        source_width_px = [int]$manifest.chart.source_width_px
        source_main_window_height_px = [int]$manifest.chart.source_main_window_height_px
        chart_window_handle_reported = [bool]([long]$manifest.chart.chart_window_handle -gt 0)
        chart_is_maximized = [bool]$manifest.chart.chart_is_maximized
        visible_bars = [int]$manifest.chart.visible_bars
        windows_total = [int]$manifest.chart.windows_total
        chart_autoscroll = [bool]$manifest.chart.chart_autoscroll
        source_dimensions_usable = [bool]$manifest.chart.source_dimensions_usable
        bars_copied = @($manifest.bars).Count
        rates_status = $manifest.rates_status
        rates_error_code = $manifest.rates_error_code
        newest_bar_is_forming = (@($manifest.bars).Count -gt 0 -and (-not [bool]$manifest.bars[-1].is_closed))
        broker_server_time_basis = $manifest.bars_time_basis
        read_only = $true
        trading_permission_enabled = $false
    }
    $safe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'observer-live-capture-summary.json') -Encoding utf8
 
    # Run Engine 2 on the just-captured MT5 image before cleaning the temporary terminal.
    # The chart image and raw OHLC remain on this runner; only a sanitized result is uploaded.
    # Report the real direct-feed files before image analysis. This distinguishes
    # a missing publication from invalid/stale data without exposing raw prices.
    $candleFeedPath = Join-Path $observerDir 'candles.json'
    $indicatorFeedPath = Join-Path $observerDir 'indicators.json'
    $marketFeedPath = Join-Path (Split-Path -Parent $observerDir) 'market.json'
    foreach ($feedPath in @($marketFeedPath,$candleFeedPath,$indicatorFeedPath)) {
        if (!(Test-Path -LiteralPath $feedPath)) {
            Add-Report ("Direct MT5 feed file missing: {0}" -f [IO.Path]::GetFileName($feedPath))
            continue
        }
        try {
            $feed = Get-Content -LiteralPath $feedPath -Raw | ConvertFrom-Json -ErrorAction Stop
            $schema = [string]$feed.schema
            $connected = [bool]$feed.terminal_connected
            $accountServerPresent = -not [string]::IsNullOrWhiteSpace([string]$feed.account.server)
            $frameCount = 0
            if ($feed.timeframes) { $frameCount = @($feed.timeframes.PSObject.Properties).Count }
            Add-Report ("Direct MT5 feed file: {0}; schema={1}; connected={2}; account_server_present={3}; timeframes={4}; bytes={5}." -f [IO.Path]::GetFileName($feedPath),$schema,$connected,$accountServerPresent,$frameCount,(Get-Item -LiteralPath $feedPath).Length)
        }
        catch {
            Add-Report ("Direct MT5 feed file invalid: {0}; reason={1}" -f [IO.Path]::GetFileName($feedPath),$_.Exception.Message)
        }
    }

    $analysisScript = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\analyze_mt5_observer_capture.py'
    $analysisOutput = Join-Path $evidence 'observer-engine2-analysis.json'
    if (!(Test-Path -LiteralPath $analysisScript)) { throw 'Engine 2 Observer analysis script is missing.' }
    $analysisArgs = @($analysisScript, '--observer-root', $observerDir, '--market-symbol', $marketSymbol,
        '--expected-broker-symbol', $observerSymbol, '--output', $analysisOutput)
    $analysisLines = & python @analysisArgs 2>&1
    $analysisExitCode = $LASTEXITCODE
    foreach ($line in $analysisLines) { Add-Report ("Engine 2 smoke: {0}" -f [string]$line) }
    if ($analysisExitCode -ne 0) {
        Add-Report ("FAIL — MT5 Engine 1/2 validation script exited with code {0}." -f $analysisExitCode)
        throw 'The actual MT5 market/candle/chart validation script failed.'
    }
    if (!(Test-Path -LiteralPath $analysisOutput)) {
        throw 'MT5 Engine 1/2 validation did not create its sanitized summary.'
    }
    $engine2Summary = Get-Content -LiteralPath $analysisOutput -Raw | ConvertFrom-Json
    $engine1Status = [string]$engine2Summary.engine1_market.status
    $engine2CandleStatus = [string]$engine2Summary.engine2_candle_history.status
    Add-Report ("Engine 1 actual MT5 market result: status={0}; price={1}; tick status={2}; tick count={3}; economic calendar={4}; events={5}." -f $engine1Status,$engine2Summary.engine1_market.price,$engine2Summary.engine1_market.microstructure.status,$engine2Summary.engine1_market.microstructure.tick_count,$engine2Summary.engine1_market.economic_calendar.status,$engine2Summary.engine1_market.economic_calendar.event_count)
    Add-Report ("Engine 2 actual MT5 candle result: status={0}; timeframes={1}; closed 1m={2}; 5m={3}; 15m={4}." -f $engine2CandleStatus,($engine2Summary.engine2_candle_history.timeframes | ConvertTo-Json -Compress),$engine2Summary.engine2_candle_history.closed_candles.'1m',$engine2Summary.engine2_candle_history.closed_candles.'5m',$engine2Summary.engine2_candle_history.closed_candles.'15m')
    Add-Report ("Engine 2 native MT5 indicators: status={0}; ready timeframes={1}; missing required={2}." -f $engine2Summary.engine2_native_indicators.status,$engine2Summary.engine2_native_indicators.ready_timeframe_count,($engine2Summary.engine2_native_indicators.missing_required_timeframes -join ','))
    Add-Report ("Engine 2 MT5 image result: status={0}; visual eligible={1}; reference calibration={2}; detected bars={3}." -f $engine2Summary.engine2.status,$engine2Summary.engine2.visual_eligible,$engine2Summary.engine2.reference_calibration_status,$engine2Summary.engine2.detected_bars)

    $engine2VisualStatus = [string]$engine2Summary.engine2.status
    $engine2VisualEligible = [bool]$engine2Summary.engine2.visual_eligible
    if ($engine2CandleStatus -ne 'READY') {
        throw ("Engine 2 actual MT5 candle history is not READY: {0}. {1}" -f $engine2CandleStatus,$engine2Summary.engine2_candle_history.reason)
    }
    if ($engine2VisualStatus -ne 'READY' -or -not $engine2VisualEligible) {
        throw ("Engine 2 actual MT5 chart image is not visually eligible: {0}. {1}" -f $engine2VisualStatus,$engine2Summary.engine2.reason)
    }
    if ($engine1Status -eq 'LIVE') {
        Add-Report 'PASS — Engine 1 MT5 market feed is LIVE.'
    }
    else {
        Add-Report ("WARN — Engine 1 market feed is independently unavailable/stale: {0}. {1}" -f $engine1Status,$engine2Summary.engine1_market.reason)
        Add-Report 'This does not invalidate the Engine 2 image/candle result. Engine 4 must continue to block trading decisions until Engine 1 returns LIVE.'
    }
    Add-Report 'PASS — Engine 2 image and native candle history validated independently from the MT5 Observer capture.'
    Add-Report 'Safety — Observer and diagnostics only. Automated trading permission is disabled; no execution EA or MIR1 command is used.'

    Add-Report ("PASS — Observer capture received from MT5 account/server: {0} / {1} / {2}; account type={3}." -f $manifest.account.server,$manifest.chart.symbol, $manifest.chart.timeframe,$manifest.account.trade_mode_label)
    Add-Report ("PASS — PNG signature and byte size verified: {0} bytes." -f $imageBytes.Length)
    Add-Report ("PASS — MT5 OHLC response recorded: {0} bars; status={1}; error={2}." -f @($manifest.bars).Count,$manifest.rates_status,$manifest.rates_error_code)
    Add-Report ("PASS — Image/OHLC request skew: {0} ms." -f $skew)
    Add-Report 'Safety — Observer only; no execution EA attached; automated trading permission disabled; no MIR1 command created. The Observer source contains no trade API.'
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
) {
    $imageCaptureEnabled = $false
}

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
        $found = Get-ChildItem -LiteralPath $searchRoot -Filter 'capture_*.json' -File -Recurse -ErrorAction SilentlyContinue |
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
    Copy-Item -LiteralPath $source -Destination $eaSource -Force

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
    $manifestFile = $null
    $manifest = $null
    $authorizationConfirmed = $false
    $lastObserverStatus = $null
    $nextLogScan = [DateTime]::MinValue
    $loginStarted = Get-Date
    $deadline = (Get-Date).AddSeconds(180)

    while ((Get-Date) -lt $deadline) {
        $observerDir = Get-CommonObserverDirectory

        if ((Get-Date) -ge $nextLogScan) {
            $authorizationConfirmed = Test-HeadwayAuthorizationLog
            $nextLogScan = (Get-Date).AddSeconds(9)
        }
        $statusSnapshot = Get-ObserverStatusSnapshot
        if ($statusSnapshot) { $lastObserverStatus = $statusSnapshot }

        if ($observerDir) {
            $candidates = Get-ChildItem -LiteralPath $observerDir -Filter 'capture_*.json' -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTimeUtc -Descending
            foreach ($candidate in $candidates) {
                try {
                    $candidateManifest = Get-Content -LiteralPath $candidate.FullName -Raw | ConvertFrom-Json -ErrorAction Stop
                }
                catch {
                    continue
                }
                if ($candidateManifest.account -and [bool]$candidateManifest.account.terminal_connected) {
                    $manifestFile = $candidate
                    $manifest = $candidateManifest
                    break
                }
            }
        }

        if ($manifestFile) { break }
        if ($terminalProcess.HasExited) {
            Add-Report 'Terminal exited before MT5 Observer capture was published.'
            break
        }
        Start-Sleep -Seconds 3
    }

    if (!$manifestFile -or !$observerDir -or !$manifest) {
        Add-Report ("Headway authorization detected in terminal logs: {0}" -f $authorizationConfirmed)
        if ($lastObserverStatus) {
            Add-Report ("Last Observer state: {0}; symbol={1}; timeframe={2}; message={3}" -f $lastObserverStatus.state,$lastObserverStatus.symbol,$lastObserverStatus.timeframe,$lastObserverStatus.message)
        }
        else {
            Add-Report 'No observer_status.json was found; the EA may not have initialized or may not have written to the expected Common Files location.'
        }
        Add-ObserverDiagnostics
        if (-not $authorizationConfirmed) {
            throw 'MT5 Headway authorization was not confirmed and no Observer capture was published. Review sanitized terminal log diagnostics above.'
        }
        if (-not $lastObserverStatus) {
            throw 'Headway authorization was detected, but the Observer EA did not publish its startup status. Review sanitized MT5 log diagnostics above.'
        }
        throw ("Headway authorization was detected, but Observer did not publish a connected capture. Last state={0}. Review the status message and sanitized log diagnostics above." -f $lastObserverStatus.state)
    }
    if (!$manifest.account -or -not [bool]$manifest.account.terminal_connected) {
        throw 'MT5 terminal did not report a connected account.'
    }
    Add-Report ("PASS — MT5 reports a connected account. Server={0}; account type={1}." -f $manifest.account.server,$manifest.account.trade_mode_label)
    if ($manifest.schema -ne 'MIR-CHART-OBSERVATION-1') { throw 'Observer manifest schema is not MIR-CHART-OBSERVATION-1.' }
    if ([string]$manifest.chart.symbol -ne $observerSymbol -or [string]$manifest.chart.timeframe -ne $observerTimeframe) {
        throw ("Observer captured {0},{1}, expected {2},{3}." -f $manifest.chart.symbol,$manifest.chart.timeframe,$observerSymbol,$observerTimeframe)
    }
    if ([int]$manifest.bars_copied -ne @($manifest.bars).Count) {
        throw 'Observer OHLC bar count is inconsistent.'
    }
    if (@($manifest.bars).Count -gt 0) {
        if ([bool]$manifest.bars[-1].is_closed) { throw 'Newest MT5 bar must be marked as forming.' }
        if ($manifest.bars[0].time_server_ms -ge $manifest.bars[-1].time_server_ms) {
            throw 'Observer bars are not in oldest-to-newest order.'
        }
    }

    $imagePath = Join-Path (Join-Path $observerDir 'images') ([string]$manifest.image_file)
    if (!(Test-Path -LiteralPath $imagePath)) { throw 'Observer manifest exists but its PNG image is missing.' }
    $imageBytes = [IO.File]::ReadAllBytes($imagePath)
    if ($imageBytes.Length -ne [int64]$manifest.image_size_bytes) { throw 'Observer PNG size does not match its manifest.' }
    if ($imageBytes.Length -lt 8 -or $imageBytes[0] -ne 137 -or $imageBytes[1] -ne 80 -or
        $imageBytes[2] -ne 78 -or $imageBytes[3] -ne 71) {
        throw 'Observer image does not have a PNG signature.'
    }
    $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    if (($nowMs - [int64]$manifest.capture_at_utc_ms) -gt 180000) {
        throw 'Observer capture is stale.'
    }
    $skew = [int64]$manifest.capture_at_utc_ms - [int64]$manifest.rates_snapshot_at_utc_ms
    if ($skew -lt 0) { throw 'OHLC snapshot timestamp occurs after the screenshot request timestamp.' }

    # The chart image and raw OHLC manifest stay on the ephemeral runner only.
    # The repository is public, so artifacts contain a sanitized summary, never
    # the user's screenshot or full price history.
    $imageHash = (Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $safe = [ordered]@{
        schema = $manifest.schema
        capture_id = $manifest.capture_id
        capture_at_utc_ms = $manifest.capture_at_utc_ms
        rates_snapshot_at_utc_ms = $manifest.rates_snapshot_at_utc_ms
        capture_data_skew_ms = $skew
        server = $manifest.account.server
        account_type = $manifest.account.trade_mode_label
        terminal_connected = [bool]$manifest.account.terminal_connected
        symbol = $manifest.chart.symbol
        timeframe = $manifest.chart.timeframe
        image_width_px = $manifest.image_width_px
        image_height_px = $manifest.image_height_px
        image_size_bytes = $imageBytes.Length
        image_sha256 = $imageHash
        source_width_px = [int]$manifest.chart.source_width_px
        source_main_window_height_px = [int]$manifest.chart.source_main_window_height_px
        chart_window_handle_reported = [bool]([long]$manifest.chart.chart_window_handle -gt 0)
        chart_is_maximized = [bool]$manifest.chart.chart_is_maximized
        visible_bars = [int]$manifest.chart.visible_bars
        windows_total = [int]$manifest.chart.windows_total
        chart_autoscroll = [bool]$manifest.chart.chart_autoscroll
        source_dimensions_usable = [bool]$manifest.chart.source_dimensions_usable
        bars_copied = @($manifest.bars).Count
        rates_status = $manifest.rates_status
        rates_error_code = $manifest.rates_error_code
        newest_bar_is_forming = (@($manifest.bars).Count -gt 0 -and (-not [bool]$manifest.bars[-1].is_closed))
        broker_server_time_basis = $manifest.bars_time_basis
        read_only = $true
        trading_permission_enabled = $false
    }
    $safe | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'observer-live-capture-summary.json') -Encoding utf8
 
    # Run Engine 2 on the just-captured MT5 image before cleaning the temporary terminal.
    # The chart image and raw OHLC remain on this runner; only a sanitized result is uploaded.
    # Report the real direct-feed files before image analysis. This distinguishes
    # a missing publication from invalid/stale data without exposing raw prices.
    $candleFeedPath = Join-Path $observerDir 'candles.json'
    $indicatorFeedPath = Join-Path $observerDir 'indicators.json'
    $marketFeedPath = Join-Path (Split-Path -Parent $observerDir) 'market.json'
    foreach ($feedPath in @($marketFeedPath,$candleFeedPath,$indicatorFeedPath)) {
        if (!(Test-Path -LiteralPath $feedPath)) {
            Add-Report ("Direct MT5 feed file missing: {0}" -f [IO.Path]::GetFileName($feedPath))
            continue
        }
        try {
            $feed = Get-Content -LiteralPath $feedPath -Raw | ConvertFrom-Json -ErrorAction Stop
            $schema = [string]$feed.schema
            $connected = [bool]$feed.terminal_connected
            $accountServerPresent = -not [string]::IsNullOrWhiteSpace([string]$feed.account.server)
            $frameCount = 0
            if ($feed.timeframes) { $frameCount = @($feed.timeframes.PSObject.Properties).Count }
            Add-Report ("Direct MT5 feed file: {0}; schema={1}; connected={2}; account_server_present={3}; timeframes={4}; bytes={5}." -f [IO.Path]::GetFileName($feedPath),$schema,$connected,$accountServerPresent,$frameCount,(Get-Item -LiteralPath $feedPath).Length)
        }
        catch {
            Add-Report ("Direct MT5 feed file invalid: {0}; reason={1}" -f [IO.Path]::GetFileName($feedPath),$_.Exception.Message)
        }
    }

    $marketSymbol = [string]$env:MIRSAD_MT5_MARKET_SYMBOL
    if ([string]::IsNullOrWhiteSpace($marketSymbol)) { $marketSymbol = 'BTCUSDT' }
    $marketSymbol = $marketSymbol.Trim()
    if ($marketSymbol.Length -gt 32) { throw 'Configured Mirsad market symbol is too long.' }
    $analysisScript = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\analyze_mt5_observer_capture.py'
    $analysisOutput = Join-Path $evidence 'observer-engine2-analysis.json'
    if (!(Test-Path -LiteralPath $analysisScript)) { throw 'Engine 2 Observer analysis script is missing.' }
    $analysisArgs = @($analysisScript, '--observer-root', $observerDir, '--market-symbol', $marketSymbol,
        '--expected-broker-symbol', $observerSymbol, '--output', $analysisOutput)
    $analysisLines = & python @analysisArgs 2>&1
    $analysisExitCode = $LASTEXITCODE
    foreach ($line in $analysisLines) { Add-Report ("Engine 2 smoke: {0}" -f [string]$line) }
    if ($analysisExitCode -ne 0) {
        Add-Report ("FAIL — MT5 Engine 1/2 validation script exited with code {0}." -f $analysisExitCode)
        throw 'The actual MT5 market/candle/chart validation script failed.'
    }
    if (!(Test-Path -LiteralPath $analysisOutput)) {
        throw 'MT5 Engine 1/2 validation did not create its sanitized summary.'
    }
    $engine2Summary = Get-Content -LiteralPath $analysisOutput -Raw | ConvertFrom-Json
    $engine1Status = [string]$engine2Summary.engine1_market.status
    $engine2CandleStatus = [string]$engine2Summary.engine2_candle_history.status
    Add-Report ("Engine 1 actual MT5 market result: status={0}; price={1}; tick status={2}; tick count={3}; economic calendar={4}; events={5}." -f $engine1Status,$engine2Summary.engine1_market.price,$engine2Summary.engine1_market.microstructure.status,$engine2Summary.engine1_market.microstructure.tick_count,$engine2Summary.engine1_market.economic_calendar.status,$engine2Summary.engine1_market.economic_calendar.event_count)
    Add-Report ("Engine 2 actual MT5 candle result: status={0}; timeframes={1}; closed 1m={2}; 5m={3}; 15m={4}." -f $engine2CandleStatus,($engine2Summary.engine2_candle_history.timeframes | ConvertTo-Json -Compress),$engine2Summary.engine2_candle_history.closed_candles.'1m',$engine2Summary.engine2_candle_history.closed_candles.'5m',$engine2Summary.engine2_candle_history.closed_candles.'15m')
    Add-Report ("Engine 2 native MT5 indicators: status={0}; ready timeframes={1}; missing required={2}." -f $engine2Summary.engine2_native_indicators.status,$engine2Summary.engine2_native_indicators.ready_timeframe_count,($engine2Summary.engine2_native_indicators.missing_required_timeframes -join ','))
    Add-Report ("Engine 2 MT5 image result: status={0}; visual eligible={1}; reference calibration={2}; detected bars={3}." -f $engine2Summary.engine2.status,$engine2Summary.engine2.visual_eligible,$engine2Summary.engine2.reference_calibration_status,$engine2Summary.engine2.detected_bars)

    $engine2VisualStatus = [string]$engine2Summary.engine2.status
    $engine2VisualEligible = [bool]$engine2Summary.engine2.visual_eligible
    if ($engine2CandleStatus -ne 'READY') {
        throw ("Engine 2 actual MT5 candle history is not READY: {0}. {1}" -f $engine2CandleStatus,$engine2Summary.engine2_candle_history.reason)
    }
    if ($engine2VisualStatus -ne 'READY' -or -not $engine2VisualEligible) {
        throw ("Engine 2 actual MT5 chart image is not visually eligible: {0}. {1}" -f $engine2VisualStatus,$engine2Summary.engine2.reason)
    }
    if ($engine1Status -eq 'LIVE') {
        Add-Report 'PASS — Engine 1 MT5 market feed is LIVE.'
    }
    else {
        Add-Report ("WARN — Engine 1 market feed is independently unavailable/stale: {0}. {1}" -f $engine1Status,$engine2Summary.engine1_market.reason)
        Add-Report 'This does not invalidate the Engine 2 image/candle result. Engine 4 must continue to block trading decisions until Engine 1 returns LIVE.'
    }
    Add-Report 'PASS — Engine 2 image and native candle history validated independently from the MT5 Observer capture.'
    Add-Report 'Safety — Observer and diagnostics only. Automated trading permission is disabled; no execution EA or MIR1 command is used.'

    Add-Report ("PASS — Observer capture received from MT5 account/server: {0} / {1} / {2}; account type={3}." -f $manifest.account.server,$manifest.chart.symbol, $manifest.chart.timeframe,$manifest.account.trade_mode_label)
    Add-Report ("PASS — PNG signature and byte size verified: {0} bytes." -f $imageBytes.Length)
    Add-Report ("PASS — MT5 OHLC response recorded: {0} bars; status={1}; error={2}." -f @($manifest.bars).Count,$manifest.rates_status,$manifest.rates_error_code)
    Add-Report ("PASS — Image/OHLC request skew: {0} ms." -f $skew)
    Add-Report 'Safety — Observer only; no execution EA attached; automated trading permission disabled; no MIR1 command created. The Observer source contains no trade API.'
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
