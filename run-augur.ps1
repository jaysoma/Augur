# run-augur.ps1 â€” start the mock shop, crawl it with the model, then stop the mock.
#
#   .\run-augur.ps1                         # spins up mockshop.py and crawls it
#   .\run-augur.ps1 http://localhost:3000   # crawl a site you already have running (e.g. Spree)
#   $env:TESTER_STUB=1 ; .\run-augur.ps1    # offline: deterministic oracle, no model
#
param([string]$Target)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot          # always run from the Augur folder = no stale paths

if ($Target) {
    # crawl an already-running site; don't touch the mock
    python crawl.py $Target
}
else {
    Write-Host "Starting mock shop on :3000..." -ForegroundColor Cyan
    $mock = Start-Process python -ArgumentList "mockshop.py" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 1
    try {
        python crawl.py http://localhost:3000
    }
    finally {
        Stop-Process -Id $mock.Id -Force -ErrorAction SilentlyContinue
        Write-Host "`nMock shop stopped." -ForegroundColor Cyan
    }
}
