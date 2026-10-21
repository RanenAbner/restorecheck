# Delete everything RestoreCheck and its demo created in your AWS account, so
# nothing keeps using credits after the demo. This is irreversible.
#
#   .\scripts\teardown_aws.ps1            # asks for confirmation
#   .\scripts\teardown_aws.ps1 -Force     # no prompt

param(
    [switch]$Force,
    [string]$AwsProfile = "restorecheck",
    [string]$StackName = "restorecheck",
    [string]$DemoStackName = "restorecheck-demo-db",
    [string]$TempInstancePrefix = "restorecheck-tmp-"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$aws = @("--profile", $AwsProfile)
$region = aws configure get region --profile $AwsProfile
$python = if (Test-Path .venv\Scripts\python.exe) { ".venv\Scripts\python.exe" } else { "python" }

if (-not $Force) {
    Write-Host "This permanently deletes the stacks '$StackName' and '$DemoStackName', the demo"
    Write-Host "database, its manual snapshots, all verification reports and the run history."
    if ((Read-Host "Type DELETE to continue") -ne "DELETE") { Write-Host "Cancelled."; exit 1 }
}

# 1. Temporary instances from a run still in progress. They use the stack's subnet
#    group and security group, so they must be gone before the stack can be deleted.
$leftovers = aws rds describe-db-instances @aws --output text `
    --query "DBInstances[?starts_with(DBInstanceIdentifier, '$TempInstancePrefix')].DBInstanceIdentifier"
foreach ($id in ($leftovers -split "\s+" | Where-Object { $_ })) {
    Write-Host "Deleting leftover temporary instance $id (waiting until it's gone)"
    aws rds delete-db-instance --db-instance-identifier $id --skip-final-snapshot --delete-automated-backups @aws | Out-Null
    aws rds wait db-instance-deleted --db-instance-identifier $id @aws
}

# 2. The reports bucket must be empty before CloudFormation can delete it.
$bucket = aws cloudformation describe-stacks --stack-name $StackName @aws `
    --query "Stacks[0].Outputs[?OutputKey=='ReportsBucketName'].OutputValue" --output text 2>$null
if ($LASTEXITCODE -eq 0 -and $bucket -and $bucket -ne "None") {
    Write-Host "Emptying s3://$bucket"
    aws s3 rm "s3://$bucket" --recursive @aws | Out-Null
}

# 3. RestoreCheck stack (sam delete also removes its uploaded build artifacts).
Write-Host "Deleting stack $StackName (the checker's network interfaces can take ~20-40 min to release)"
sam delete --stack-name $StackName --profile $AwsProfile --region $region --no-prompts

# 4. Manual demo snapshots (CloudFormation does not own them), then the demo database.
& $python scripts/demo_db.py --profile $AwsProfile --stack-name $DemoStackName cleanup-snapshots
Write-Host "Deleting stack $DemoStackName (the database takes several minutes)"
aws cloudformation delete-stack --stack-name $DemoStackName @aws
aws cloudformation wait stack-delete-complete --stack-name $DemoStackName @aws

Write-Host "Teardown complete." -ForegroundColor Green
Write-Host "Left in place (free/negligible): the SAM artifacts bucket stack 'aws-sam-cli-managed-default'."
