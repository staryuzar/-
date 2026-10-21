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
  $shortSha = $sha.Substring(0, [Math]::Min(12, $sha.Length))
  $fullPath = Join-Path $PWD $reportPath
  $utf8NoBom = [System.Text.UTF8Encoding]::new($false)

  for ($attempt = 1; $attempt -le 10; $attempt++) {
    # Read from the newest remote branch head on every attempt. This avoids
    # depending on a Contents API read that may be unavailable to a fine-grained token.
    & git fetch --no-tags origin "+refs/heads/$branch:refs/remotes/origin/$branch"
    if ($LASTEXITCODE -ne 0) { throw "Could not fetch the latest GoldLab branch before recording run $runId." }
    & git checkout --force -B $branch "refs/remotes/origin/$branch"
    if ($LASTEXITCODE -ne 0) { throw "Could not refresh the local report checkout for run $runId." }

    if (!(Test-Path -LiteralPath $fullPath)) { throw "Continuity report missing from branch: $reportPath" }
    $currentContent = [System.IO.File]::ReadAllText($fullPath, [System.Text.Encoding]::UTF8)
    # Links already listed by the human-maintained report also count as recorded.
    if ($currentContent.Contains($marker) -or $currentContent -match [regex]::Escape("/actions/runs/$runId")) {
      return $false
    }

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
    $newContent = $currentContent.TrimEnd() + [Environment]::NewLine + $section + [Environment]::NewLine
    [System.IO.File]::WriteAllText($fullPath, $newContent, $utf8NoBom)

    & git config user.name "github-actions[bot]"
    if ($LASTEXITCODE -ne 0) { throw "Could not configure Git author." }
    & git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
    if ($LASTEXITCODE -ne 0) { throw "Could not configure Git email." }
    & git add -- $reportPath
    if ($LASTEXITCODE -ne 0) { throw "Could not stage continuity report." }
    & git commit -m "docs: auto-record GoldLab Actions run $runId" -- $reportPath
    if ($LASTEXITCODE -ne 0) {
      # A concurrent run may already have added this record. Refresh and check again.
      Start-Sleep -Seconds ([Math]::Min(5,$attempt))
      continue
    }
    & git push origin "HEAD:refs/heads/$branch"
    if ($LASTEXITCODE -eq 0) { return $true }
    # Concurrent human/test commits can advance the branch during the push.
    # The next iteration fetches the new head and reapplies this run once.
    Start-Sleep -Seconds ([Math]::Min(5,$attempt))
  }
  throw "Could not persist run $runId after 10 conflict-safe git retries."
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
        if (Add-RunToReport -run $run) { $updates++; Write-Output "Persisted GoldLab run $($run.id) ($($run.conclusion)) into $reportPath." }
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
