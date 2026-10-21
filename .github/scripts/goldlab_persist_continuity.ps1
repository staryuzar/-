$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Persist completed GoldLab test runs into the continuity report without touching main.
$repo = [string]$env:GITHUB_REPOSITORY
$branch = [string]$env:GITHUB_REF_NAME
$token = [string]$env:GITHUB_TOKEN
$ownRunId = [string]$env:GITHUB_RUN_ID
$eventName = [string]$env:GITHUB_EVENT_NAME
$apiBase = "https://api.github.com/repos/$repo"
$reportPath = "GOLDLAB_CONTINUITY_REPORT_AR.md"

if ($repo -ne "staryuzar/-") { throw "Refusing to write journal outside staryuzar/-." }
if ($branch -ne "gold-xauusd-expert-lab") { throw "Refusing to write journal outside gold-xauusd-expert-lab (main is protected)." }
if ([string]::IsNullOrWhiteSpace($token)) { throw "GITHUB_TOKEN is unavailable; cannot persist report." }

$headers = @{
  Authorization = "Bearer $token"
  Accept = "application/vnd.github+json"
  "X-GitHub-Api-Version" = "2022-11-28"
}
$reportUrl = "$apiBase/contents/$reportPath?ref=$([uri]::EscapeDataString($branch))"

# Push-triggered runs collect all related workflows that start near this code change.
# A manual dispatch acts as a recovery sweep of recently completed GoldLab test runs.
$startedAt = [DateTime]::UtcNow
if ($eventName -eq "workflow_dispatch") {
  $cutoff = $startedAt.AddMinutes(-180)
  $waitMinutes = 3
} else {
  $cutoff = $startedAt.AddMinutes(-3)
  $waitMinutes = 32
}
$deadline = $startedAt.AddMinutes($waitMinutes)
$runApiUrl = "$apiBase/actions/runs?branch=$([uri]::EscapeDataString($branch))&per_page=100"
$knownSeen = 0
$updates = 0
$emptyPolls = 0
$maxPolls = [int][Math]::Ceiling($waitMinutes * 60 / 20)

function Get-ReportState {
  $doc = Invoke-RestMethod -Method Get -Uri $reportUrl -Headers $headers -TimeoutSec 30
  $encoded = ([string]$doc.content) -replace "\s", ""
  $bytes = [Convert]::FromBase64String($encoded)
  return @{
    Sha = [string]$doc.sha
    Content = [System.Text.Encoding]::UTF8.GetString($bytes)
  }
}

function Add-RunToReport([object]$run) {
  $runId = [string]$run.id
  $runLink = [string]$run.html_url
  $runName = [string]$run.name
  $runName = $runName.Replace([char]13, " ").Replace([char]10, " ").Trim()
  $conclusion = [string]$run.conclusion
  if ([string]::IsNullOrWhiteSpace($conclusion)) { $conclusion = [string]$run.status }
  $event = [string]$run.event
  $sha = [string]$run.head_sha
  $created = [string]$run.created_at
  $marker = "<!-- goldlab-auto-run-id:$runId -->"

  for ($attempt = 1; $attempt -le 10; $attempt++) {
    $state = Get-ReportState
    # Links already listed by the human-maintained report also count as recorded.
    if ($state.Content.Contains($marker) -or $state.Content -match [regex]::Escape("/actions/runs/$runId")) {
      return $false
    }
    $shortSha = $sha.Substring(0, [Math]::Min(12, $sha.Length))
    $section = @(
      "",
      "---",
      "",
      $marker,
      "### سجل آلي — GitHub Actions run $runId",
      "- **اسم التشغيل:** $runName",
      "- **نتيجة سير العمل:** $conclusion (الحدث: $event، الحالة: $($run.status))",
      "- **الفرع/الالتزام:** $branch / [$shortSha](https://github.com/$repo/commit/$sha)",
      "- **وقت الإنشاء (UTC):** $created",
      "- **السجلات:** [فتح التشغيل]($runLink) · [ملفات الأدلة/التقرير](https://github.com/$repo/actions/runs/$runId/artifacts)",
      "- **قاعدة القراءة:** نتيجة سير العمل لا تكفي وحدها للحكم على ربحية الاستراتيجية؛ راجع تقرير HTML/CSV وسجلات MT5 في ملفات الأدلة. قد يكون التشغيل ناجحًا لأنه حفظ حالة NOT RUN المقصودة.",
      ""
    ) -join [Environment]::NewLine
    $newContent = $state.Content.TrimEnd() + [Environment]::NewLine + $section + [Environment]::NewLine
    $body = @{
      message = "docs: auto-record GoldLab Actions run $runId"
      content = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($newContent))
      sha = $state.Sha
      branch = $branch
    } | ConvertTo-Json -Depth 5

    try {
      $null = Invoke-RestMethod -Method Put -Uri "$apiBase/contents/$reportPath" -Headers $headers -ContentType "application/json" -Body $body -TimeoutSec 45
      Write-Output "Persisted GoldLab run $runId ($conclusion) into $reportPath."
      return $true
    } catch {
      if ($attempt -eq 10) { throw "Could not persist run $runId after 10 conflict-safe retries: $($_.Exception.Message)" }
      # A parallel tester may have updated the same Markdown file. Re-read its
      # current blob SHA and retry; duplicate markers make this operation idempotent.
      Start-Sleep -Seconds ([Math]::Min(5,$attempt))
    }
  }
  return $false
}

for ($poll = 1; $poll -le $maxPolls; $poll++) {
  $response = Invoke-RestMethod -Method Get -Uri $runApiUrl -Headers $headers -TimeoutSec 30
  $runs = @($response.workflow_runs | Where-Object {
    [string]$_.id -ne $ownRunId -and
    [string]$_.name -like "GoldLab MT5*" -and
    [string]$_.head_branch -eq $branch -and
    ([DateTime]::Parse([string]$_.created_at).ToUniversalTime() -ge $cutoff)
  } | Sort-Object { [DateTime]::Parse([string]$_.created_at).ToUniversalTime() })

  if ($runs.Count -eq 0) {
    $emptyPolls++
    if ($eventName -eq "workflow_dispatch" -or $emptyPolls -ge 3) { break }
  } else {
    $emptyPolls = 0
    $knownSeen = $runs.Count
    foreach ($run in $runs) {
      if ([string]$run.status -eq "completed") {
        if (Add-RunToReport -run $run) { $updates++ }
      }
    }
    $pending = @($runs | Where-Object { [string]$_.status -ne "completed" })
    if ($pending.Count -eq 0) { break }
    Write-Output "Waiting for $($pending.Count) related GoldLab run(s) to finish; poll $poll/$maxPolls."
  }

  if ([DateTime]::UtcNow -ge $deadline) { break }
  Start-Sleep -Seconds 20
}

Write-Output "GoldLab continuity journal finished. Relevant runs seen: $knownSeen; new report entries: $updates."
if ($updates -eq 0 -and $knownSeen -eq 0 -and $eventName -ne "workflow_dispatch") {
  Write-Warning "No related GoldLab MT5 run appeared in the collection window. No report entry was fabricated."
}
