<#
.SYNOPSIS
    PR-5 parent-report inspector: logs in as the harness parent and prints what the
    parent portal actually receives.

.DESCRIPTION
    Read-only. Never writes to the harness DB and never regenerates an approved
    report; it replays the calls the parent console makes:

        GET /api/parent/reports?student_id=<id>                 -> approved list
        GET /api/parent/reports?student_id=<id>&report_id=<rid> -> one published body
        GET /api/parent/report?student_id=<id>&period=<p>       -> live generator (-Live)

    Note the asymmetry, it is easy to get wrong: the *stored* report lives on
    /api/parent/reports (plural, report_id=...) while /api/parent/report
    (singular) is the live on-the-fly generator driven by period=cycle|weekly|
    journey. Only the plural route carries "the report the teacher approved".

    Auth notes (both cost us time before):
      * the session cookie is set with "Secure"; over plain http a cookie jar
        throws it away, so the token is injected into the WebRequestSession by
        hand with Secure=$false.
      * PowerShell 5.1 silently DROPS a "Cookie" entry passed through -Headers,
        which surfaces as a bogus 401. Hence -WebSession everywhere.
      * GETs are not CSRF-protected; only POST /api/auth/* needs
        X-Requested-With: XMLHttpRequest (sent anyway for uniformity).

    Exit codes: 0 ok, 1 backend unreachable, 2 login failed,
                3 API error status, 4 no report found.

.PARAMETER BaseUrl
    Precedence: -BaseUrl > $env:PR5_BASE_URL > http://127.0.0.1:8002

.PARAMETER Email
    Precedence: -Email > $env:PR5_PARENT_EMAIL > parent@pr5.local

.PARAMETER Password
    Precedence: -Password > $env:PR5_PARENT_PASSWORD > Pr5Harness!2026

.PARAMETER StudentId
    Precedence: -StudentId > $env:PR5_STUDENT_ID > stud-pr5-demo0001

.PARAMETER ReportId
    Inspect one stored report. Default: every approved report in the list.

.PARAMETER Latest
    Inspect only the newest approved report (by published_at).

.PARAMETER Live
    Also call the live generator /api/parent/report for -Period and print what
    the parent "report tab" would render right now.

.PARAMETER Period
    cycle (default) | weekly | journey - only meaningful with -Live.

.PARAMETER Raw
    Print raw JSON instead of the human summary.

.PARAMETER Save
    Also write the raw parent payload to this path (one file per report when the
    list has several: <stem>_<report_id>.json).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/pr5_check_parent_report.ps1

.EXAMPLE
    # newest stored report, raw JSON, keep a copy
    powershell -ExecutionPolicy Bypass -File scripts/pr5_check_parent_report.ps1 `
        -Latest -Raw -Save .\temp\parent_report.json

.EXAMPLE
    # what the report tab renders live, plus the stored list
    powershell -ExecutionPolicy Bypass -File scripts/pr5_check_parent_report.ps1 `
        -Live -Period cycle

.EXAMPLE
    # harness backend on its default port 8001
    powershell -ExecutionPolicy Bypass -File scripts/pr5_check_parent_report.ps1 `
        -BaseUrl http://127.0.0.1:8001
#>
[CmdletBinding()]
param(
    [string]$BaseUrl   = $(if ($env:PR5_BASE_URL) { $env:PR5_BASE_URL } else { 'http://127.0.0.1:8002' }),
    [string]$Email     = $(if ($env:PR5_PARENT_EMAIL) { $env:PR5_PARENT_EMAIL } else { 'parent@pr5.local' }),
    [string]$Password  = $(if ($env:PR5_PARENT_PASSWORD) { $env:PR5_PARENT_PASSWORD } else { 'Pr5Harness!2026' }),
    [string]$StudentId = $(if ($env:PR5_STUDENT_ID) { $env:PR5_STUDENT_ID } else { 'stud-pr5-demo0001' }),
    [string]$ReportId,
    [switch]$Latest,
    [switch]$Live,
    [ValidateSet('cycle', 'weekly', 'journey')]
    [string]$Period = 'cycle',
    [switch]$Raw,
    [string]$Save
)

$ErrorActionPreference = 'Stop'
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$BaseUrl = $BaseUrl.TrimEnd('/')
$baseHost = ([uri]$BaseUrl).Host
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

function Fail([string]$msg, [int]$code) {
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    exit $code
}

function Invoke-Api {
    param([string]$Method, [string]$Path, [string]$Body)
    $p = @{
        Uri             = "$BaseUrl$Path"
        Method          = $Method
        WebSession      = $session
        UseBasicParsing = $true
        TimeoutSec      = 30
        Headers         = @{ 'X-Requested-With' = 'XMLHttpRequest'; 'Accept' = 'application/json' }
    }
    if ($Body) {
        $p['Body'] = [System.Text.Encoding]::UTF8.GetBytes($Body)
        $p['ContentType'] = 'application/json'
    }
    try {
        $resp = Invoke-WebRequest @p
        return [pscustomobject]@{ Status = [int]$resp.StatusCode; Body = $resp.Content; SetCookie = $resp.Headers['Set-Cookie']; Error = $null }
    }
    catch [System.Net.WebException] {
        $wr = $_.Exception.Response
        if (-not $wr) {
            return [pscustomobject]@{ Status = 0; Body = $null; SetCookie = $null; Error = $_.Exception.Message }
        }
        $text = ''
        try { $text = (New-Object System.IO.StreamReader($wr.GetResponseStream())).ReadToEnd() } catch { }
        return [pscustomobject]@{ Status = [int]$wr.StatusCode; Body = $text; SetCookie = $wr.Headers['Set-Cookie']; Error = $_.Exception.Message }
    }
}

# Slots that must never reach a parent (PR-5 Â§B4 / T-5).
$BannedKeys = @('kid_label', 'citations', 'cost_summary', 'cost', 'teacher_edits', 'review', 'internal_label', 'last_label_internal')

function Test-Leak([string]$json) {
    $hits = @()
    foreach ($k in $BannedKeys) {
        if ($json -match ('"' + [regex]::Escape($k) + '"\s*:')) { $hits += $k }
    }
    return $hits
}

function Get-Obj($o, [string]$name) {
    if ($null -eq $o) { return $null }
    $p = $o.PSObject.Properties[$name]
    if ($p) { return $p.Value }
    return $null
}

function Show-Envelope($rep, $narrative) {
    $variant = Get-Obj $rep 'variant'
    $period  = Get-Obj $rep 'period'
    $summary = Get-Obj $rep 'summary'

    Write-Host ("variant     : {0}" -f $(if ($variant) { $variant } else { '-' }))
    if ($period) {
        Write-Host ("period      : type={0} {1} -> {2} ({3}d)" -f (Get-Obj $period 'type'), (Get-Obj $period 'from'), (Get-Obj $period 'to'), (Get-Obj $period 'days'))
    }
    if ($summary) {
        Write-Host ("sessions    : {0}   duration: {1}s   topics: {2}" -f `
            (Get-Obj $summary 'session_count'), (Get-Obj $summary 'total_duration_seconds'), (Get-Obj $summary 'topics_touched'))
        $dist = Get-Obj $summary 'mode_distribution'
        if ($dist) {
            $pairs = @()
            foreach ($n in $dist.PSObject.Properties.Name) { $pairs += "$n=$(Get-Obj $dist $n)" }
            Write-Host ("modes       : {0}" -f ($pairs -join '  '))
        }
    }
    else {
        Write-Host "sessions    : - (no summary block)"
    }

    $topics = Get-Obj $rep 'topics'
    if ($topics -and @($topics).Count -gt 0) {
        Write-Host "topics      :"
        foreach ($t in @($topics)) {
            Write-Host ("  - {0}  mastery={1}%  delta={2}  attempts={3}  label='{4}'  streak={5}" -f `
                (Get-Obj $t 'topic_id'), (Get-Obj $t 'mastery_pct'), (Get-Obj $t 'mastery_delta'), `
                (Get-Obj $t 'attempt_count'), (Get-Obj $t 'last_label_parent'), (Get-Obj $t 'streak'))
        }
    }
    else {
        Write-Host "topics      : none"
    }

    $timeline = Get-Obj $rep 'activity_timeline'
    if ($timeline) { Write-Host ("timeline    : {0} active day(s)" -f @($timeline).Count) }
    $alerts = Get-Obj $rep 'safety_alerts'
    if ($alerts) { Write-Host ("safety      : {0} alert(s)" -f @($alerts).Count) }
    foreach ($k in 'baseline', 'roadmap', 'portfolio_highlights', 'first_steps') {
        $v = Get-Obj $rep $k
        if ($null -ne $v) {
            $desc = if ($v -is [string]) { $v } else { ($v | ConvertTo-Json -Compress -Depth 4) }
            if ($desc.Length -gt 160) { $desc = $desc.Substring(0, 160) + '...' }
            Write-Host ("{0,-11} : {1}" -f $k, $desc)
        }
    }

    Write-Host "--- narrative the parent reads ---" -ForegroundColor DarkGray
    if ($narrative) { Write-Host $narrative } else { Write-Host "[WARN] empty - parent sees the empty state" -ForegroundColor Yellow }
}

# ---------------------------------------------------------------- 0. reachability
Write-Host "Backend : $BaseUrl" -ForegroundColor DarkGray
$probe = $null
try { $probe = Invoke-Api -Method 'GET' -Path '/api/auth/me' } catch { }
if ($null -eq $probe -or $probe.Status -eq 0) {
    Fail "backend not reachable on $BaseUrl - start it first: scripts\pr5_start_local.ps1 -Backend -Port 8002" 1
}

# ---------------------------------------------------------------- 1. login
$login = Invoke-Api -Method 'POST' -Path '/api/auth/login' -Body (@{ email = $Email; password = $Password } | ConvertTo-Json -Compress)
if ($login.Status -lt 200 -or $login.Status -ge 300) {
    Fail "login failed for $Email ($($login.Status)): $($login.Body)" 2
}
if (-not $login.SetCookie) { Fail "login returned $($login.Status) but no Set-Cookie" 2 }

$pair = (($login.SetCookie | Select-Object -First 1) -split ';')[0].Trim()
$cname, $cvalue = $pair -split '=', 2
$cookie = New-Object System.Net.Cookie($cname, $cvalue, '/', $baseHost)
$cookie.Secure = $false   # browser-jar rule only; we inject the pair ourselves
$session.Cookies.Add($cookie)

$me = Invoke-Api -Method 'GET' -Path '/api/auth/me'
if ($me.Status -ne 200) {
    Fail "session rejected ($($me.Status)) - is the backend running against .pr5_harness\pr5_harness.db?" 2
}
$meJson = $me.Body | ConvertFrom-Json
Write-Host "Login   : $($meJson.user.email)  role=$($meJson.user.role)  student=$StudentId" -ForegroundColor DarkGray

$sid = [uri]::EscapeDataString($StudentId)

# ---------------------------------------------------------------- 2. stored list
$listPath = "/api/parent/reports?student_id=$sid"
$list = Invoke-Api -Method 'GET' -Path $listPath
if ($list.Status -lt 200 -or $list.Status -ge 300) { Fail "GET $listPath -> $($list.Status): $($list.Body)" 3 }

$listJson = $list.Body | ConvertFrom-Json
$items = @(Get-Obj $listJson 'reports')
Write-Host ""
Write-Host "GET /api/parent/reports -> $($items.Count) approved report(s)" -ForegroundColor Cyan
if ($items.Count -eq 0) {
    Write-Host "Nothing approved yet: run scripts\pr5_seed_local.py --reissue-reports." -ForegroundColor Yellow
    exit 4
}

$items | ForEach-Object {
    [pscustomobject]@{
        report_id = (Get-Obj $_ 'report_id')
        status    = (Get-Obj $_ 'status')
        lang      = (Get-Obj $_ 'lang_code')
        age_band  = (Get-Obj $_ 'age_band')
        weeks     = "w$(Get-Obj $_ 'week_from')-w$(Get-Obj $_ 'week_to')"
        published = (Get-Obj $_ 'published_at')
    }
} | Format-Table -AutoSize | Out-String -Width 220 | Write-Host

# ---------------------------------------------------------------- 3. stored body
$targets = $items
if ($ReportId) {
    $targets = @($items | Where-Object { "$(Get-Obj $_ 'report_id')" -eq "$ReportId" })
    if ($targets.Count -eq 0) { Fail "report $ReportId is not approved for $StudentId" 4 }
}
elseif ($Latest) {
    $targets = @($items | Sort-Object { "$(Get-Obj $_ 'published_at')" } -Descending | Select-Object -First 1)
}

foreach ($t in $targets) {
    $rid = "$(Get-Obj $t 'report_id')"
    $detailPath = "/api/parent/reports?student_id=$sid&report_id=$([uri]::EscapeDataString($rid))"
    $detail = Invoke-Api -Method 'GET' -Path $detailPath
    if ($detail.Status -lt 200 -or $detail.Status -ge 300) {
        Write-Host "[FAIL] GET $detailPath -> $($detail.Status): $($detail.Body)" -ForegroundColor Red
        continue
    }

    if ($Raw) {
        Write-Host ""
        Write-Host "=== raw stored body: $rid ($(Get-Obj $t 'lang_code')) ===" -ForegroundColor Cyan
        Write-Host $detail.Body
    }
    else {
        $row = Get-Obj ($detail.Body | ConvertFrom-Json) 'report'
        $payload = Get-Obj $row 'payload'
        $rep = Get-Obj $payload 'report'
        if (-not $rep) { $rep = $payload }          # older rows stored the bare envelope

        Write-Host ""
        Write-Host "=== stored report $rid  lang=$(Get-Obj $t 'lang_code')  band=$(Get-Obj $t 'age_band')  weeks=$(Get-Obj $t 'week_from')-$(Get-Obj $t 'week_to') ===" -ForegroundColor Cyan
        Show-Envelope $rep (Get-Obj $payload 'content')

        $hits = Test-Leak $detail.Body
        if ($hits.Count -gt 0) {
            Write-Host ("[WARN] internal slots present in the parent payload: {0}" -f ($hits -join ', ')) -ForegroundColor Yellow
        }
        else {
            Write-Host "masking     : clean (no kid_label / citations / cost_* / teacher_edits)" -ForegroundColor DarkGray
        }
    }

    if ($Save) {
        $outPath = if ([System.IO.Path]::IsPathRooted($Save)) { $Save } else { Join-Path $PWD.Path $Save }
        if ($targets.Count -gt 1) {
            $stem = [System.IO.Path]::GetFileNameWithoutExtension($Save)
            $ext = [System.IO.Path]::GetExtension($Save); if (-not $ext) { $ext = '.json' }
            $outPath = Join-Path (Split-Path -Parent $Save) "$stem`_$rid$ext"
        }
        $dir = Split-Path -Parent $outPath
        if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $full = [System.IO.Path]::GetFullPath($outPath)
        [System.IO.File]::WriteAllText($full, $detail.Body, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "saved       : $full" -ForegroundColor DarkGray
    }
}

# ---------------------------------------------------------------- 4. live generator
if ($Live) {
    $livePath = "/api/parent/report?student_id=$sid&period=$Period"
    $liveResp = Invoke-Api -Method 'GET' -Path $livePath
    Write-Host ""
    Write-Host "GET $livePath -> $($liveResp.Status)" -ForegroundColor Cyan
    if ($liveResp.Status -lt 200 -or $liveResp.Status -ge 300) {
        Write-Host "[FAIL] live generator: $($liveResp.Body)" -ForegroundColor Red
    }
    elseif ($Raw) {
        Write-Host $liveResp.Body
    }
    else {
        $liveEnv = $liveResp.Body | ConvertFrom-Json
        Show-Envelope (Get-Obj $liveEnv 'report') (Get-Obj $liveEnv 'content')
        $hits = Test-Leak $liveResp.Body
        if ($hits.Count -gt 0) {
            Write-Host ("[INFO] live generator envelope still carries: {0}" -f ($hits -join ', ')) -ForegroundColor Yellow
            Write-Host "       (this route returns the agent envelope as-is; the stored" -ForegroundColor DarkGray
            Write-Host "        /api/parent/reports body is the scrubbed parent copy)" -ForegroundColor DarkGray
        }
    }
}

Write-Host ""
Write-Host "OK" -ForegroundColor Green
exit 0




