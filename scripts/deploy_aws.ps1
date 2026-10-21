# Deploy RestoreCheck and its demo source database to your AWS account.
#
#   .\scripts\deploy_aws.ps1 -AlertEmail you@example.com
#   .\scripts\deploy_aws.ps1 -Schedule ENABLED          # turn the nightly run on
#
# Safe to re-run: unchanged stacks are left alone, and -AlertEmail / -Schedule
# keep their current values unless you pass new ones. Creating the demo database
# takes ~10 minutes the first time. Remove everything with teardown_aws.ps1.

param(
    [string]$AlertEmail = "",
    [ValidateSet("", "ENABLED", "DISABLED")] [string]$Schedule = "",
    [string]$AwsProfile = "restorecheck",
    [string]$StackName = "restorecheck",
    [string]$DemoStackName = "restorecheck-demo-db"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Native {
    # Runs a CLI command and stops the script if it fails (PowerShell 5.1 doesn't).
    & $args[0] $args[1..($args.Length - 1)]
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $($args -join ' ')" }
}

$aws = @("--profile", $AwsProfile)
$region = aws configure get region --profile $AwsProfile
$account = aws sts get-caller-identity --query Account --output text @aws
Write-Host "Deploying to account $account, region $region" -ForegroundColor Cyan

# 1. Network: the account's default VPC and two of its subnets (different zones).
$vpcId = aws ec2 describe-vpcs --filters Name=is-default,Values=true --query "Vpcs[0].VpcId" --output text @aws
$subnetIds = (aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpcId" Name=default-for-az,Values=true `
    --query "sort_by(Subnets, &AvailabilityZone)[0:2].SubnetId" --output text @aws) -split "\s+" -join ","
Write-Host "Default VPC $vpcId, subnets $subnetIds"

# 2. Demo source database, reachable only from this machine's public IP (for seeding).
$myIp = (Invoke-RestMethod -Uri "https://checkip.amazonaws.com").Trim()
Write-Host "Demo database will accept connections from $myIp/32 only"
Invoke-Native aws cloudformation deploy @aws `
    --template-file demo/source-db.yaml --stack-name $DemoStackName `
    --parameter-overrides "VpcId=$vpcId" "AdminCidr=$myIp/32" `
    --tags project=restorecheck --no-fail-on-empty-changeset
$sourceDbId = aws cloudformation describe-stacks --stack-name $DemoStackName @aws `
    --query "Stacks[0].Outputs[?OutputKey=='DbInstanceIdentifier'].OutputValue" --output text

# 3. RestoreCheck itself. Keep the deployed email/schedule unless new ones were given
#    (leaving AlertEmail out would otherwise delete the email subscription).
$current = @{}
$params = aws cloudformation describe-stacks --stack-name $StackName @aws --query "Stacks[0].Parameters" --output json 2>$null
if ($LASTEXITCODE -eq 0 -and $params) {
    ($params | ConvertFrom-Json) | ForEach-Object { $current[$_.ParameterKey] = $_.ParameterValue }
}
if (-not $AlertEmail -and $current["AlertEmail"]) { $AlertEmail = $current["AlertEmail"] }
if (-not $Schedule) { $Schedule = if ($current["ScheduleState"]) { $current["ScheduleState"] } else { "DISABLED" } }
Write-Host "Alert email: $(if ($AlertEmail) { $AlertEmail } else { '(none)' }); schedule: $Schedule"

Invoke-Native sam build
$overrides = @(
    "SourceDbInstanceId=$sourceDbId", "VpcId=$vpcId", "SubnetIds=$subnetIds", "ScheduleState=$Schedule"
)
if ($AlertEmail) { $overrides += "AlertEmail=$AlertEmail" }
Invoke-Native sam deploy --stack-name $StackName --profile $AwsProfile --region $region `
    --resolve-s3 --capabilities CAPABILITY_IAM --no-confirm-changeset --no-fail-on-empty-changeset `
    --tags project=restorecheck --parameter-overrides ($overrides -join " ")

Write-Host ""
Write-Host "Deployed." -ForegroundColor Green
if ($AlertEmail) { Write-Host "Confirm the SNS subscription email sent to $AlertEmail, or alerts won't arrive." }
Write-Host "Next:"
Write-Host "  python scripts/demo_db.py seed"
Write-Host "  python scripts/demo_db.py snapshot --label healthy"
Write-Host "  python scripts/run_pipeline.py --aws --profile $AwsProfile"
