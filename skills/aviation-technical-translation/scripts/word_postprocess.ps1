<#
.SYNOPSIS
Postprocess a generated DOCX with Microsoft Word COM and export an authoritative PDF.

.DESCRIPTION
Inputs are a work-copy DOCX and a JSON action file created by build_docx.py.
Outputs are the updated DOCX, PDF, Word structure statistics, and resolved TOC entries.
The caller must pass explicit paths; this script does not assume a project directory.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File word_postprocess.ps1 `
  -DocxPath WORK/working.docx -PdfPath QA/render.pdf `
  -ActionsPath WORK/draft.actions.json -StatsPath QA/word_stats.json `
  -TocEntriesPath QA/toc_entries.json
#>

param(
    [Parameter(Mandatory = $true)][string]$DocxPath,
    [Parameter(Mandatory = $true)][string]$PdfPath,
    [Parameter(Mandatory = $true)][string]$ActionsPath,
    [Parameter(Mandatory = $true)][string]$StatsPath,
    [Parameter(Mandatory = $true)][string]$TocEntriesPath
)

$ErrorActionPreference = 'Stop'
$word = $null
$document = $null
$stage = 'startup'

function Find-UniqueMarkerRange {
    param([object]$Document, [string]$Marker)
    $first = $Document.Content.Duplicate
    $find = $first.Find
    $find.ClearFormatting()
    $find.Replacement.ClearFormatting()
    $find.Text = $Marker
    $find.Forward = $true
    $find.Wrap = 0
    if (-not $find.Execute()) { throw "Required marker not found: $Marker" }

    $after = $Document.Range($first.End, $Document.Content.End)
    $findAfter = $after.Find
    $findAfter.ClearFormatting()
    $findAfter.Replacement.ClearFormatting()
    $findAfter.Text = $Marker
    $findAfter.Forward = $true
    $findAfter.Wrap = 0
    if ($findAfter.Execute()) { throw "Marker occurs more than once: $Marker" }
    return $first
}

function Update-AllStoryFields {
    param([object]$Document)
    foreach ($story in $Document.StoryRanges) {
        $current = $story
        while ($null -ne $current) {
            if ($current.Fields.Count -gt 0) { [void]$current.Fields.Update() }
            $current = $current.NextStoryRange
        }
    }
}

try {
    $stage = 'resolve inputs'
    $resolvedDocx = [IO.Path]::GetFullPath($DocxPath)
    $resolvedPdf = [IO.Path]::GetFullPath($PdfPath)
    $actions = Get-Content -LiteralPath $ActionsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $resolvedDocx -PathType Leaf)) { throw "DOCX does not exist: $resolvedDocx" }

    $stage = 'create Word COM application'
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.ScreenUpdating = $false

    $stage = 'open DOCX work copy'
    $document = $word.Documents.Open($resolvedDocx, $false, $false, $false)

    $mathConverted = 0
    foreach ($action in @($actions.math_actions)) {
        $stage = "convert formula $([string]$action.formula_id)"
        $range = Find-UniqueMarkerRange -Document $document -Marker ([string]$action.marker)
        $start = $range.Start
        $expression = [string]$action.expression
        $range.Text = $expression
        $range.SetRange($start, $start + $expression.Length)
        $range.Font.Name = 'Cambria Math'
        $range.Font.NameAscii = 'Cambria Math'
        $range.Font.NameOther = 'Cambria Math'
        [void]$range.OMaths.Add($range)
        if ($range.OMaths.Count -ne 1) { throw "Word did not create one OMath object for $([string]$action.formula_id)" }
        $range.OMaths.Item(1).BuildUp()
        if ([string]$action.placement -eq 'display') { $range.ParagraphFormat.Alignment = 1 }
        $mathConverted++
    }

    $footnoteActions = @($actions.footnote_actions)
    if ($footnoteActions.Count -gt 0) {
        $scopes = @($footnoteActions | ForEach-Object { [string]$_.numbering_scope } | Sort-Object -Unique)
        if ($scopes.Count -ne 1) { throw "Footnote actions must use one numbering_scope; found $($scopes -join ', ')" }
        $numberingRule = switch ($scopes[0]) {
            'document' { 0 }
            'section' { 1 }
            'page' { 2 }
            default { throw "Unsupported footnote numbering_scope: $($scopes[0])" }
        }
        $document.Footnotes.NumberingRule = $numberingRule
        $document.Footnotes.StartingNumber = [int]$footnoteActions[0].expected_number
    }

    $footnotesInserted = 0
    foreach ($action in $footnoteActions) {
        $stage = "insert footnote $([string]$action.footnote_id)"
        $range = Find-UniqueMarkerRange -Document $document -Marker ([string]$action.marker)
        $start = $range.Start
        $range.Text = ''
        $range.SetRange($start, $start)
        [void]$document.Footnotes.Add($range, [Type]::Missing, [string]$action.text)
        $footnotesInserted++
    }

    $stage = 'check marker leakage'
    $documentText = [string]$document.Content.Text
    if ($documentText.Contains('[[MATH:') -or $documentText.Contains('[[FOOTNOTE:')) {
        throw 'Unresolved math or footnote action marker remains in the document.'
    }

    $stage = 'update fields and TOCs'
    Update-AllStoryFields -Document $document
    foreach ($toc in $document.TablesOfContents) { [void]$toc.Update() }
    $document.Repaginate()
    Update-AllStoryFields -Document $document
    foreach ($toc in $document.TablesOfContents) { [void]$toc.UpdatePageNumbers() }
    $document.Repaginate()

    $stage = 'save postprocessed DOCX'
    $document.Save()

    $tocEntries = @()
    foreach ($toc in $document.TablesOfContents) {
        foreach ($paragraph in $toc.Range.Paragraphs) {
            $text = ([string]$paragraph.Range.Text) -replace '[\r\a]+$', ''
            if ([string]::IsNullOrWhiteSpace($text)) { continue }
            $styleName = ''
            try { $styleName = [string]$paragraph.Range.Style.NameLocal } catch { $styleName = [string]$paragraph.Range.Style }
            $tocEntries += [PSCustomObject]@{
                text = $text
                style = $styleName
                outline_level = [int]$paragraph.OutlineLevel
                page = [int]$paragraph.Range.Information(3)
                vertical_position_pt = [double]$paragraph.Range.Information(6)
                space_before_pt = [double]$paragraph.SpaceBefore
                space_after_pt = [double]$paragraph.SpaceAfter
                line_spacing_pt = [double]$paragraph.LineSpacing
                left_indent_pt = [double]$paragraph.LeftIndent
                first_line_indent_pt = [double]$paragraph.FirstLineIndent
            }
        }
    }

    $stage = 'export PDF'
    $document.ExportAsFixedFormat($resolvedPdf, 17)

    $stats = [PSCustomObject]@{
        word_version = [string]$word.Version
        pages = [int]$document.ComputeStatistics(2)
        sections = [int]$document.Sections.Count
        tables = [int]$document.Tables.Count
        inline_shapes = [int]$document.InlineShapes.Count
        footnotes = [int]$document.Footnotes.Count
        omath_objects = [int]$document.OMaths.Count
        toc_objects = [int]$document.TablesOfContents.Count
        toc_entries = [int]$tocEntries.Count
        math_converted_this_run = [int]$mathConverted
        footnotes_inserted_this_run = [int]$footnotesInserted
    }
    $utf8 = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($StatsPath), ($stats | ConvertTo-Json -Depth 8), $utf8)
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($TocEntriesPath), (ConvertTo-Json -InputObject @($tocEntries) -Depth 8), $utf8)
}
catch {
    Write-Error "Word COM stage failed: $stage`n$($_.Exception.Message)`n$($_.ScriptStackTrace)"
    throw
}
finally {
    if ($null -ne $document) {
        try { $document.Close($false) } catch {}
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) } catch {}
        $document = $null
    }
    if ($null -ne $word) {
        try { $word.Quit() } catch {}
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) } catch {}
        $word = $null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
