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
    # Never let a silent MetaTrader bootstrapper hold a hosted runner forever.
    # The installer is external software and must finish before terminal discovery.
    $install = Start-Process -FilePath $installer -ArgumentList @('/auto', $installArg) -PassThru
    if (!$install.WaitForExit(180000)) {
        Add-Report 'FAIL — Official MT5 installer exceeded the 180-second installation deadline.'
        Stop-Process -Id $install.Id -Force -ErrorAction SilentlyContinue
        throw 'Official MT5 installer timed out after 180 seconds; aborting cleanly instead of hanging the workflow.'
    }
    $installerExitCode = $install.ExitCode
    Add-Report ("MT5 installer process exit code: {0}" -f $installerExitCode)

    # MetaQuotes' official web bootstrapper can return exit code 1 even when
    # it has successfully installed MT5. A previously successful Mirsad run
    # recorded exit code 1 and then compiled/launched the installed terminal.
    # Therefore installation success is established by verified platform
    # binaries, not by the bootstrapper's process code alone.
    $terminal = $null
    $editor = $null
    $installDeadline = [DateTime]::UtcNow.AddSeconds(120)
    do {
        $terminal = Get-ChildItem -LiteralPath $installDir -Filter 'terminal64.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if (!$terminal) {
            $terminal = Get-ChildItem -LiteralPath $installDir -Filter 'terminal.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        $editor = Get-ChildItem -LiteralPath $installDir -Filter 'metaeditor64.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        $binariesReady = $terminal -and $editor -and $terminal.Length -gt 1000000 -and $editor.Length -gt 1000000
        if ($binariesReady) { break }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $installDeadline)

    if (!$binariesReady) {
        Add-Report ("FAIL — MT5 installation binaries were not verified. terminal_found={0}; editor_found={1}; installer_exit_code={2}" -f [bool]$terminal,[bool]$editor,$installerExitCode)
        throw 'Official MT5 bootstrapper finished but valid terminal64.exe and metaeditor64.exe binaries were not found within 120 seconds.'
    }
    if ($installerExitCode -ne 0) {
        Add-Report ("WARN — Bootstrapper returned exit code {0}, but valid terminal and MetaEditor binaries were found; continuing with binary verification." -f $installerExitCode)
    }
    else {
        Add-Report 'PASS — Official MT5 installer returned zero and terminal/MetaEditor binaries were verified.'
    }
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

    # Remove stale outputs and invoke MetaEditor with separately quoted arguments.
    Remove-Item -LiteralPath $compileLog,$eaBinary -Force -ErrorAction SilentlyContinue
    $compileArgument = '/compile:' + $eaSource
    Add-Report ("MetaEditor compile target: {0}" -f $eaSource)
    $compiler = Start-Process -FilePath $editor.FullName -ArgumentList @($compileArgument, '/log') -WorkingDirectory $installDir -PassThru
    $compilerExited = $compiler.WaitForExit(90000)
    if (!$compilerExited) {
        Stop-Process -Id $compiler.Id -Force -ErrorAction SilentlyContinue
        throw 'MetaEditor Observer compilation timed out after 90 seconds.'
    }
    $compiler.Refresh()
    Add-Report ("MetaEditor launcher exit code: {0}" -f $compiler.ExitCode)

    # MetaEditor may hand compilation to its already-running GUI process.
    # Poll for the real outputs rather than assuming launcher exit == compile completion.
    $compileDeadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
        if ((Test-Path -LiteralPath $compileLog) -and (Test-Path -LiteralPath $eaBinary)) {
            break
        }
        Start-Sleep -Milliseconds 1000
    } while ([DateTime]::UtcNow -lt $compileDeadline)

    if (!(Test-Path -LiteralPath $compileLog) -or !(Test-Path -LiteralPath $eaBinary)) {
        $diagnostic = Join-Path $evidence 'MetaEditor_diagnostics.txt'
        $lines = [System.Collections.Generic.List[string]]::new()
        $lines.Add("Editor=$($editor.FullName)")
        $lines.Add("Source=$eaSource")
        $lines.Add("ExpectedLog=$compileLog")
        $lines.Add("ExpectedBinary=$eaBinary")
        $lines.Add("LauncherExitCode=$($compiler.ExitCode)")
        $lines.Add("LogExists=$(Test-Path -LiteralPath $compileLog)")
        $lines.Add("BinaryExists=$(Test-Path -LiteralPath $eaBinary)")
        $lines.Add("--- matching logs in install directory ---")
        Get-ChildItem -LiteralPath $installDir -Filter '*ChartObserver*.log' -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 20 FullName,Length,LastWriteTime |
            ForEach-Object { $lines.Add(($_ | Format-List | Out-String).Trim()) }
        $lines.Add("--- MetaEditor processes ---")
        Get-CimInstance Win32_Process -Filter "Name='metaeditor64.exe' OR Name='metaeditor.exe'" -ErrorAction SilentlyContinue |
            ForEach-Object { $lines.Add("PID=$($_.ProcessId) Path=$($_.ExecutablePath) CommandLine=$($_.CommandLine)") }
        if (Test-Path -LiteralPath $compileLog) {
            Copy-Item -LiteralPath $compileLog -Destination (Join-Path $evidence 'Mirsad_ChartObserver_compile.log') -Force
            $compileLines = Get-Content -LiteralPath $compileLog -ErrorAction SilentlyContinue
            $lines.Add("--- MetaEditor compiler diagnostics (last 120 lines) ---")
            foreach ($compileLine in ($compileLines | Select-Object -Last 120)) {
                $lines.Add([string]$compileLine)
            }
        }
        $lines | Set-Content -LiteralPath $diagnostic -Encoding utf8
        Add-Report ("FAIL — MetaEditor outputs missing after 60s. ExitCode={0}; Log={1}; EX5={2}." -f $compiler.ExitCode,(Test-Path -LiteralPath $compileLog),(Test-Path -LiteralPath $eaBinary))
        Get-Content -LiteralPath $diagnostic | ForEach-Object { Write-Output $_ }
        throw 'MetaEditor did not create the Observer compile log and EX5 binary within 60 seconds.'
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
                $requiredIndicatorFrames = @('1m','5m','15m')
                $requiredIndicatorNames = @('ema20','ema50','rsi14','atr14')
                $indicatorBuffersReady = $true
                foreach ($timeframe in $requiredIndicatorFrames) {
                    $frame = $indicators.timeframes.$timeframe
                    if ($null -eq $frame) { $indicatorBuffersReady = $false; break }
                    foreach ($indicatorName in $requiredIndicatorNames) {
                        $item = $frame.values.$indicatorName
                        if ($null -eq $item -or [string]$item.status -ne 'READY' -or
                            $null -eq $item.closed -or $null -eq $item.current) {
                            $indicatorBuffersReady = $false
                            break
                        }
                    }
                    if (!$indicatorBuffersReady) { break }
                }
                if ($serverOk -and $identityOk -and $schemaOk -and $timeframesOk -and $fresh -and $indicatorBuffersReady) {
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
    # Quote age can cross the strict freshness boundary between two
    # two-second snapshots. Re-read the continuously published feed instead
    # of failing on a single transient stale quote.
    $directSummary = $null
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        $validatorLines = & python @validatorArgs 2>&1
        $validatorExitCode = $LASTEXITCODE
        foreach ($line in $validatorLines) {
            Add-Report ("Direct feed validator attempt {0}: {1}" -f $attempt,[string]$line)
        }
        if (Test-Path -LiteralPath $directOutput) {
            $directSummary = Get-Content -LiteralPath $directOutput -Raw | ConvertFrom-Json
            if ($validatorExitCode -eq 0 -and
                [string]$directSummary.engine2.status -eq 'READY' -and
                [string]$directSummary.engine3.status -eq 'READY') { break }
        }
        if ($attempt -lt 20) { Start-Sleep -Seconds 2 }
    }
    if ($null -eq $directSummary -or $validatorExitCode -ne 0) {
        throw 'Image-free direct MT5 feed reader validation remained blocked after 20 fresh-snapshot attempts.'
    }
    # Preserve the market snapshot, then pair candle and CopyBuffer snapshots.
    # The Observer publishes them sequentially. If an M1 bar closes between the
    # two writes, their timestamps can differ for one timer cycle; never compare
    # those different bars and never weaken numeric tolerances to hide the race.
    Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $observerDir) 'market.json') -Destination (Join-Path $evidence 'market-snapshot.json') -Force

    $parityValidator = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\\scripts\\validate_engine3_mt5_indicator_parity.py'
    $parityOutput = Join-Path $evidence 'engine3-indicator-parity.json'
    $candlesSnapshot = Join-Path $evidence 'candles-snapshot.json'
    $indicatorsSnapshot = Join-Path $evidence 'indicators-snapshot.json'
    if (!(Test-Path -LiteralPath $parityValidator)) {
        throw 'Engine 3 MT5 indicator parity validator is missing.'
    }
    $parityArgs = @(
        $parityValidator,
        '--candles', $candlesSnapshot,
        '--native-indicators', $indicatorsSnapshot,
        '--output', $parityOutput
    )
    $parityDeadline = [DateTime]::UtcNow.AddSeconds(30)
    $parityAttempt = 0
    $parityExitCode = 1
    $paritySummary = $null
    do {
        $parityAttempt++
        Copy-Item -LiteralPath (Join-Path $observerDir 'candles.json') -Destination $candlesSnapshot -Force
        Copy-Item -LiteralPath (Join-Path $observerDir 'indicators.json') -Destination $indicatorsSnapshot -Force
        $parityLines = & python @parityArgs 2>&1
        $parityExitCode = $LASTEXITCODE
        foreach ($line in $parityLines) {
            Add-Report ("Engine 3 MT5 parity attempt {0}: {1}" -f $parityAttempt,[string]$line)
        }
        if ($parityExitCode -eq 0 -and (Test-Path -LiteralPath $parityOutput)) {
            $paritySummary = Get-Content -LiteralPath $parityOutput -Raw | ConvertFrom-Json
            break
        }
        if (!(Test-Path -LiteralPath $parityOutput)) { break }
        $paritySummary = Get-Content -LiteralPath $parityOutput -Raw | ConvertFrom-Json

        # Retry only when every failed timeframe has a timestamp mismatch and
        # all remaining failures are numeric deltas caused by comparing those
        # mismatched bars. Schema, identity, missing-buffer and history errors
        # remain hard failures and are not retried away.
        $transientTimestampRace = @($paritySummary.failures).Count -gt 0
        foreach ($failure in @($paritySummary.failures)) {
            if ([string]$failure -notmatch '^[^:]+: ') {
                $transientTimestampRace = $false
                break
            }
        }
        foreach ($frameProperty in @($paritySummary.timeframes.PSObject.Properties)) {
            if ([string]$frameProperty.Value.status -eq 'FAIL') {
                $frameFailures = @($frameProperty.Value.failures)
                $hasTimestampMismatch = @($frameFailures | Where-Object { [string]$_ -match 'timestamp mismatch' }).Count -gt 0
                $hasHardFailure = @($frameFailures | Where-Object {
                    [string]$_ -notmatch 'timestamp mismatch' -and
                    [string]$_ -notmatch 'absolute error .* exceeds tolerance'
                }).Count -gt 0
                if (!$hasTimestampMismatch -or $hasHardFailure) {
                    $transientTimestampRace = $false
                    break
                }
            }
        }
        if (!$transientTimestampRace -or [DateTime]::UtcNow -ge $parityDeadline) { break }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $parityDeadline)

    if ($parityExitCode -ne 0 -or $null -eq $paritySummary) {
        throw 'Engine 3 indicator parity against native MT5 CopyBuffer did not pass on identical closed bars; see timestamp and metric diagnostics.'
    }
    Add-Report ("PASS — Engine 3 versus MT5 parity: {0}/{1} indicator checks passed across six timeframes." -f $paritySummary.passed_metrics,$paritySummary.total_metrics)
    if ([string]$directSummary.engine2.status -ne 'READY') {
        throw 'Engine 2 native MT5 market/OHLC feed is not READY.'
    }
    Add-Report ("PASS — Engine 2 feed: market={0}; native OHLC candles={1}." -f $directSummary.market.status,$directSummary.candles.status)
    Add-Report ("Engine 3 feed: overall={0}; native={1}; calculated={2}; signal={3}; quality={4}; coverage={5}%; ready timeframes={6}." -f $directSummary.engine3.status,$directSummary.engine3.native_status,$directSummary.engine3.calculated_status,$directSummary.engine3.signal_score,$directSummary.engine3.signal_quality,([double]$directSummary.engine3.signal_timeframe_weight_coverage*100),$directSummary.native_indicators.ready_timeframe_count)
    Add-Report ("Engine 3 volume basis: {0}" -f $directSummary.engine3.signal_volume_basis)
    if ([string]$directSummary.engine3.status -ne 'READY' -or
        [string]$directSummary.engine3.calculated_status -ne 'READY' -or
        $null -eq $directSummary.engine3.signal_score -or
        [double]$directSummary.engine3.signal_quality -lt 0.60) {
        throw 'Engine 3 calculated signal or native MT5 buffers are not READY with at least 60 percent evidence quality.'
    }
    Add-Report 'PASS — Engine 3 composite signal, quality gate, core MT5 buffers and all six native indicator frames are READY.'
    # Engine 1 independently samples only its public providers. Its
    # diagnostic does not consume the MT5 broker quote snapshot, and provider
    # outages remain warnings rather than weakening Engine 2 / Engine 3 gates.
    $engine1Validator = Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\validate_engine1_live_sources.py'
    $engine1Output = Join-Path $evidence 'engine1-live-source-report.json'
    if (Test-Path -LiteralPath $engine1Validator) {
        $engine1Args = @(
            $engine1Validator,
            '--output', $engine1Output
        )
        $engine1Lines = & python @engine1Args 2>&1
        $engine1ExitCode = $LASTEXITCODE
        foreach ($line in $engine1Lines) {
            Add-Report ("Engine 1 live intelligence: {0}" -f [string]$line)
        }
        if (Test-Path -LiteralPath $engine1Output) {
            $engine1Summary = Get-Content -LiteralPath $engine1Output -Raw | ConvertFrom-Json
            Add-Report ("Engine 1 standalone public-source report: status={0}; public providers={1}; usable directional components={2}; ShowMyTrades calendar={3}; TE calendar={4}." -f $engine1Summary.overall_status,$engine1Summary.provider_response_count,$engine1Summary.usable_directional_component_count,$engine1Summary.economic_calendar.source_statuses.showmytrades,$engine1Summary.economic_calendar.source_statuses.trading_economics)
        }
        if ($engine1ExitCode -ne 0) {
            Add-Report 'WARN — Engine 1 live public providers were incomplete in this session; diagnostic captured without weakening or blocking Engine 3 validation.'
        }
    } else {
        Add-Report 'WARN — Engine 1 live-source validator was not present in this checkout.'
    }
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
    $priceActionLines = & python @priceActionArgs 2>&1
    $priceActionExitCode = $LASTEXITCODE
    foreach ($line in $priceActionLines) {
        Add-Report ("Engine 2 price action: {0}" -f [string]$line)
    }
    if ($priceActionExitCode -ne 0 -or !(Test-Path -LiteralPath $priceActionOutput)) {
        throw 'Engine 2 native MT5 multi-timeframe price-action analysis did not reach READY.'
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
