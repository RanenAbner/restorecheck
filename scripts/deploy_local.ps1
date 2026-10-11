# Build and deploy the stack into LocalStack (never real AWS).
# `samlocal` is the SAM CLI with every AWS endpoint redirected to localhost:4566.
#
#   docker compose up -d
#   .\scripts\deploy_local.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

try {
    Invoke-RestMethod -Uri "http://localhost:4566/_localstack/health" -TimeoutSec 3 | Out-Null
} catch {
    Write-Error "LocalStack is not reachable on http://localhost:4566. Start it with: docker compose up -d"
    exit 1
}

samlocal build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

samlocal deploy --config-env dev
exit $LASTEXITCODE
