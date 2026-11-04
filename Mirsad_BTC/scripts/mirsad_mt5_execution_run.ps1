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
$runBrokerAcceptance=($env:MIRSAD_RUN_BROKER_ACCEPTANCE -eq 'true' -or $env:MIRSAD_RUN_BROKER_ACCEPTANCE -eq '1')
$runLiveRuntimeCycle=($env:MIRSAD_RUN_LIVE_RUNTIME_CYCLE -eq 'true' -or $env:MIRSAD_RUN_LIVE_RUNTIME_CYCLE -eq '1')
$executionEnabled=($runBrokerAcceptance -or $runLiveRuntimeCycle)
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
 Add-Report 'This workflow runs one risk-sized MIR1 BUY/CLOSE acceptance trade through the Python bridge and validates its broker deal cycle.'
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
 if($runBrokerAcceptance){
  $requestedDemoHost=[string]$env:MIRSAD_MT5_SERVER
  $expectedDemoAccountServer=[string]$env:MIRSAD_MT5_EXPECTED_ACCOUNT_SERVER
  if($requestedDemoHost -ne 'mt5.demo.trade-hw.online'){
   throw 'Broker acceptance is blocked: the only permitted connection host is mt5.demo.trade-hw.online.'
  }
  if($expectedDemoAccountServer -ne 'Headway-Demo'){
   throw 'Broker acceptance is blocked: expected account server must be explicitly pinned to Headway-Demo.'
  }
  # Ignore a server override from the secret for the one-off acceptance run:
  # always connect through the explicitly pinned demo host.
  $server=$requestedDemoHost
  Add-Report 'PASS — Broker acceptance is pinned to the Headway demo host and expected Headway-Demo account identity.'
 }
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
 $eaSourceText=$sourceText
 if(-not $executionEnabled){
  $executionEnabledPattern='(?m)^([ \t]*input[ \t]+bool[ \t]+InpAllowExecution[ \t]*=[ \t]*)true([ \t]*;)'
  $executionDisabledPattern='(?m)^[ \t]*input[ \t]+bool[ \t]+InpAllowExecution[ \t]*=[ \t]*false[ \t]*;'
  $eaSourceText=[regex]::Replace($eaSourceText,$executionEnabledPattern,'${1}false${2}',1)
  if($eaSourceText -notmatch $executionDisabledPattern){throw 'Read-only validation build could not force InpAllowExecution=false.'}
 }
 [IO.File]::WriteAllText($eaSource,$eaSourceText,[Text.UTF8Encoding]::new($false))
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

 if($runLiveRuntimeCycle){
  $expectedCommonFiles=[string]$env:MIRSAD_EXPECTED_COMMON_FILES
  if([string]::IsNullOrWhiteSpace($expectedCommonFiles) -or !(Test-Path -LiteralPath $expectedCommonFiles)){throw 'Integrated runtime requires the Observer Common Files directory.'}
  $expectedCommonFiles=[IO.Path]::GetFullPath($expectedCommonFiles)
  foreach($relative in @('MirsadBTC\market.json','MirsadBTC\observer\candles.json','MirsadBTC\observer\indicators.json')){
   if(!(Test-Path -LiteralPath (Join-Path $expectedCommonFiles $relative))){throw ("The live Observer feed is missing from the shared directory: {0}" -f $relative)}
  }
  $commonFilesLink=Join-Path $installDir 'Common\Files'
  $commonParent=Split-Path -Parent $commonFilesLink
  New-Item -ItemType Directory -Path $commonParent -Force|Out-Null
  if(Test-Path -LiteralPath $commonFilesLink){
   $backup=Join-Path $commonParent 'Files.pre-integration'
   if(Test-Path -LiteralPath $backup){Remove-Item -LiteralPath $backup -Recurse -Force}
   Move-Item -LiteralPath $commonFilesLink -Destination $backup -Force
  }
  New-Item -ItemType Junction -Path $commonFilesLink -Target $expectedCommonFiles|Out-Null
  Add-Report ("PASS — Execution terminal Common Files linked to active Observer feed at {0}." -f $expectedCommonFiles)
 }
 $loginConfig=Join-Path $root 'mt5-demo.ini'
 $allowLiveTrading=if($executionEnabled){'1'}else{'0'}
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
AllowLiveTrading=$allowLiveTrading
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
 if($runBrokerAcceptance){
  Add-Report 'MT5 started with Mirsad EA on BTC,M1; AllowLiveTrading=1 is enabled for the explicitly requested BUY/CLOSE acceptance test.'
 }elseif($runLiveRuntimeCycle){
  Add-Report 'MT5 started with Mirsad EA on BTC,M1; execution permission is enabled for integrated runtime validation.'
 }else{
  Add-Report 'MT5 started with Mirsad EA on BTC,M1 in read-only validation mode; AllowLiveTrading=0.'
 }
 $heartbeat=$false;$quoteFresh=$false;$folder=$null;$telemetry=$null
 $deadline=(Get-Date).AddSeconds(150)
 while((Get-Date)-lt $deadline){
  $folder=Find-CommonFolder
  if($folder){
   try{
    $telemetry=Get-Content -LiteralPath (Join-Path $folder 'status.json') -Raw|ConvertFrom-Json -ErrorAction Stop
    $accountLogin=0
    try{$accountLogin=[int64]$telemetry.account.login}catch{$accountLogin=0}
    $accountServer=[string]$telemetry.account.server
    $accountIdentityValid=($accountLogin -gt 0 -and -not [string]::IsNullOrWhiteSpace($accountServer))
    $executionStateMatches=(
      ([bool]$telemetry.execution_enabled -eq $executionEnabled) -and
      ([bool]$telemetry.execution_input_enabled -eq $executionEnabled)
    )
    $permissionsMatch=((-not $executionEnabled) -or [bool]$telemetry.trade_permissions_available)
    $heartbeat=($telemetry.schema -eq 'MIR1' -and [bool]$telemetry.terminal_connected -and
      $executionStateMatches -and $permissionsMatch -and
      $accountIdentityValid -and
      [int64]$telemetry.heartbeat_at_ms -gt 0 -and $telemetry.symbol -eq 'BTC')
    $tickAgeValue=$telemetry.quote.tick_age_seconds
    $tickAge=[double]$tickAgeValue
    $quoteFresh=($null -ne $tickAgeValue -and [double]$telemetry.quote.ask -gt 0 -and
      $tickAge -ge 0 -and $tickAge -le 10)
   }catch{$heartbeat=$false;$quoteFresh=$false}
  }
  if($heartbeat -and $quoteFresh){break}
  if($terminalProcess.HasExited){Add-Report 'Terminal exited before a fresh connected MIR1 heartbeat, account identity and broker quote were observed.';break}
  Start-Sleep -Seconds 3
 }
 if(!$heartbeat){throw 'MT5 did not publish a fresh connected MIR1 heartbeat with account identity and all execution permissions enabled.'}
 if(!$quoteFresh){throw 'MT5 broker quote did not become fresh within the 150-second observation window.'}
 if($runBrokerAcceptance){
  $actualAccountServer=[string]$telemetry.account.server
  if($actualAccountServer -ne $expectedDemoAccountServer){
   throw 'Broker acceptance aborted before any order: the connected MT5 account server does not match Headway-Demo.'
  }
  if([string]$telemetry.market_symbol -ne 'BTCUSDT'){
   throw 'Broker acceptance aborted before any order: the expected market mapping is BTCUSDT.'
  }
  Add-Report 'PASS — Live MT5 telemetry confirms the actual account server is Headway-Demo and market mapping is BTCUSDT.'
 }
 if($executionEnabled){
  Add-Report 'PASS — Mirsad EA heartbeat is live; execution input and MT5 automated-trading permissions are enabled.'
 }else{
  Add-Report 'PASS — Mirsad EA heartbeat is live in read-only validation mode.'
 }
 Add-Report ("Broker symbol: {0}; market mapping: {1}; account currency: {2}" -f $telemetry.symbol,$telemetry.market_symbol,$telemetry.account.currency)
 Add-Report ("Current Ask quote available: {0}" -f ([double]$telemetry.quote.ask -gt 0))
 Add-Report ("Broker tick age (seconds): {0}" -f $telemetry.quote.tick_age_seconds)
 if([double]$telemetry.quote.tick_age_seconds -gt 10 -or [double]$telemetry.quote.tick_age_seconds -lt 0){throw 'Broker quote tick is stale or has an invalid age.'}
 Add-Report 'PASS — No existing MIR1 command was injected by the transport check; the controlled acceptance transaction now runs through MT5BridgeEngine.'

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

 $commonFilesRoot=Split-Path -Parent $folder
 if($runLiveRuntimeCycle){
  $expectedRoot=[IO.Path]::GetFullPath([string]$env:MIRSAD_EXPECTED_COMMON_FILES)
  foreach($relative in @('MirsadBTC\market.json','MirsadBTC\observer\candles.json','MirsadBTC\observer\indicators.json')){
   if(!(Test-Path -LiteralPath (Join-Path $expectedRoot $relative))){throw ("Shared Observer feed disappeared: {0}" -f $relative)}
  }
  $expectedStatusPath=Join-Path $expectedRoot 'MirsadBTC\status.json'
  $actualStatusPath=Join-Path $folder 'status.json'
  if(!(Test-Path -LiteralPath $expectedStatusPath) -or !(Test-Path -LiteralPath $actualStatusPath)){throw 'Execution EA status.json is not visible through both Common Files paths.'}
  $sharedIdentityConfirmed=$false
  for($sharedAttempt=1;$sharedAttempt -le 8;$sharedAttempt++){
   $expectedStatus=Get-Content -LiteralPath $expectedStatusPath -Raw|ConvertFrom-Json -ErrorAction Stop
   $actualStatus=Get-Content -LiteralPath $actualStatusPath -Raw|ConvertFrom-Json -ErrorAction Stop
   if([int64]$expectedStatus.heartbeat_at_ms -gt 0 -and [int64]$expectedStatus.heartbeat_at_ms -eq [int64]$actualStatus.heartbeat_at_ms){$sharedIdentityConfirmed=$true;break}
   Start-Sleep -Milliseconds 300
  }
  if(!$sharedIdentityConfirmed){throw 'Execution EA heartbeat differs across Observer and execution Common Files paths.'}
  Add-Report 'PASS — Observer and ExecutionBridge are publishing through the same live MT5 Common Files directory.'
 }

  if($runLiveRuntimeCycle){
  $env:PYTHONPATH=(Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC')
  $env:MIRSAD_MT5_COMMON_FILES=$commonFilesRoot
  $env:MIRSAD_ENABLE_ORDER_PUBLISH='1'
  $env:MIRSAD_DATA_DIR=Join-Path $root 'integrated-runtime-data'
  $runtimeCheck=Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\mirsad_runtime_integration_check.py'
  $runtimeReport=Join-Path $evidence 'mirsad-live-runtime-integration.json'
  if(!(Test-Path -LiteralPath $runtimeCheck)){throw 'The live runtime integration checker is missing.'}
  $runtimeOutput=& python -u $runtimeCheck --common-files $commonFilesRoot --report $runtimeReport 2>&1
  $runtimeExit=$LASTEXITCODE
  $runtimeOutput|Set-Content -LiteralPath (Join-Path $evidence 'mirsad-live-runtime-integration.log') -Encoding utf8
  if($runtimeExit -ne 0 -or !(Test-Path -LiteralPath $runtimeReport)){throw 'The five-engine live runtime integration did not pass; inspect mirsad-live-runtime-integration.json.'}
  $runtimeSummary=Get-Content -LiteralPath $runtimeReport -Raw|ConvertFrom-Json -ErrorAction Stop
  if($runtimeSummary.schema -ne 'MIRSAD-LIVE-RUNTIME-INTEGRATION-1' -or $runtimeSummary.status -ne 'PASS'){throw 'The integrated runtime report did not confirm all required engine and execution checks.'}
  Add-Report ("PASS — Integrated five-engine runtime cycle: Engine1={0}; Engine2={1} ({2}); Engine3={3}; Engine4={4}; Engine5={5}; action={6}; decision-readiness={7}; entry-eligible={8}; publishing={9}; execution-gate={10}." -f $runtimeSummary.engines.engine1.status,$runtimeSummary.engines.engine2.status,$runtimeSummary.engines.engine2.direction,$runtimeSummary.engines.engine3.calculated_status,$runtimeSummary.engines.engine4.status,$runtimeSummary.engines.engine5.status,$runtimeSummary.engines.engine4.action,$runtimeSummary.decision_readiness,$runtimeSummary.directional_entry_eligible,$runtimeSummary.checks.order_publishing_enabled,$runtimeSummary.checks.engine5_command_gate_ready)
 }

 # A broker transaction is an explicit manual opt-in. Normal validation is
 # read-only: compile, attach, observe the MIR1 heartbeat/quote and validate
 # the broker deal-history envelope without creating a position.
 if ($runBrokerAcceptance) {
  $env:PYTHONPATH=(Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC')
  $env:MIRSAD_MT5_COMMON_FILES=$commonFilesRoot
  $env:MIRSAD_ENABLE_ORDER_PUBLISH='1'
  $acceptanceScript=Join-Path $env:GITHUB_WORKSPACE 'Mirsad_BTC\scripts\mirsad_mt5_execution_acceptance.py'
  $acceptanceReport=Join-Path $evidence 'mirsad-order-acceptance.json'
  $acceptanceLog=Join-Path $evidence 'mirsad-order-acceptance.log'
  if(!(Test-Path $acceptanceScript)){throw 'MIR1 execution acceptance script is missing.'}
  $acceptanceOutput=& python -u $acceptanceScript --common-files $commonFilesRoot --report $acceptanceReport --timeout 60 2>&1
  $acceptanceExit=$LASTEXITCODE
  $acceptanceOutput|Set-Content -LiteralPath $acceptanceLog -Encoding utf8
  if($acceptanceExit -ne 0){throw 'MIR1 BUY/CLOSE acceptance test failed; inspect the sanitized acceptance artifact.'}
  if(!(Test-Path $acceptanceReport)){throw 'MIR1 acceptance script did not write its result report.'}
  $acceptance=Get-Content -LiteralPath $acceptanceReport -Raw|ConvertFrom-Json -ErrorAction Stop
  if($acceptance.schema -ne 'MIR1-EXECUTION-ACCEPTANCE-1' -or $acceptance.status -ne 'SUCCESS' -or
     $acceptance.trade.deal_cycle.state -ne 'CLOSED' -or
     [int]$acceptance.trade.deal_cycle.entry_count -lt 1 -or
     [int]$acceptance.trade.deal_cycle.exit_count -lt 1){throw 'MIR1 acceptance report did not prove a closed broker deal cycle.'}
  Add-Report ("PASS — Python MIR1 bridge opened and closed the bounded BTC acceptance position; net cashflow {0} {1}." -f $acceptance.trade.deal_cycle.net_deal_cashflow,$acceptance.trade.deal_cycle.currency)
  Add-Report 'PASS — Broker deal history confirms both entry and exit for the same position_id; no test position remains open.'
 } elseif($runLiveRuntimeCycle){
  Add-Report 'SKIP — Integrated runtime checked the MIR1 command boundary; bounded BUY/CLOSE transport has a separate live acceptance test.'
 } else {
  Add-Report 'SKIP — No broker order was requested. BUY/CLOSE acceptance requires explicit workflow_dispatch opt-in.'
 }
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
