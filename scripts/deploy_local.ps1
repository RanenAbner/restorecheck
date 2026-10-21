# Build and deploy the stack into LocalStack (never real AWS).
# `samlocal` is the SAM CLI with every AWS endpoint redirected to localhost:4566.
#
#   docker compose up -d
#   .\scripts\deploy_local.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$endpoint = "http://localhost:4566"
try {
    Invoke-RestMethod -Uri "$endpoint/_localstack/health" -TimeoutSec 3 | Out-Null
} catch {
    Write-Error "LocalStack is not reachable on $endpoint. Start it with: docker compose up -d"
    exit 1
}

# LocalStack's dummy credentials (not secrets), scoped to this script's process.
$env:AWS_ACCESS_KEY_ID = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
$env:AWS_DEFAULT_REGION = "us-east-1"

# The template needs a VPC and subnets; use LocalStack's default VPC.
$vpcId = aws --endpoint-url $endpoint ec2 describe-vpcs --filters Name=is-default,Values=true `
    --query "Vpcs[0].VpcId" --output text
$subnetIds = (aws --endpoint-url $endpoint ec2 describe-subnets --filters "Name=vpc-id,Values=$vpcId" `
    --query "Subnets[0:2].SubnetId" --output text) -split "\s+" -join ","

samlocal build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# --parameter-overrides replaces samconfig's list, so it repeats the dev values.
samlocal deploy --config-env dev --parameter-overrides `
    "Stage=dev SourceDbInstanceId=restorecheck-source ScheduleState=DISABLED VpcId=$vpcId SubnetIds=$subnetIds"
exit $LASTEXITCODE
