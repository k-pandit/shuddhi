# Opens a reviewed .docx in Microsoft Word, lists its tracked changes and exports a PDF showing the markup.
param([string]$Doc = (Join-Path $PSScriptRoot 'sample_notification_reviewed.docx'),
      [string]$Pdf = (Join-Path $PSScriptRoot 'sample_notification_reviewed_markup.pdf'))
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  # ReadOnly, no conversion prompt, no repair: if Word cannot read the file this call fails.
  $d = $word.Documents.Open($Doc, $false, $true, $false)
  $n = $d.Revisions.Count
  "Word opened the file. Tracked changes found: $n"
  $ins = 0; $del = 0
  for ($i = 1; $i -le $n; $i++) {
    $rv = $d.Revisions.Item($i)
    $kind = if ($rv.Type -eq 1) { 'insert'; $ins++ } elseif ($rv.Type -eq 2) { 'delete'; $del++ } else { "type $($rv.Type)" }
    "{0,3}  {1,-6}  '{2}'  by {3}" -f $i, $kind, $rv.Range.Text, $rv.Author
  }
  "Insertions: $ins   Deletions: $del"
  "Italic run preserved around 'Committee': " + $(
    $r = $d.Content; if ($r.Find.Execute('Monitoring')) { $r.Font.Italic -eq -1 } else { 'phrase not found' })
  $d.ExportAsFixedFormat($Pdf, 17, $false, 0, 0, 1, 1, 7)   # 7 = document with markup
  "Exported $Pdf"
  $d.Close(0)
} finally {
  $word.Quit()
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
}
