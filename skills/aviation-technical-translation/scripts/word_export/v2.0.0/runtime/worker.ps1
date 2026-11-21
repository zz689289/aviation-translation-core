#requires -Version 5.1
param([Parameter(Mandatory=$true)][string]$JobPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'local_runtime.ps1')
$config=Read-WordExportConfiguration
. (Join-Path $PSScriptRoot 'native.ps1')
$job=Get-Content -LiteralPath $JobPath -Raw -Encoding UTF8 | ConvertFrom-Json
$work=$job.WorkDirectory
$utf8=New-Object Text.UTF8Encoding($false)
$script:word=$null; $script:docs=$null; $script:doc=$null; $script:bootstrap=$null
$script:bound=$null; $script:boundProcess=$null; $script:ownsWord=$false
$script:stages=New-Object 'System.Collections.Generic.List[object]'
$script:metrics=$null; $script:normalExit=$false; $script:failure=$null
$script:alertRows=New-Object 'System.Collections.Generic.List[object]';$script:quitSucceeded=$false
$script:readerTrace=$false
$script:neutralReadFlag=$false;$script:readCounter=0
function Json([string]$name,[object]$value) { [IO.File]::WriteAllText((Join-Path $work $name),($value|ConvertTo-Json -Depth 30),$utf8) }
function Release([object]$value) { if($null -ne $value -and [Runtime.InteropServices.Marshal]::IsComObject($value)){[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($value)} }
function Exact([Management.Automation.ErrorRecord]$record) { return @{Message=$record.Exception.Message;Record=($record|Out-String);HResult=('0x{0:X8}' -f $record.Exception.HResult);Stack=$record.ScriptStackTrace;Id=$record.FullyQualifiedErrorId} }
function Stage([string]$name,[scriptblock]$action) {
 $start=[DateTimeOffset]::Now; $watch=[Diagnostics.Stopwatch]::StartNew()
 Json 'current_stage.json' @{Stage=$name;Started=$start.ToString('o')}
 try { & $action | Out-Null; $status='PASS'; $errorInfo=$null }
 catch { $status='FAIL';$errorInfo=Exact $_;throw }
 finally {
  $watch.Stop();$row=@{Stage=$name;Status=$status;Started=$start.ToString('o');Finished=[DateTimeOffset]::Now.ToString('o');Seconds=$watch.Elapsed.TotalSeconds;Error=$errorInfo}
  $script:stages.Add($row);Json 'stages.json' @($script:stages.ToArray())
 }
}
function Hash([string]$path) {
 $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
 $algorithm=[Security.Cryptography.SHA256]::Create()
 try{return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}
 finally{$stream.Dispose();$algorithm.Dispose()}
}
function OpenDoc([string]$path,[bool]$readOnly) {
 [object]$file=$path;[object]$confirm=$false;[object]$ro=$readOnly;[object]$recent=$false;[object]$missing=[Type]::Missing;[object]$visible=$false
 # Package dependencies are audited before Word is created. This one-instance
 # scope handles Word's generic internal dirty-field advisory; no UI input.
 $priorAlerts=[int]$script:word.DisplayAlerts
 try{$script:word.DisplayAlerts=[int]0
  $script:alertRows.Add(@{Path=$path;Point='before_open';Prior=$priorAlerts;Readback=[int]$script:word.DisplayAlerts;Time=[DateTimeOffset]::Now.ToString('o')});Json 'alerts_scope.json' @($script:alertRows.ToArray())
  if([int]$script:word.DisplayAlerts -ne 0){throw 'OPEN_ALERT_SCOPE_READBACK_FAILED'}
  return $script:docs.Open([string]$path,$false,[bool]$readOnly,$false,$missing,$missing,$missing,$missing,$missing,$missing,$missing,$false)
 }finally{$script:word.DisplayAlerts=$priorAlerts;$script:alertRows.Add(@{Path=$path;Point='restored';Prior=$priorAlerts;Readback=[int]$script:word.DisplayAlerts;Time=[DateTimeOffset]::Now.ToString('o')});Json 'alerts_scope.json' @($script:alertRows.ToArray());if([int]$script:word.DisplayAlerts -ne $priorAlerts){throw 'OPEN_ALERT_RESTORE_FAILED'}}
}
function CloseDoc([object]$document) {
 [object]$save=0;[object]$format=[Type]::Missing;[object]$route=[Type]::Missing
 $document.Close([int]0)
}
function ReadMark([string]$point){if($script:readerTrace -and -not $script:doc.Saved -and -not [IO.File]::Exists((Join-Path $work 'first_dirty_reader.json'))){Json 'first_dirty_reader.json' @{Point=$point;Time=[DateTimeOffset]::Now.ToString('o')}}}
function WalkFields([object]$range,[string]$story,[bool]$update,[int]$depth=0) {
 if($depth -gt 20){throw 'FIELD_RECURSION_LIMIT'}
 $fields=$null
 try {
  $fields=$range.Fields
  for($index=1;$index -le [int]$fields.Count;$index++) {
   $field=$null;$codeRange=$null;$resultRange=$null
   try {
    $field=$fields.Item($index);$codeRange=$field.Code;$resultRange=$field.Result
    ReadMark ('FieldCodeResult '+$story+' '+$index)
    $key=$story+':'+$codeRange.Start+':'+$codeRange.End
    if(-not $script:seen.Add($key)){continue}
    $code=[string]$codeRange.Text;$token=([regex]::Match($code,'^\s*([A-Za-z]+|=)')).Groups[1].Value.ToUpperInvariant()
    if($token -notin @('TOC','PAGEREF','REF','NOTEREF','SEQ','PAGE','NUMPAGES','SECTION','SECTIONPAGES','STYLEREF','DOCPROPERTY','DOCVARIABLE','IF','QUOTE','COMPARE','=','SYMBOL','HYPERLINK','SHAPE')){throw ('UNSUPPORTED_FIELD_CODE: '+$code)}
    if($token -eq 'SHAPE' -and $code -notmatch '^\s*SHAPE(?:\s+\\\*\s+MERGEFORMAT)?\s*$'){throw ('UNRECOGNIZED_SHAPE_FIELD: '+$code)}
    WalkFields $codeRange $story $update ($depth+1)
    ReadMark ('WalkCode '+$story+' '+$code)
    if($update -and $token -notin @('TOC','HYPERLINK','SHAPE')){
     if($field.Locked){throw ('LOCKED_INTERNAL_FIELD: '+$code)};if(-not $field.Update()){throw ('FIELD_UPDATE_FAILED: '+$code)}
     if($token -in @('NUMPAGES','PAGE','SECTIONPAGES')){$calculated=[string]$resultRange.Text;$resultRange.Text=$calculated}
    }
    WalkFields $resultRange $story $update ($depth+1)
    ReadMark ('WalkResult '+$story+' '+$code)
    $script:fieldRows.Add([pscustomobject]@{Story=$story;StoryType=[int]$resultRange.StoryType;Section=[int]$resultRange.Information([int]2);Token=$token;Code=$code.Trim();Text=[string]$resultRange.Text;CodeStart=[int]$codeRange.Start;Start=[int]$resultRange.Start;End=[int]$resultRange.End;PhysicalEndPage=[int]$resultRange.Information([int]3);AdjustedEndPage=[int]$resultRange.Information([int]1)})
   } finally {Release $resultRange;Release $codeRange;Release $field}
  }
 } finally {Release $fields}
}
function ShapeFields([object]$shapes,[string]$story,[bool]$update,[int]$depth=0) {
 if($depth -gt 10){throw 'SHAPE_RECURSION_LIMIT'}
 for($si=1;$si -le [int]$shapes.Count;$si++) {
  $shape=$null;$frame=$null;$text=$null;$group=$null
  try {
   $shape=$shapes.Item($si)
   if([int]$shape.Type -eq 6){$group=$shape.GroupItems;ShapeFields $group ($story+'/group'+$si) $update ($depth+1)}
   $frame=$shape.TextFrame
   ReadMark ('TextFrame '+$story+' '+$si)
   if([int]$frame.HasText -ne 0){$text=$frame.TextRange;WalkFields $text ($story+'/shape'+$si) $update}
  } finally {Release $group;Release $text;Release $frame;Release $shape}
 }
}
function AllFields([bool]$update) {
 $readWasClean=([bool]$script:doc.Saved -or $script:neutralReadFlag)
 $flatBefore=$null
 if(-not $update -and $job.HasTextboxes -and $readWasClean){$flatRawBefore=[string]$script:doc.WordOpenXML;$flatBefore=$true}
 $script:seen=New-Object 'System.Collections.Generic.HashSet[string]'
 $script:fieldRows=New-Object 'System.Collections.Generic.List[object]'
 $script:storyRows=New-Object 'System.Collections.Generic.List[object]'
 $stories=$null
 try {
  $stories=$script:doc.StoryRanges
  foreach($root in $stories){
   $range=$root;$part=0
   while($null -ne $range){
    $next=$null;$shapes=$null
    try {
     $label=([string]$range.StoryType)+':'+$part
     WalkFields $range $label $update
     ReadMark ('AfterFields '+$label)
     $shapes=$range.ShapeRange
     ReadMark ('ShapeRange '+$label)
     ShapeFields $shapes $label $update
     ReadMark ('AfterShapes '+$label)
     $script:storyRows.Add([pscustomobject]@{Story=$label;Text=[string]$range.Text})
     $next=$range.NextStoryRange
    } finally {Release $shapes;Release $range}
    $range=$next;$part++
   }
  }
 } finally {Release $stories}
 $content=$null
 try{$content=$script:doc.Content;$pageCount=[int]$content.Information([int]4)}finally{Release $content}
 # A read must stay nonmutating and bounded. Per-field page/section/offset evidence
 # plus Saved readback covers reopen/export stability; final dual-render tests
 # compare EVERY decoded PDF page separately, outside the COM deadline.
 if($null -ne $flatBefore){
  $flatRawAfter=[string]$script:doc.WordOpenXML
  $script:neutralReadFlag=$true;$script:readCounter++
  [IO.File]::WriteAllText((Join-Path $work ('read_'+$script:readCounter+'_before.xml')),$flatRawBefore,$utf8)
  [IO.File]::WriteAllText((Join-Path $work ('read_'+$script:readCounter+'_after.xml')),$flatRawAfter,$utf8)
  Json ('read_package_pending_'+$script:readCounter+'.json') @{Status='PENDING_EXTERNAL_VALIDATION';SavedBeforeOrPriorPendingCheck=$readWasClean;SavedAfter=[bool]$script:doc.Saved;NoSavedFlagAssignment=$true;RequiredComparison='ALL_PARTS_EXCEPT_RSIDs_ONLY'}
 }
 return [pscustomobject]@{Fields=@($script:fieldRows.ToArray());Stories=@($script:storyRows.ToArray());Pages=$pageCount}
}
function UpdateTOCs([bool]$pagesOnly) {
 $tocs=$null
 try {$tocs=$script:doc.TablesOfContents;for($index=1;$index -le $tocs.Count;$index++){$toc=$null;try{$toc=$tocs.Item($index);if($pagesOnly){$toc.UpdatePageNumbers()}else{$toc.Update()}}finally{Release $toc}}}
 finally {Release $tocs}
}
function Signature([object]$snapshot){
 # Word canonicalizes hidden field instruction runs on Save/reopen. Raw CP
 # offsets are diagnostic identities within one session, not display positions.
 $projection=[pscustomobject]@{Pages=$snapshot.Pages;Stories=$snapshot.Stories;Fields=@($snapshot.Fields|Select-Object Story,StoryType,Section,Token,Code,Text,PhysicalEndPage,AdjustedEndPage)}
 return ($projection|ConvertTo-Json -Depth 12 -Compress)
}
function SavedEvidence([string]$point,[bool]$xml=$false){
 Json ($point+'_state.json') @{Saved=[bool]$script:doc.Saved;ReadOnly=[bool]$script:doc.ReadOnly;Point=$point;Time=[DateTimeOffset]::Now.ToString('o')}
}
try {
 Stage 'environment' {
  $self=[Diagnostics.Process]::GetCurrentProcess();$identity=[Security.Principal.WindowsIdentity]::GetCurrent();$principal=New-Object Security.Principal.WindowsPrincipal($identity)
  $envData=@{Username=$identity.Name;IsAdministrator=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);SessionId=$self.SessionId;Is64Bit=[Environment]::Is64BitProcess;PSVersion=$PSVersionTable.PSVersion.ToString();STA=([Threading.Thread]::CurrentThread.ApartmentState.ToString() -eq 'STA')}
  Json 'environment.json' $envData
  if($identity.User.Value -ne $config.UserSid -or $envData.IsAdministrator -or $envData.SessionId -eq 0 -or -not $envData.Is64Bit -or -not $envData.STA -or $PSVersionTable.PSVersion.Major -ne 5){throw 'REQUIRED_NONADMIN_INTERACTIVE_WINPS51_STA_IDENTITY_NOT_AVAILABLE'}
 }
 $before=@([Diagnostics.Process]::GetProcessesByName('WINWORD')|ForEach-Object {$_.Id})
 Json 'word_processes_before.json' $before
 Stage 'create_owned_hidden_instance' {
  $creation=[DateTime]::UtcNow.Ticks
  $script:word=New-Object -ComObject Word.Application
  $script:docs=$script:word.Documents
  $script:bootstrap=OpenDoc (Join-Path $work 'bootstrap.docx') $true
  $windows=$null;$window=$null
  try {
   $windows=$script:bootstrap.Windows;$window=$windows.Item(1);[long]$handle=$window.Hwnd
   if($handle -eq 0 -or -not [WordNative]::IsWindow([IntPtr]$handle)){throw 'INVALID_BOOTSTRAP_DOCUMENT_HWND'}
   $number=[WordNative]::ProcessOf($handle);$process=[Diagnostics.Process]::GetProcessById([int]$number);[void]$process.Handle
   if($number -in $before -or $process.ProcessName -ine 'WINWORD' -or $process.StartTime.ToUniversalTime().Ticks -lt $creation -or $process.SessionId -ne [Diagnostics.Process]::GetCurrentProcess().SessionId){$process.Dispose();throw 'WORD_INSTANCE_NOT_NEW_OWNED_PROCESS'}
   $script:bound=@{ProcessId=$number;StartTicks=$process.StartTime.ToUniversalTime().Ticks;SessionId=$process.SessionId;JobId=$job.JobId;Window=$handle;WorkerProcessId=[Diagnostics.Process]::GetCurrentProcess().Id}
   $script:boundProcess=$process;$script:ownsWord=$true
   Json 'word_identity.pending.json' $script:bound
   [IO.File]::Move((Join-Path $work 'word_identity.pending.json'),(Join-Path $work 'word_identity.json'))
  } finally {Release $window;Release $windows}
  $script:word.Visible=$false;$script:word.DisplayAlerts=[int]-1
  if($script:word.Visible){throw 'HIDDEN_WORD_READBACK_FAILED'}
  # Ownership is already retained by exact process handle; no unrelated active
  # bootstrap document may influence header/footer field calculation or save.
  CloseDoc $script:bootstrap;Release $script:bootstrap;$script:bootstrap=$null
 }
 Stage 'open' {
  if((Hash $job.DocumentPath) -cne $job.CopySHA256){throw 'PREPARED_COPY_CHANGED_BEFORE_OPEN'}
  $script:doc=OpenDoc $job.DocumentPath ($job.Mode -eq 'ReadOnly')
  SavedEvidence 'first_open'
  if([IO.Path]::GetFullPath($script:doc.FullName) -ine [IO.Path]::GetFullPath($job.DocumentPath)){throw 'WRONG_DOCUMENT_OBJECT'}
  if([bool]$script:doc.ReadOnly -ne ($job.Mode -eq 'ReadOnly')){throw 'WRONG_DOCUMENT_OPEN_MODE'}
 }
 if($job.Mode -eq 'UpdateSave') {
  Stage 'update_internal_fields' {$null=AllFields $true}
  Stage 'update_whole_toc' {UpdateTOCs $false}
  Stage 'stabilize_pagination' {
   $previous=$null;$stable=$false
   for($cycle=1;$cycle -le 5;$cycle++){
    $script:doc.Repaginate();$null=AllFields $true;UpdateTOCs $true;$script:doc.Repaginate();$snapshot=AllFields $false
    Json ('pagination_'+$cycle+'.json') $snapshot
    $current=Signature $snapshot
    if($current -ceq $previous){$stable=$true;break};$previous=$current
   }
   if(-not $stable){throw 'FIELDS_OR_PAGINATION_DID_NOT_CONVERGE'}
  }
  Stage 'save' {
   # ComputeStatistics mutates document statistics. It belongs BEFORE Save,
   # never in a supposedly read-only post-save/reopen inspector.
   $actualPages=[int]$script:doc.ComputeStatistics([int]2)
   $null=AllFields $true
   Json 'before_save_statistics.json' @{ComputedPages=$actualPages}
   $script:doc.Save()
   $script:neutralReadFlag=$false
   while([int]$script:word.BackgroundSavingStatus -gt 0){Start-Sleep -Milliseconds 50}
   if(-not $script:doc.Saved){throw 'SAVE_RETURNED_UNSAVED_DOCUMENT'}
   SavedEvidence 'save_returned'
   $script:readerTrace=$true
   $script:metrics=AllFields $false;Json 'saved_display.json' $script:metrics
   SavedEvidence 'saved_snapshot' $true
   if(-not $script:doc.Saved -and -not $script:neutralReadFlag){throw 'READ_SNAPSHOT_MODIFIED_SAVED_DOCUMENT'}
  }
  Stage 'close_saved_document' {CloseDoc $script:doc;Release $script:doc;$script:doc=$null}
  Stage 'reopen_saved_copy' {
   $script:savedHash=Hash $job.DocumentPath
   $script:doc=OpenDoc $job.DocumentPath $true;$script:neutralReadFlag=$false;SavedEvidence 'reopen_returned' $true
   if(-not $script:doc.Saved){throw 'REOPENED_DOCUMENT_INITIAL_STATE_IS_DIRTY'}
   $script:doc.Repaginate();SavedEvidence 'reopen_repaginated'
   $reopened=AllFields $false;Json 'reopened_display.json' $reopened
   SavedEvidence 'reopened_snapshot' $true
   if((Signature $reopened) -cne (Signature $script:metrics)){throw 'UNSAVED_DISPLAY_OR_PAGINATION_CHANGE_AFTER_REOPEN'}
   if(-not $script:doc.Saved -and -not $script:neutralReadFlag){throw 'REOPENED_DOCUMENT_IS_DIRTY'}
   if((Hash $job.DocumentPath) -cne $script:savedHash){throw 'REOPEN_CHANGED_SAVED_BYTES'}
  }
 } else {
  Stage 'readonly_pagination' {if(-not $script:doc.Saved){throw 'READONLY_INITIAL_STATE_IS_DIRTY'};$script:doc.Repaginate();$script:metrics=AllFields $false;Json 'readonly_display.json' $script:metrics;$script:savedHash=Hash $job.DocumentPath;if(-not $script:doc.Saved -and -not $script:neutralReadFlag){throw 'READONLY_OPEN_OR_READ_CHANGED_DOCUMENT'}}
 }
 Stage 'bookmark_page_evidence' {
  $names=New-Object 'System.Collections.Generic.HashSet[string]'
  if($job.Mode -eq 'ReadOnly'){foreach($name in $job.ReferencedBookmarks){[void]$names.Add([string]$name)}}
  foreach($field in $script:metrics.Fields){$match=[regex]::Match($field.Code,'^\s*(?:PAGE|NOTE)?REF\s+(?:"([^"]+)"|([^\s\\]+))',[Text.RegularExpressions.RegexOptions]::IgnoreCase);if($match.Success){$name=$match.Groups[1].Value;if(-not $name){$name=$match.Groups[2].Value};[void]$names.Add($name)}}
  $script:bookmarkRows=New-Object 'System.Collections.Generic.List[object]';$bookmarks=$null
  try{$bookmarks=$script:doc.Bookmarks;foreach($name in $names){if(-not $bookmarks.Exists($name)){throw ('BOOKMARK_DISAPPEARED: '+$name)};$bookmark=$null;$range=$null;try{$bookmark=$bookmarks.Item([object]$name);$range=$bookmark.Range;$script:bookmarkRows.Add([pscustomobject]@{Name=$name;Text=[string]$range.Text;PhysicalPage=[int]$range.Information([int]3);AdjustedPage=[int]$range.Information([int]1)})}finally{Release $range;Release $bookmark}}}finally{Release $bookmarks}
 }
 Stage 'export_pdf' {
  [IO.File]::WriteAllText((Join-Path $work 'export_before.xml'),[string]$script:doc.WordOpenXML,$utf8)
  $script:doc.ExportAsFixedFormat([string]$job.PdfPath,[int]17,$false,[int]0,[int]0,[int]1,[int]1,[int]0,$true,$true,[int]0,$true,$true,$false)
  $after=AllFields $false;Json 'after_export_display.json' $after
  if((Signature $after) -cne (Signature $script:metrics) -or (-not $script:doc.Saved -and -not $script:neutralReadFlag)){throw 'UNSAVED_DISPLAY_OR_PAGINATION_CHANGE_DURING_EXPORT'}
  [IO.File]::WriteAllText((Join-Path $work 'export_after.xml'),[string]$script:doc.WordOpenXML,$utf8)
  Json 'export_package_pending.json' @{Status='PENDING_EXTERNAL_VALIDATION';SavedAfter=[bool]$script:doc.Saved;ReadFlagRequiresRSIDOnlyProof=$script:neutralReadFlag}
  if((Hash $job.DocumentPath) -cne $script:savedHash){throw 'EXPORT_CHANGED_SAVED_BYTES'}
 }
} catch {$script:failure=Exact $_;Json 'worker_error.json' $script:failure}
finally {
 function CleanupStage([string]$name,[scriptblock]$action){try{Stage $name $action}catch{if($null -eq $script:failure){$script:failure=Exact $_};Json ('cleanup_'+$name+'_error.json') (Exact $_)}}
  if($null -ne $script:doc){CleanupStage 'close' {try{CloseDoc $script:doc}finally{Release $script:doc;$script:doc=$null}}}
  if($null -ne $script:bootstrap){CleanupStage 'close_bootstrap' {try{CloseDoc $script:bootstrap}finally{Release $script:bootstrap;$script:bootstrap=$null}}}
  if($script:ownsWord){CleanupStage 'quit' {
   [object]$quitSaveChanges=0;[object]$quitOriginalFormat=[Type]::Missing;[object]$quitRouteDocument=[Type]::Missing
   $script:word.Quit([ref]$quitSaveChanges,[ref]$quitOriginalFormat,[ref]$quitRouteDocument)
   $script:quitSucceeded=$true
  }}
  CleanupStage 'release_com' {Release $script:doc;Release $script:bootstrap;Release $script:docs;Release $script:word;$script:doc=$null;$script:bootstrap=$null;$script:docs=$null;$script:word=$null;[GC]::Collect();[GC]::WaitForPendingFinalizers();[GC]::Collect();[GC]::WaitForPendingFinalizers()}
  if($script:ownsWord -and $script:quitSucceeded){CleanupStage 'normal_exit' {if(-not $script:boundProcess.WaitForExit(10000)){throw 'OWNED_WORD_DID_NOT_EXIT_NORMALLY'};$script:normalExit=$true}}
 if($null -ne $script:boundProcess){$script:boundProcess.Dispose()}
 foreach($planned in @('environment','create_owned_hidden_instance','open','update_internal_fields','update_whole_toc','stabilize_pagination','save','close_saved_document','reopen_saved_copy','readonly_pagination','bookmark_page_evidence','export_pdf','close','quit','release_com','normal_exit')){
  if(-not (@($script:stages.ToArray()|Where-Object {$_.Stage -eq $planned}).Count)){$script:stages.Add(@{Stage=$planned;Status='NOT_RUN';Seconds=$null;Reason=$(if($job.Mode -eq 'ReadOnly' -and $planned -in @('update_internal_fields','update_whole_toc','stabilize_pagination','save','close_saved_document','reopen_saved_copy')){'READONLY_MODE'}elseif($job.Mode -eq 'UpdateSave' -and $planned -eq 'readonly_pagination'){'UPDATESAVE_MODE'}else{'EARLIER_STAGE_FAILED'});Error=$null})}
 }
 $status=if($null -eq $script:failure -and $script:normalExit){'PASS'}else{'FAIL'}
 $bookmarks=if(Get-Variable -Name bookmarkRows -Scope Script -ErrorAction SilentlyContinue){@($script:bookmarkRows.ToArray())}else{@()}
 Json 'worker_result.json' @{Status=$status;NormalExit=$script:normalExit;Error=$script:failure;WordPages=$(if($null -ne $script:metrics){$script:metrics.Pages}else{$null});Bookmarks=$bookmarks;Stages=@($script:stages.ToArray())}
}
if($status -eq 'PASS'){exit 0};exit 1
