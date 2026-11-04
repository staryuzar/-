#requires -Version 5.1
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root=Join-Path $env:RUNNER_TEMP 'mirsad-mt5-execution-check'
$installDir=Join-Path $root 'terminal'
$evidence=Join-Path $root 'evidence'
New-Item -ItemType Directory -Path $installDir,$evidence -Force | Out-Null
$report=Join-Path $evidence 'mirsad-execution-report.txt'
$installer=Join-Path $root 'mt5setup.exe'
$loginConfig=$null
$terminalProcess=$null
$accountPassword=$null
$credentialRaw=[string]$env:MT5_CREDENTIALS
function Add-Report([string]$Line){$Line|Add-Content -LiteralPath $report -Encoding utf8}
function Find-CommonFolder {
 $paths=@(
  (Join-Path $installDir 'Common\Files\MirsadBTC'),
  (Join-Path $installDir 'Terminal\Common\Files\MirsadBTC'),
  (Join-Path $env:APPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC'),
  (Join-Path $env:LOCALAPPDATA 'MetaQuotes\Terminal\Common\Files\MirsadBTC')
 )
 foreach($p in $paths){if(Test-Path -LiteralPath (Join-Path $p 'status.json')){return $p}}
 $roots=@((Join-Path $env:APPDATA 'MetaQuotes\Terminal'),(Join-Path $installDir 'Common'))|Where-Object{Test-Path -LiteralPath $_}
 foreach($r in $roots){
  $f=Get-ChildItem -LiteralPath $r -Filter status.json -File -Recurse -ErrorAction SilentlyContinue|Where-Object{$_.Directory.Name -eq 'MirsadBTC'}|Select-Object -First 1
  if($f){return $f.Directory.FullName}
 }
 return $null
}
try{
 'Mirsad BTC — MT5 execution bridge validation'|Set-Content -LiteralPath $report -Encoding utf8
 Add-Report ("UTC start: {0}" -f [DateTime]::UtcNow.ToString('o'))
 Add-Report 'Compile Mirsad EA, launch MT5 on the configured broker server and verify live EA telemetry.'
 Add-Report 'No MIR1 trade command is created by this workflow.'
 if([string]::IsNullOrWhiteSpace($credentialRaw)){throw "Repository Actions secret 'mt5' is unavailable."}
 $login='';$accountPassword='';$server='mt5.demo.trade-hw.online';$obj=$null
 if($credentialRaw.TrimStart().StartsWith('{')){
  try{$obj=ConvertFrom-Json -InputObject $credentialRaw -ErrorAction Stop}catch{throw 'MT5 secret JSON is invalid.'}
 }
 if($null -ne $obj){
  $login=[string]$obj.login;if([string]::IsNullOrWhiteSpace($login)){$login=[string]$obj.account}
  $accountPassword=[string]$obj.password
  if(-not [string]::IsNullOrWhiteSpace([string]$obj.server)){$server=[string]$obj.server}
 }else{
  $lines=@($credentialRaw -split "\r?\n"|ForEach-Object{$_.Trim()}|Where-Object{$_ -ne ''})
  $fields=@{}
  foreach($line in $lines){if($line -match '(?i)^(login|account|password|server)\s*[:=]\s*(.*)$'){$fields[$matches[1].ToLowerInvariant()]=$matches[2]}}
  if($fields.ContainsKey('login') -or $fields.ContainsKey('account') -or $fields.ContainsKey('password')){
   $login=[string]$fields['login'];if([string]::IsNullOrWhiteSpace($login)){$login=[string]$fields['account']}
   $accountPassword=[string]$fields['password'];if(-not [string]::IsNullOrWhiteSpace([string]$fields['server'])){$server=[string]$fields['server']}
  }elseif($lines.Count -ge 2){
   $login=[string]$lines[0];$accountPassword=[string]$lines[1];if($lines.Count -ge 3){$server=[string]$lines[2]}
  }else{throw 'MT5 secret format is not recognized.'}
 }
 if($login -notmatch '^\d{4,20}$' -or [string]::IsNullOrWhiteSpace($accountPassword)){throw 'MT5 credentials are incomplete.'}
 if([string]::IsNullOrWhiteSpace($server)){throw 'MT5 server is missing from the configured connection.'}
 Write-Output "::add-mask::$login"
 Write-Output "::add-mask::$accountPassword"
 Write-Output "::add-mask::$server"
 Add-Report 'Configured MT5 server accepted; credentials are masked and not included in evidence.'

 $download='https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe'
 Invoke-WebRequest -Uri $download -OutFile $installer -TimeoutSec 240
 if(!(Test-Path $installer) -or (Get-Item $installer).Length -lt 100000){throw 'Official MT5 installer download failed.'}
 $installArg='/path:"'+$installDir+'"'
 $install=Start-Process -FilePath $installer -ArgumentList @('/auto',$installArg) -PassThru -Wait
 Add-Report ("MT5 installer exit code: {0}" -f $install.ExitCode)
 $terminal=Get-ChildItem -LiteralPath $installDir -Filter terminal64.exe -File -Recurse -ErrorAction SilentlyContinue|Select-Object -First 1
 if(!$terminal){$terminal=Get-ChildItem -LiteralPath $installDir -Filter terminal.exe -File -Recurse -ErrorAction SilentlyContinue|Select-Object -First 1}
 $editor=Get-ChildItem -LiteralPath $installDir -Filter metaeditor64.exe -File -Recurse -ErrorAction SilentlyContinue|Select-Object -First 1
 if(!$terminal -or !$editor){throw 'MetaTrader terminal or MetaEditor was not found.'}
 Add-Report ("MetaTrader version: {0}" -f $terminal.VersionInfo.ProductVersion)

 $source=Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\mt5\Mirsad_BTC_ExecutionBridge.mq5'
 if(!(Test-Path $source)){throw 'Mirsad execution EA source file is missing.'}
 $sourceText=Get-Content -LiteralPath $source -Raw
 if($sourceText -notmatch '(?im)^[ \t]*input[ \t]+bool[ \t]+InpAllowExecution[ \t]*=[ \t]*true[ \t]*;'){
  throw 'Execution validation failed: EA must explicitly default InpAllowExecution=true.'
 }
 Add-Report 'PASS — Execution EA source defaults InpAllowExecution=true.'
 $experts=Join-Path $installDir 'MQL5\Experts'
 New-Item -ItemType Directory -Path $experts -Force|Out-Null
 $eaSource=Join-Path $experts 'Mirsad_BTC_ExecutionBridge.mq5'
 $eaBinary=Join-Path $experts 'Mirsad_BTC_ExecutionBridge.ex5'
 $compileLog=Join-Path $experts 'Mirsad_BTC_ExecutionBridge.log'
 Copy-Item -LiteralPath $source -Destination $eaSource -Force
 $compiler=Start-Process -FilePath $editor.FullName -ArgumentList ('/compile:"'+$eaSource+'" /log') -WorkingDirectory $installDir -PassThru
 if(!$compiler.WaitForExit(90000)){Stop-Process -Id $compiler.Id -Force -ErrorAction SilentlyContinue;throw 'MetaEditor compile timeout.'}
 Start-Sleep -Seconds 2
 if(!(Test-Path $compileLog) -or !(Test-Path $eaBinary)){throw 'MetaEditor did not create compile log and EX5.'}
 $compileText=Get-Content -LiteralPath $compileLog -Raw
 $compileText|Set-Content -LiteralPath (Join-Path $evidence 'Mirsad_BTC_ExecutionBridge_compile.log') -Encoding utf8
 if($compileText -notmatch '(?i)0 errors' -or $compileText -match '(?i)[1-9][0-9]* errors'){throw 'MetaEditor did not report zero errors.'}
 if($compileText -notmatch '(?i)0 warnings' -or $compileText -match '(?i)[1-9][0-9]* warnings'){throw 'MetaEditor did not report zero compile warnings.'}
 Copy-Item -LiteralPath $eaBinary -Destination (Join-Path $evidence 'Mirsad_BTC_ExecutionBridge.ex5') -Force
 Add-Report 'PASS — MetaEditor compiled Mirsad_BTC_ExecutionBridge.ex5 with zero errors and zero warnings.'

 $loginConfig=Join-Path $root 'mt5-demo.ini'
 $ini=@"
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
AllowLiveTrading=1
AllowDllImport=0

[Charts]
ProfileLast=Default
MaxBars=50000

[StartUp]
Expert=Mirsad_BTC_ExecutionBridge
Symbol=BTC
Period=M1
"@
 [IO.File]::WriteAllText($loginConfig,$ini,[Text.UTF8Encoding]::new($false))
 $accountPassword=$null;$credentialRaw=$null;$obj=$null
 $terminalProcess=Start-Process -FilePath $terminal.FullName -ArgumentList @('/portable',"/config:$loginConfig","/login:$login") -WorkingDirectory $installDir -PassThru
 Add-Report 'MT5 started with Mirsad EA on BTC,M1; terminal-wide automated trading is enabled (AllowLiveTrading=1). This job validates the EA transport without injecting a trade command.'
 $loginStarted=Get-Date;$authorized=$false;$heartbeat=$false;$quoteFresh=$false;$folder=$null;$telemetry=$null
 $deadline=(Get-Date).AddSeconds(150)
 while((Get-Date)-lt $deadline){
  $logDir=Join-Path $installDir 'Logs'
  if(Test-Path $logDir){
   $logs=Get-ChildItem -LiteralPath $logDir -Filter '*.log' -File -ErrorAction SilentlyContinue|Sort-Object LastWriteTime -Descending|Select-Object -First 12
   foreach($log in $logs){
    if($log.LastWriteTime -lt $loginStarted.AddSeconds(-3)){continue}
    $txt='';try{$txt=Get-Content -LiteralPath $log.FullName -Raw}catch{continue}
    foreach($line in ($txt -split "\r?\n")){
     if($line -match [regex]::Escape($server) -and
        $line -match '(?i)(authorized on|successfully authorized|authorization successful|login successful)' -and
        $line -notmatch '(?i)(failed|invalid|not authorized|authorization error)'){$authorized=$true}
    }
   }
  }
  $folder=Find-CommonFolder
  if($folder){
   try{
    $telemetry=Get-Content -LiteralPath (Join-Path $folder 'status.json') -Raw|ConvertFrom-Json -ErrorAction Stop
    $heartbeat=($telemetry.schema -eq 'MIR1' -and [bool]$telemetry.terminal_connected -and
      [bool]$telemetry.execution_enabled -and
      [bool]$telemetry.execution_input_enabled -and
      [bool]$telemetry.trade_permissions_available -and
      [int64]$telemetry.heartbeat_at_ms -gt 0 -and $telemetry.symbol -eq 'BTC')
    $tickAgeValue=$telemetry.quote.tick_age_seconds
    $tickAge=[double]$tickAgeValue
    $quoteFresh=($null -ne $tickAgeValue -and [double]$telemetry.quote.ask -gt 0 -and
      $tickAge -ge 0 -and $tickAge -le 10)
   }catch{$heartbeat=$false;$quoteFresh=$false}
  }
  if($authorized -and $heartbeat -and $quoteFresh){break}
  if($terminalProcess.HasExited){Add-Report 'Terminal exited before both authorization and EA heartbeat.';break}
  Start-Sleep -Seconds 3
 }
 if(!$authorized){throw 'MT5 authorization on the configured broker server was not confirmed.'}
 Add-Report 'PASS — MT5 authorized on the configured broker server.'
 if(!$heartbeat){throw 'MT5 logged in but the Mirsad EA heartbeat did not report execution enabled.'}
 if(!$quoteFresh){throw 'MT5 broker quote did not become fresh within the 150-second observation window.'}
 Add-Report 'PASS — Mirsad EA heartbeat is live; the EA input and MT5 automated-trading permissions are enabled.'
 Add-Report ("Broker symbol: {0}; market mapping: {1}; account currency: {2}" -f $telemetry.symbol,$telemetry.market_symbol,$telemetry.account.currency)
 Add-Report ("Current Ask quote available: {0}" -f ([double]$telemetry.quote.ask -gt 0))
 Add-Report ("Broker tick age (seconds): {0}" -f $telemetry.quote.tick_age_seconds)
 if([double]$telemetry.quote.tick_age_seconds -gt 10 -or [double]$telemetry.quote.tick_age_seconds -lt 0){throw 'Broker quote tick is stale or has an invalid age.'}
 $commandFile=Join-Path $folder 'command.json'
 if(Test-Path $commandFile){throw 'Unexpected command.json found; no trade test will be attempted.'}
 Add-Report 'No trade command was injected by this transport-validation job; automated trading remains available to valid Engine 4 commands.'

 # The broker deal-history feed is read-only. An empty list is valid on a
 # fresh demo account; malformed identity, money fields or timestamps are not.
 $dealHistoryPath=Join-Path $folder 'deals.json'
 if(!(Test-Path $dealHistoryPath)){throw 'MIR1 broker deal-history file was not published.'}
 try{$dealHistory=Get-Content -LiteralPath $dealHistoryPath -Raw|ConvertFrom-Json -ErrorAction Stop}
 catch{throw 'MIR1 broker deal-history JSON could not be parsed.'}
 $dealRows=@($dealHistory.deals)
 if($dealHistory.schema -ne 'MIR1-DEALS-1' -or $dealHistory.status -ne 'READY' -or
    $dealHistory.time_basis -ne 'MT5_SERVER_TIME' -or
    [int64]$dealHistory.magic -ne [int64]$telemetry.magic_number -or
    $dealHistory.symbol -ne $telemetry.symbol -or
    [int64]$dealHistory.queried_at_utc_ms -le 0 -or
    [int64]$dealHistory.server_utc_offset_seconds_at_query -lt -86400 -or
    [int64]$dealHistory.server_utc_offset_seconds_at_query -gt 86400 -or
    [int64]$dealHistory.window_end_server_ms -lt [int64]$dealHistory.window_start_server_ms -or
    [int]$dealHistory.returned_count -ne $dealRows.Count -or
    [int]$dealHistory.history_matching_total -lt $dealRows.Count -or
    [bool]$dealHistory.truncated -ne ([int]$dealHistory.history_matching_total -gt $dealRows.Count)){
  throw 'MIR1 broker deal-history envelope failed schema, identity, time or count validation.'
 }
 foreach($deal in $dealRows){
  if([int64]$deal.deal_ticket -le 0 -or [int64]$deal.position_id -le 0 -or
     [int64]$deal.magic -ne [int64]$telemetry.magic_number -or
     $deal.symbol -ne $telemetry.symbol -or
     [int64]$deal.time_server_ms -lt [int64]$dealHistory.window_start_server_ms -or
     [int64]$deal.time_server_ms -gt [int64]$dealHistory.window_end_server_ms){
   throw 'MIR1 deal entry contains a foreign identity or out-of-window timestamp.'
  }
  $net=[double]$deal.profit+[double]$deal.commission+[double]$deal.swap+[double]$deal.fee
  if([math]::Abs($net-[double]$deal.net_cashflow) -gt 0.02){
   throw 'MIR1 deal entry net cashflow does not match profit plus charges.'
  }
 }
 Add-Report ("PASS — MIR1 deal history is valid; Mirsad-owned deals returned: {0}; truncated: {1}." -f @($dealHistory.deals).Count,[bool]$dealHistory.truncated)
 $safe=[ordered]@{
  schema=$telemetry.schema;terminal_connected=$telemetry.terminal_connected
  execution_enabled=$telemetry.execution_enabled
  execution_input_enabled=$telemetry.execution_input_enabled
  trade_permissions_available=$telemetry.trade_permissions_available
  heartbeat_at_ms=$telemetry.heartbeat_at_ms;symbol=$telemetry.symbol
  market_symbol=$telemetry.market_symbol;quote=$telemetry.quote
  symbol_spec=$telemetry.symbol_spec;positions_count=@($telemetry.positions).Count
  deal_history_status=$dealHistory.status;deal_history_count=@($dealHistory.deals).Count
  deal_history_truncated=[bool]$dealHistory.truncated
  account_currency=$telemetry.account.currency
 }
 $safe|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $evidence 'mirsad-live-telemetry.json') -Encoding utf8
 $first=[int64]$telemetry.heartbeat_at_ms
 Start-Sleep -Seconds 15
 $new=Get-Content -LiteralPath (Join-Path $folder 'status.json') -Raw|ConvertFrom-Json -ErrorAction Stop
 if([int64]$new.heartbeat_at_ms -le $first){throw 'EA heartbeat did not advance during observation.'}
 Add-Report 'PASS — EA heartbeat continued updating during the MT5 runtime observation.'
 Add-Report 'The Windows runner will close MT5 when this validation job finishes; local persistent installation is a separate deployment step.'
 Add-Report ("UTC finish: {0}" -f [DateTime]::UtcNow.ToString('o'))
 Get-Content -LiteralPath $report
}catch{
 Add-Report ("FAIL — {0}" -f $_.Exception.Message)
 Add-Report ("UTC finish: {0}" -f [DateTime]::UtcNow.ToString('o'))
 Get-Content -LiteralPath $report
 throw
}finally{
 if($terminalProcess -and !$terminalProcess.HasExited){Stop-Process -Id $terminalProcess.Id -Force -ErrorAction SilentlyContinue}
 if($loginConfig -and (Test-Path $loginConfig)){Remove-Item -LiteralPath $loginConfig -Force -ErrorAction SilentlyContinue}
 $accountPassword=$null;$credentialRaw=$null
}
