#requires -Version 5.1
[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$InputPath,
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [ValidateSet('UpdateSave','ReadOnly')][string]$Mode='UpdateSave',
 [ValidateRange(15,600)][int]$WordTimeoutSeconds=90,
 [ValidateRange(1,3600)][int]$QueueTimeoutSeconds=600,
 [string[]]$ExpectedText=@()
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$utf8=New-Object Text.UTF8Encoding($false)
. (Join-Path $PSScriptRoot 'local_runtime.ps1')
$config=Read-WordExportConfiguration
$python=$config.Python
$shellPath=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$root=[IO.Path]::GetFullPath($OutputDirectory)
$mutex=$null;$locked=$false;$child=$null;$binding=$null;$workerIdentity=$null;$validationIdentity=$null;$verification=$null
$status='FAIL';$errorInfo=$null;$cleanup=New-Object 'System.Collections.Generic.List[object]';$snapshots=New-Object 'System.Collections.Generic.List[object]'
$started=[DateTimeOffset]::Now;$queueSeconds=$null;$wordNormalExit=$false;$timedOut=$false;$phase='preflight';$lastDialog=$null;$dialogWatch=$null
$source=$null;$sourceHash=$null;$sourceGuard=$null;$sourceUnchanged=$null;$residual=$null;$worker=$null;$wordElapsed=$null
function Json([string]$name,[object]$value){[IO.File]::WriteAllText((Join-Path $root $name),($value|ConvertTo-Json -Depth 30),$utf8)}
function ErrorData([Management.Automation.ErrorRecord]$record){return @{Message=$record.Exception.Message;Record=($record|Out-String);HResult=('0x{0:X8}' -f $record.Exception.HResult);Stack=$record.ScriptStackTrace}}
function Identity([Diagnostics.Process]$process){[void]$process.Handle;return @{ProcessId=$process.Id;StartTicks=$process.StartTime.ToUniversalTime().Ticks;SessionId=$process.SessionId;Name=$process.ProcessName}}
function StopOwned([object]$who,[string]$reason){
 if($null -eq $who){return}
 $process=$null
 try{
  try{$process=[Diagnostics.Process]::GetProcessById([int]$who.ProcessId)}catch [ArgumentException]{$cleanup.Add(@{Status='ALREADY_EXITED';Identity=$who;Reason=$reason});return}
  [void]$process.Handle
  if($process.StartTime.ToUniversalTime().Ticks -ne [long]$who.StartTicks -or $process.SessionId -ne [int]$who.SessionId -or $process.ProcessName -ine $who.Name){throw 'CLEANUP_OWNERSHIP_MISMATCH'}
  Json ('cleanup_identity_before_kill_'+$who.ProcessId+'_'+$cleanup.Count+'.json') @{Identity=$who;Verified=Identity $process;Reason=$reason;Time=[DateTimeOffset]::Now.ToString('o')}
  $process.Kill();$exited=$process.WaitForExit(3000);$cleanup.Add(@{Status=$(if($exited){'TERMINATED'}else{'EXIT_NOT_CONFIRMED'});Identity=$who;Reason=$reason})
 }catch{$cleanup.Add(@{Status='REFUSED_OR_FAILED';Identity=$who;Error=ErrorData $_})}finally{if($null -ne $process){$process.Dispose()}}
}
function Arg([string]$text){if($text.Contains('"') -or $text.Contains("`n") -or $text.Contains("`r")){throw 'INVALID_ARGUMENT'};return '"'+$text+'"'}
function RunPython([string]$operation,[int]$seconds){
 $p=Start-Process -FilePath $python -ArgumentList @('-X','utf8','-I','-B',(Arg (Join-Path $PSScriptRoot 'package_ops.py')),$operation,(Arg (Join-Path $root 'job.json'))) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root ($operation+'.stdout.txt')) -RedirectStandardError (Join-Path $root ($operation+'.stderr.txt'))
 try{$who=Identity $p;Json ($operation+'_process.json') $who;if(-not $p.WaitForExit($seconds*1000)){StopOwned $who ($operation+'_TIMEOUT');throw ($operation.ToUpperInvariant()+'_TIMEOUT')};if($p.ExitCode -ne 0){throw ($operation.ToUpperInvariant()+'_FAILED: '+[IO.File]::ReadAllText((Join-Path $root ($operation+'.stderr.txt')),$utf8))}}finally{$p.Dispose()}
}
if(Test-Path -LiteralPath $root){[Console]::WriteLine((@{Status='FAIL';Stage='preflight';Error='OUTPUT_DIRECTORY_ALREADY_EXISTS_NO_OVERWRITE';OutputDirectory=$root}|ConvertTo-Json -Compress));exit 1}
[void](New-Item -ItemType Directory -Path $root -ErrorAction Stop)
try{
 $id=[Security.Principal.WindowsIdentity]::GetCurrent();$principal=New-Object Security.Principal.WindowsPrincipal($id);$self=[Diagnostics.Process]::GetCurrentProcess()
 $envData=@{Username=$id.Name;UserSid=$id.User.Value;Administrator=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);SessionId=$self.SessionId;ProcessId=$self.Id;PSVersion=$PSVersionTable.PSVersion.ToString();Is64Bit=[Environment]::Is64BitProcess;Apartment=[Threading.Thread]::CurrentThread.ApartmentState.ToString();ExecutionPolicies=@(Get-ExecutionPolicy -List|ForEach-Object{@{Scope=$_.Scope.ToString();Policy=$_.ExecutionPolicy.ToString()}})}
 Json 'environment.json' $envData
 if($id.User.Value -ne $config.UserSid -or $envData.Administrator -or $envData.SessionId -eq 0 -or -not $envData.Is64Bit -or $envData.Apartment -ne 'STA' -or $PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'REQUIRED_NONADMIN_INTERACTIVE_WINPS51_STA_IDENTITY_NOT_AVAILABLE'}
 $source=(Get-Item -LiteralPath $InputPath -ErrorAction Stop).FullName
 $sourceGuard=[IO.File]::Open($source,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
 $sourceHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
 if([IO.Path]::GetExtension($source) -ine '.docx'){throw 'DOCX_INPUT_REQUIRED'}
 $work=Join-Path $root '.work';$jobId=[Guid]::NewGuid().ToString('N')
 Json 'job.json' @{JobId=$jobId;InputPath=$source;OutputDirectory=$root;WorkDirectory=$work;Mode=$Mode;ExpectedText=@($ExpectedText);WordTimeoutSeconds=$WordTimeoutSeconds}
 Json 'runtime_hashes.json' @(Get-ChildItem -LiteralPath $PSScriptRoot -File|ForEach-Object {@{Name=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}})
 $drive=Get-PSDrive -Name C;Json 'storage.json' @{CFreeBytes=$drive.Free;OutputWriteVerified=$true}
 $phase='prepare';RunPython 'prepare' 90
 . (Join-Path $PSScriptRoot 'native.ps1')
 $mutexName='Local\Codex.WordExport.v2.'+$id.User.Value
 $mutex=New-Object Threading.Mutex($false,$mutexName)
 $phase='queue';$queueWatch=[Diagnostics.Stopwatch]::StartNew()
 try{$locked=$mutex.WaitOne($QueueTimeoutSeconds*1000)}catch [Threading.AbandonedMutexException]{$locked=$true;Json 'abandoned_mutex.json' (ErrorData $_)}
 $queueWatch.Stop();$queueSeconds=$queueWatch.Elapsed.TotalSeconds
 if(-not $locked){throw 'QUEUE_TIMEOUT'}
 Json 'mutex.json' @{Name=$mutexName;Acquired=[DateTimeOffset]::Now.ToString('o');WaitSeconds=$queueSeconds;ProcessId=$self.Id}
 $phase='word';$wordWatch=[Diagnostics.Stopwatch]::StartNew()
 $child=Start-Process -FilePath $shellPath -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','RemoteSigned','-File',(Arg (Join-Path $PSScriptRoot 'worker.ps1')),'-JobPath',(Arg (Join-Path $root 'job.json'))) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root 'worker.stdout.txt') -RedirectStandardError (Join-Path $root 'worker.stderr.txt')
 $workerIdentity=Identity $child;Json 'worker_identity.json' $workerIdentity
 while(-not $child.HasExited){
  if($null -eq $binding -and [IO.File]::Exists((Join-Path $work 'word_identity.json'))){
   $candidate=Get-Content -LiteralPath (Join-Path $work 'word_identity.json') -Raw -Encoding UTF8|ConvertFrom-Json
   if($candidate.JobId -cne $jobId -or $candidate.WorkerProcessId -ne $workerIdentity.ProcessId -or $candidate.SessionId -ne $self.SessionId){throw 'WORD_OWNERSHIP_RECORD_MISMATCH'}
   $binding=@{ProcessId=$candidate.ProcessId;StartTicks=$candidate.StartTicks;SessionId=$candidate.SessionId;Name='WINWORD'}
   if(@($snapshots.ToArray()|Where-Object {$_.ProcessId -eq $binding.ProcessId}).Count -gt 0){throw 'OWNED_WORD_STOLE_FOREGROUND_BEFORE_BINDING'}
  }
  $front=[WordNative]::GetForegroundWindow();$frontNumber=[WordNative]::ProcessOf($front.ToInt64())
  $snapshots.Add(@{Time=[DateTimeOffset]::Now.ToString('o');Hwnd=$front.ToInt64();ProcessId=$frontNumber})
  if($null -ne $binding){
   if($frontNumber -eq [uint32]$binding.ProcessId){throw 'OWNED_WORD_STOLE_FOREGROUND'}
   $dialogs=@([WordNative]::Windows([uint32]$binding.ProcessId)|Where-Object {($_.Class -eq '#32770' -or $_.Class.StartsWith('bosa_sdm')) -and $_.Text.Length -gt 0})
   if($dialogs.Count -gt 0){
    $fingerprint=($dialogs|ConvertTo-Json -Depth 5 -Compress)
    if($fingerprint -cne $lastDialog){$lastDialog=$fingerprint;$dialogWatch=[Diagnostics.Stopwatch]::StartNew()}
    if($dialogWatch.ElapsedMilliseconds -ge 500){Json 'unexpected_dialog.json' @{Time=[DateTimeOffset]::Now.ToString('o');Dialogs=$dialogs;Stage=(Get-Content -LiteralPath (Join-Path $work 'current_stage.json') -Raw -Encoding UTF8|ConvertFrom-Json)};throw 'UNEXPECTED_WORD_DIALOG_NO_INTERACTION'}
   }else{$lastDialog=$null;$dialogWatch=$null}
  }
  if($wordWatch.Elapsed.TotalSeconds -ge $WordTimeoutSeconds){$timedOut=$true;throw 'WORD_TIMEOUT'}
  [void]$child.WaitForExit(100)
 }
 $wordWatch.Stop();$child.WaitForExit()
 $wordElapsed=$wordWatch.Elapsed.TotalSeconds
 $worker=Get-Content -LiteralPath (Join-Path $work 'worker_result.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $wordNormalExit=[bool]$worker.NormalExit
 if($child.ExitCode -ne 0 -or $worker.Status -ne 'PASS' -or -not $wordNormalExit){throw ('WORD_WORKER_FAILED: '+($worker.Error|ConvertTo-Json -Depth 10 -Compress))}
 $phase='verify';RunPython 'validate' 90
 $verification=Get-Content -LiteralPath (Join-Path $work 'verification.json') -Raw -Encoding UTF8|ConvertFrom-Json
 if($verification.Status -ne 'PASS'){throw 'VALIDATION_NOT_PASS'}
 $phase='publish';$stage=Join-Path $root '.publish';[void][IO.Directory]::CreateDirectory($stage)
 $stem=[IO.Path]::GetFileNameWithoutExtension($source)
 [IO.File]::Copy((Join-Path $work 'document.docx'),(Join-Path $stage ($stem+'.docx')),$false)
 [IO.File]::Copy((Join-Path $work 'document.pdf'),(Join-Path $stage ($stem+'.pdf')),$false)
 [IO.Directory]::Move($stage,(Join-Path $root 'artifacts'))
 $status='PASS';$phase='complete'
}catch{
 $errorInfo=ErrorData $_
 if($null -ne $child -and -not $child.HasExited){StopOwned $workerIdentity $errorInfo.Message}
 if($null -ne $binding){StopOwned $binding $errorInfo.Message}
}finally{
 if($null -ne $binding){
  $residual=@([Diagnostics.Process]::GetProcessesByName('WINWORD')|Where-Object {$_.Id -eq [int]$binding.ProcessId -and $_.StartTime.ToUniversalTime().Ticks -eq [long]$binding.StartTicks}|ForEach-Object {Identity $_})
  if($residual.Count -gt 0){$status='FAIL';$wordNormalExit=$false}
 }
 if($null -ne $source -and $null -ne $sourceHash){try{$sourceUnchanged=((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $sourceHash)}catch{$sourceUnchanged=$false};if(-not $sourceUnchanged){$status='FAIL';$errorInfo=@{Message='SOURCE_INTEGRITY_CHANGED_OR_UNREADABLE';EarlierError=$errorInfo}}}
 if($null -ne $sourceGuard){$sourceGuard.Dispose()}
 Json 'foreground_observations.json' @($snapshots.ToArray())
 if($locked){$mutex.ReleaseMutex();Json 'mutex_released.json' @{Time=[DateTimeOffset]::Now.ToString('o')}}
 if($null -ne $mutex){$mutex.Dispose()};if($null -ne $child){$child.Dispose()}
 $report=@{Status=$status;Stage=$phase;Error=$errorInfo;Mode=$Mode;InputPath=$InputPath;OutputDirectory=$root;Started=$started.ToString('o');Finished=[DateTimeOffset]::Now.ToString('o');QueueWaitSeconds=$queueSeconds;WordSeconds=$wordElapsed;WordNormalExit=$wordNormalExit;WordTimedOut=$timedOut;OwnedWordResidual=$residual;SourceSHA256=$sourceHash;SourceUnchanged=$sourceUnchanged;Cleanup=@($cleanup.ToArray());Verification=$verification;Worker=$worker;NoUIInputUsed=$true;PublicationAcceptance='NOT_ASSESSED_BY_TOOL_TEST'}
 Json 'final_report.json' $report
 [Console]::WriteLine((@{Status=$status;Stage=$phase;NormalExit=$wordNormalExit;Report=(Join-Path $root 'final_report.json');Error=$(if($null -ne $errorInfo){$errorInfo.Message}else{$null})}|ConvertTo-Json -Compress))
}
if($status -eq 'PASS'){exit 0};exit 1
