# start-tunnel.ps1  --  expose the Augur UI (serve.py :7000) over your reserved ngrok domain.
# Works around: missing ngrok, the "unknown version '3'" config error, and the --url vs --domain
# flag difference, by using a clean temp config and auto-detecting the correct flag.
#
#   1) paste your authtoken below   2) run:  powershell -ExecutionPolicy Bypass -File .\start-tunnel.ps1

param([string]$AuthToken = "3EsegApDloAFZAUptuAfZ2jOQoP_3xmLW5GyBTm1ApsnCxeFd")   # pass it on the command line:  -AuthToken <your-token>

# ---- settings -------------------------------------------------------------
$Port   = 7000
$Domain = "exposure-dragonish-tackling.ngrok-free.dev"
# ...or, if you'd rather not type it each run, hardcode your token on the next line:
if ([string]::IsNullOrWhiteSpace($AuthToken)) { $AuthToken = "" }   # <-- optional: paste token here
# ---------------------------------------------------------------------------

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($AuthToken)) {
  Write-Error "Paste your ngrok authtoken into `$AuthToken at the top of this script (dashboard > Your Authtoken)."
  exit 1
}

# 1. Ensure ngrok is installed and on PATH
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
  Write-Host "ngrok not found - installing via winget..." -ForegroundColor Yellow
  winget install --id ngrok.ngrok -e --silent --accept-source-agreements --accept-package-agreements
  # refresh PATH for this session
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
}
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
  Write-Error "ngrok still not on PATH. Open a NEW terminal and re-run, or install from https://ngrok.com/download"
  exit 1
}
Write-Host "Using ngrok: $((Get-Command ngrok).Source)"
ngrok version

# 2. Write a minimal, universally-compatible config (v2 is read by every 3.x agent).
#    This bypasses the corrupted version:3 ngrok.yml entirely.
$cfg = Join-Path $env:TEMP "augur-ngrok.yml"
Set-Content -Path $cfg -Encoding ASCII -Value @"
version: "2"
authtoken: $AuthToken
"@
Write-Host "Wrote temp config: $cfg"

# 3. Detect whether this build uses --url (newer) or --domain (older)
$help = (& ngrok http --help 2>&1 | Out-String)
$flag = if ($help -match '--url') { '--url' } else { '--domain' }
Write-Host "Domain flag for this build: $flag"

# 4. Make sure serve.py is actually listening; start it if not
$open = Test-NetConnection -ComputerName localhost -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $open) {
  Write-Host "Nothing on localhost:$Port - starting serve.py..." -ForegroundColor Yellow
  Start-Process python -ArgumentList "serve.py" -WorkingDirectory $here
  Start-Sleep -Seconds 2
  Write-Host "(If the crawl needs the generated store, also run .\view-augur.ps1 to start genserver on :3000.)"
}

# 5. Start the tunnel (foreground - leave this window open)
Write-Host "`nStarting tunnel  ->  https://$Domain   (Ctrl+C to stop)`n" -ForegroundColor Green
& ngrok http $Port "$flag=$Domain" --config $cfg
