$ErrorActionPreference="Stop"
$ProgressPreference="SilentlyContinue"
$root=Join-Path $env:RUNNER_TEMP "goldlab-custom-tick-import"
$install=Join-Path $root "terminal"
$reports=Join-Path $PWD "goldlab-results"
New-Item -ItemType Directory -Path $root,$install,$reports -Force | Out-Null
$summary=Join-Path $reports "custom-tick-import-summary.txt"
$raw=[string]$env:MT5_CREDENTIALS
if (!$raw) { throw "Missing MT5 secret." }
$login=""; $password=""; $server="mt5.demo.trade-hw.online"; $o=$null
if ($raw.TrimStart().StartsWith("{")) { try{$o=ConvertFrom-Json $raw -ErrorAction Stop}catch{$o=$null} }
if ($null -ne $o) {
  $login=[string]$o.login; if(!$login){$login=[string]$o.account}; $password=[string]$o.password; if($o.server){$server=[string]$o.server}
} else {
  $lines=@($raw -split "\r?\n" | ForEach-Object{$_.Trim()} | Where-Object{$_})
  if($lines.Count -lt 2){throw "Unsupported MT5 secret format."}
  $login=$lines[0];$password=$lines[1];if($lines.Count -ge 3){$server=$lines[2]}
}
if($login -notmatch '^\d{4,20}$' -or !$password){throw "Invalid MT5 secret format."}
Write-Output "::add-mask::$login";Write-Output "::add-mask::$password";Write-Output "::add-mask::$server"
$passCfg=$password;$raw=$null;$o=$null;$lines=$null

function SaveLogs {
  if(!(Test-Path $install)){return}
  $all=@()
  foreach($d in @((Join-Path $install "Logs"),(Join-Path $install "MQL5\Logs"),(Join-Path $install "Tester\logs"),(Join-Path $install "MQL5\Scripts\GoldLab"),(Join-Path $install "MQL5\Experts\GoldLab"))){
    if(Test-Path $d){$all+=@(Get-ChildItem $d -File -Recurse -Filter "*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 8)}
  }
  $i=0
  foreach($l in @($all | Sort-Object LastWriteTime -Descending | Select-Object -Unique -First 16)){
    try{$txt=Get-Content $l.FullName -Raw;$txt=$txt -replace [regex]::Escape($login),'[ACCOUNT]' -replace [regex]::Escape($password),'[PASSWORD]' -replace [regex]::Escape($server),'[SERVER]';$i++;$txt|Set-Content (Join-Path $reports ("mt5-log-{0:D2}.txt" -f $i)) -Encoding utf8}catch{}
  }
}
"GoldLab external-tick custom-symbol import proof" | Set-Content $summary -Encoding utf8
try {
  $csv=Get-ChildItem (Join-Path $PWD "dukascopy-tick-probe") -Filter "xauusd-tick-2026-03-26-2026-03-27.csv" -File -Recurse | Select-Object -First 1
  if(!$csv -or $csv.Length -lt 1000000){throw "Dukascopy CSV missing/too small."}
  $setup=Join-Path $root "mt5setup.exe"
  Invoke-WebRequest "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" -OutFile $setup -TimeoutSec 180
  if(!(Test-Path $setup) -or (Get-Item $setup).Length -lt 100000){throw "MT5 installer missing."}
  Write-Host "Phase 1/4: launching official MT5 installer."
  $sp=Start-Process $setup -ArgumentList @("/auto","/path:$install") -PassThru
  if(!$sp.WaitForExit(300000)){
    try{& "$env:SystemRoot\System32\taskkill.exe" /PID $sp.Id /T /F 2>&1 | Add-Content $summary -Encoding utf8}catch{}
    throw "Official MT5 installer exceeded five-minute timeout; no tester result accepted."
  }
  Write-Host "MT5 installer exited: $($sp.ExitCode)"
  $terminal=Get-ChildItem $install -Filter "terminal64.exe" -File -Recurse | Select-Object -First 1
  $editor=Get-ChildItem $install -Filter "metaeditor64.exe" -File -Recurse | Select-Object -First 1
  if(!$terminal -or !$editor){throw "MT5 installation failed, exit=$($sp.ExitCode)."}
  "MT5 version: $((Get-Item $terminal.FullName).VersionInfo.ProductVersion)" | Add-Content $summary -Encoding utf8

  $expert=Join-Path $install "MQL5\Experts\GoldLab"
  $script=Join-Path $install "MQL5\Scripts\GoldLab"
  $files=Join-Path $install "MQL5\Files"
  $tester=Join-Path $install "MQL5\Profiles\Tester"
  New-Item -ItemType Directory -Path $expert,$script,$files,$tester -Force | Out-Null
  Copy-Item "trading-lab\gold-xauusd\GoldLabEA.mq5" (Join-Path $expert "GoldLabEA.mq5") -Force
  Copy-Item "trading-lab\gold-xauusd\GoldLabDukascopyImport.mq5" (Join-Path $script "GoldLabDukascopyImport.mq5") -Force
  Copy-Item $csv.FullName (Join-Path $files "Dukascopy_XAUUSD_2026-03-26.csv") -Force
  foreach($x in @(
    @{src=(Join-Path $expert "GoldLabEA.mq5");log=(Join-Path $expert "GoldLabEA.log");ex5=(Join-Path $expert "GoldLabEA.ex5");name="EA"},
    @{src=(Join-Path $script "GoldLabDukascopyImport.mq5");log=(Join-Path $script "GoldLabDukascopyImport.log");ex5=(Join-Path $script "GoldLabDukascopyImport.ex5");name="Importer"}
  )){
    $cp=Start-Process $editor.FullName -ArgumentList ('/compile:"'+$x.src+'" /log') -WorkingDirectory $install -PassThru
    if(!$cp.WaitForExit(90000)){Stop-Process $cp.Id -Force -ErrorAction SilentlyContinue;throw "$($x.name) compiler timed out."}
    Start-Sleep -Seconds 2
    if(!(Test-Path $x.log)){throw "$($x.name) compile log missing."}
    $cl=Get-Content $x.log -Raw;$m=[regex]::Match($cl,'(?im)^\s*Result:\s*(\d+)\s+errors,\s*(\d+)\s+warnings')
    if(!$m.Success -or [int]$m.Groups[1].Value -ne 0 -or [int]$m.Groups[2].Value -ne 0 -or !(Test-Path $x.ex5)){
      ($cl -replace [regex]::Escape($password),'[PASSWORD]') | Set-Content (Join-Path $reports ($x.name+"-compile-failure.txt")) -Encoding utf8
      throw "$($x.name) compile failed, expected zero errors and warnings."
    }
    ($cl -replace [regex]::Escape($password),'[PASSWORD]') | Set-Content (Join-Path $reports ($x.name+"-compile.log")) -Encoding utf8
    "$($x.name) compile: PASS 0 errors / 0 warnings" | Add-Content $summary -Encoding utf8
  }

  $importIni=Join-Path $root "import.ini"
  $ic=@("[Common]","Login=$login","Password=$passCfg","Server=$server","ProxyEnable=0","KeepPrivate=1","NewsEnable=0","CertInstall=0","","[Experts]","Enabled=1","AllowLiveTrading=0","AllowDllImport=0","","[StartUp]","Script=GoldLab\GoldLabDukascopyImport","Symbol=XAUUSD","Period=M1","ShutdownTerminal=1") -join [Environment]::NewLine
  [IO.File]::WriteAllText($importIni,$ic,[Text.Encoding]::ASCII)
  $env:MT5_CREDENTIALS=$null
  Write-Host "Phase 2/4: launching MQL5 custom-symbol tick importer."
  $ip=Start-Process $terminal.FullName -ArgumentList @("/portable",('/config:"'+$importIni+'"')) -WorkingDirectory $install -PassThru
  if(!$ip.WaitForExit(600000)){try{& "$env:SystemRoot\System32\taskkill.exe" /PID $ip.Id /T /F|Out-Null}catch{};throw "Importer did not exit within 10 minutes."}
  Start-Sleep -Seconds 2
  $importFile=Join-Path $files "GoldLabDukascopyImportResult.txt"
  if(!(Test-Path $importFile)){
    SaveLogs
    $nearby=@(Get-ChildItem $install -Filter "GoldLabDukascopyImportResult.txt" -File -Recurse -ErrorAction SilentlyContinue)
    ("Importer result missing; expected=$importFile; same-name copies elsewhere in portable install=$($nearby.Count)") | Add-Content $summary -Encoding utf8
    throw "Importer result file missing after startup; inspect captured terminal/script journals."
  }
  Copy-Item $importFile (Join-Path $reports "GoldLabDukascopyImportResult.txt") -Force
  $ir=Get-Content $importFile -Raw;$ir|Add-Content $summary -Encoding utf8
  if($ir -notmatch '(?m)^STATUS=PASS;' -or
     $ir -notmatch 'valid_ticks=480416' -or
     $ir -notmatch 'custom_ticks_replace=480416' -or
     $ir -notmatch 'copyticksrange_readback=480416' -or
     $ir -notmatch 'risk_probe_ok=(true|false)') {
    SaveLogs
    throw "Custom-symbol import/readback gate failed: expected exactly 480416 original, imported and read-back ticks plus an explicit risk-probe status."
  }

  $setName="GoldLab_Dukascopy_Import_Proof.set"
  $set=@(
    "InpMagic=2026102101||2026102101||1||2026102101||N","InpEntryTF=5||5||1||5||N","InpBiasTF=16385||16385||1||16385||N",
    "InpRiskPercent=0.5||0.5||0.1||0.5||N","InpFastEMA=20||20||1||20||N","InpSlowEMA=50||50||1||50||N","InpBiasFastEMA=50||50||1||50||N","InpBiasSlowEMA=200||200||1||200||N",
    "InpRSIPeriod=14||14||1||14||N","InpRSIMidline=50.0||50.0||1.0||50.0||N","InpADXPeriod=14||14||1||14||N","InpMinADX=23.0||23.0||1.0||23.0||N","InpMaxADX=25.0||25.0||1.0||25.0||N",
    "InpAllowLong=false||false||0||true||N","InpATRPeriod=14||14||1||14||N","InpStopATR=0.45||0.45||0.05||0.45||N","InpStopRetryBufferATR=0.50||0.50||0.05||0.50||N",
    "InpTargetATR=2.4||2.4||0.1||2.4||N","InpTrailATR=1.4||1.4||0.1||1.4||N","InpMaxSpreadPoints=1000.0||1000.0||100.0||1000.0||N",
    "InpCloseOnOpposite=true||false||0||true||N","InpWriteTradeCSV=true||false||0||true||N","InpRequireSignalCandleDirection=true||true||0||true||N","InpRequireFastEMARejection=true||true||0||true||N",
    "InpTestForceInvalidStopsOnce=false||false||0||true||N"
  ) -join [Environment]::NewLine
  [IO.File]::WriteAllText((Join-Path $tester $setName),$set,[Text.UTF8Encoding]::new($false))
  $base="goldlab-results\GoldLab_Dukascopy_CustomSymbol_M5_2026-03-26_to_2026-03-27"
  $testIni=Join-Path $root "tester.ini"
  $tc=@("[Common]","Login=$login","Password=$passCfg","Server=$server","ProxyEnable=0","KeepPrivate=1","NewsEnable=0","CertInstall=0","","[Experts]","Enabled=1","AllowLiveTrading=0","AllowDllImport=0","","[Tester]","Expert=GoldLab\GoldLabEA.ex5","ExpertParameters=$setName","Symbol=XAUUSD_DK0326","Period=M5","Model=4","ExecutionMode=-1","Optimization=0","FromDate=2026.03.26","ToDate=2026.03.27","ForwardMode=0","Deposit=500","Currency=USD","Leverage=1:1000","Report=$base","ReplaceReport=1","ShutdownTerminal=1","UseLocal=1","UseRemote=0","UseCloud=0","Visual=0") -join [Environment]::NewLine
  [IO.File]::WriteAllText($testIni,$tc,[Text.Encoding]::ASCII)
  $env:MT5_CREDENTIALS=$null
  Write-Host "Phase 3/4: launching MT5 Strategy Tester on the isolated custom symbol."
  $tp=Start-Process $terminal.FullName -ArgumentList @("/portable",('/config:"'+$testIni+'"')) -WorkingDirectory $install -PassThru
  if(!$tp.WaitForExit(900000)){try{& "$env:SystemRoot\System32\taskkill.exe" /PID $tp.Id /T /F|Out-Null}catch{};SaveLogs;throw "Custom-symbol tester timed out."}
  "Tester terminal exit code: $($tp.ExitCode)"|Add-Content $summary -Encoding utf8
  $report=$null
  foreach($p in @((Join-Path $install ($base+".htm")),(Join-Path $install ($base+".html")),(Join-Path $PWD ($base+".htm")),(Join-Path $PWD ($base+".html")))){if(Test-Path $p){$report=Get-Item $p;break}}
  if(!$report){$report=Get-ChildItem $install -Filter "GoldLab_Dukascopy_CustomSymbol_M5_2026-03-26_to_2026-03-27.htm" -File -Recurse -ErrorAction SilentlyContinue|Select-Object -First 1}
  if(!$report){SaveLogs;throw "MT5 did not produce the custom-symbol report."}
  $html=Get-Content $report.FullName -Raw
  $html=$html -replace [regex]::Escape($login),'[ACCOUNT]' -replace [regex]::Escape($password),'[PASSWORD]' -replace [regex]::Escape($server),'[SERVER]'
  [IO.File]::WriteAllText((Join-Path $reports "GoldLab_Dukascopy_CustomSymbol_M5_2026-03-26_to_2026-03-27.htm"),$html,[Text.UTF8Encoding]::new($false))
  $q=[regex]::Match($html,'(?is)History Quality:</td>\s*<td[^>]*><b>\s*([^<]+?)\s*</b>')
  $b=[regex]::Match($html,'(?is)Bars:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
  $t=[regex]::Match($html,'(?is)Ticks:</td>\s*<td[^>]*><b>\s*([\d,]+)\s*</b>')
  $dt=[regex]::Match($html,'(?is)Period:</td>\s*<td[^>]*><b>\s*M5\s*\((\d{4}\.\d{2}\.\d{2})\s*-\s*(\d{4}\.\d{2}\.\d{2})\)\s*</b>')
  $tr=[regex]::Match($html,'(?is)Total Trades:</td>\s*<td[^>]*><b>\s*(\d+)\s*</b>')
  $de=[regex]::Match($html,'(?is)Total Deals:</td>\s*<td[^>]*><b>\s*(\d+)\s*</b>')
  if(!$q.Success -or !$b.Success -or !$t.Success -or !$dt.Success){SaveLogs;throw "Could not parse report history/date fields."}
  $quality=$q.Groups[1].Value.Trim();$bars=[long]$b.Groups[1].Value.Replace(",","");$ticks=[long]$t.Groups[1].Value.Replace(",","")
  $trades=if($tr.Success){[int]$tr.Groups[1].Value}else{-1};$deals=if($de.Success){[int]$de.Groups[1].Value}else{-1}
  @("","## Custom-symbol tester gate","Source: Dukascopy, not Headway broker ticks","Symbol: XAUUSD_DK0326","Period: M5 ($($dt.Groups[1].Value) - $($dt.Groups[2].Value))","History quality: $quality","Bars: $bars","Ticks: $ticks","Trades/deals: $trades/$deals","One-day data-path smoke test only; H1 EMA200 lacks warm-up. Zero trades are acceptable; no strategy-profit inference.")|Add-Content $summary -Encoding utf8
  if($quality -ne "100% real ticks"){SaveLogs;throw "Tester history quality is '$quality', expected 100% real ticks."}
  if($bars -lt 200 -or $ticks -ne 480416){SaveLogs;throw "Tester feed gate failed (bars=$bars; ticks=$ticks; expected exactly 480416 ticks)."}
  # MT5 may render the date range through the first following M5 bar.
  # An exact 480416-tick count independently binds this report to the one-day import.
  if($dt.Groups[1].Value -ne "2026.03.26" -or $dt.Groups[2].Value -notin @("2026.03.27","2026.03.28")){SaveLogs;throw "Tester period mismatch: $($dt.Groups[1].Value) - $($dt.Groups[2].Value)."}
  if($html -notmatch '(?is)InpTestForceInvalidStopsOnce=false</b>' -or $html -notmatch '(?is)InpMaxSpreadPoints=1000(?:\.0+)?</b>'){SaveLogs;throw "Injection-off or spread-scaling input not confirmed in report."}
  "STATUS=PASS; custom-symbol tick import/readback and MT5 real-tick tester proof succeeded; not performance evidence."|Add-Content $summary -Encoding utf8
  Write-Host "Phase 4/4: PASS — MT5 confirmed imported real ticks; no strategy-profit conclusion is drawn."
  SaveLogs
  Get-Content $summary
}
catch{
  ("STATUS=FAIL_OR_INCOMPLETE; error="+$_.Exception.Message)|Add-Content $summary -Encoding utf8
  SaveLogs
  throw
}
finally{
  $env:MT5_CREDENTIALS=$null;$passCfg=$null
  foreach($p in @((Join-Path $root "import.ini"),(Join-Path $root "tester.ini"))){if(Test-Path $p){Remove-Item $p -Force -ErrorAction SilentlyContinue}}
}
