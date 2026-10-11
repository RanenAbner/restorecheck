# RestoreCheck

**Automated Backup Verification & Disaster-Recovery Testing on AWS**

## The problem
AWS storage services guarantee extremely high **durability** (Amazon S3 and AWS Backup advertise up to 99.999999999% — "11 nines"). But durability only means your stored bytes won't be lost or physically corrupted. It says nothing about whether a backup can actually be **restored** into a working system.

In practice, restores fail for reasons durability never covers:
- The backup is **application-inconsistent** (taken mid-transaction).
- The backup job silently **excluded** a database, table, or volume (configuration drift).
- The backup is encrypted with a **KMS key** that was rotated or deleted — durably stored, but undecryptable.
- The **restore procedure itself** is broken or too slow to meet the recovery time objective (RTO).
- The source data was already **corrupted or ransomware-encrypted** before the backup ran.

> A backup isn't real until you've tested the restore.

## What RestoreCheck does
On a schedule, RestoreCheck automatically:
1. Restores the latest backup into a **temporary, isolated environment**.
2. Runs **integrity checks** to confirm the data is complete and usable.
3. **Records** the pass/fail result and a detailed report.
4. **Alerts** the team immediately if a backup fails verification.
5. **Tears down** the temporary resources to minimize cost.

This proves — continuously and automatically — that backups are genuinely recoverable, *before* a real disaster.

## Architecture (MVP: RDS backups)

```
            +--------------+
            | EventBridge  |  (scheduled cron trigger)
            +------+-------+
                   | invokes
                   v
            +--------------+        restore latest snapshot
            |    Lambda    | ------------->  +-------------------+
            | (Python/Boto3)|                |  Temporary RDS    |
            |  orchestrator | <---- checks --|  (spun up & torn  |
            +--+---+---+----+                |  down each run)   |
               |   |   |                     +-------------------+
      result   |   |   |  alert on failure
       +-------v+ +v--+ v------+
       |DynamoDB| | S3 | | SNS  |--> email alert
       |(history)| |(report)| +------+
       +--------+ +----+
               |
               v
        +------------+
        | CloudWatch |  (dashboards, metrics, RTO trends)
        +------------+

   Security: IAM least-privilege role + custom JSON policy
   Deployment: AWS SAM / CloudFormation (Infrastructure as Code)
```

## AWS services used
| Service | Role in the system |
|---|---|
| EventBridge | Schedules the periodic verification runs |
| Lambda | Orchestrates restore -> verify -> record -> teardown |
| RDS | Temporary database restored from a snapshot for testing |
| S3 | Stores detailed verification reports |
| DynamoDB | Stores pass/fail history for fast lookups |
| SNS | Sends failure alerts (email/SMS) |
| CloudWatch | Dashboards and metrics for backup health & RTO |
| IAM | Least-privilege role + custom JSON policy |
| CloudFormation (via SAM) | Reproducible, automated deployment |

## Repository layout
| Path | Purpose |
|---|---|
| `template.yaml` | SAM/CloudFormation template — all infrastructure |
| `samconfig.toml` | Saved `sam` options; the `dev` environment targets LocalStack |
| `src/handler.py` | Lambda entry point |
| `src/config.py`, `src/aws_clients.py` | Settings + boto3 client factory (dev mode lives here) |
| `src/checks/` | Integrity checks, one module each |
| `tests/` | pytest unit tests |
| `scripts/` | `deploy_local.ps1` (deploy to LocalStack), `local_run.py` (run the handler locally) |
| `events/` | Sample invocation payloads |
| `docker-compose.yml` | Starts LocalStack |

## Running locally (LocalStack)
Development and testing run against **LocalStack** (local AWS emulator), so no AWS charges are incurred until the final deployment.

Prerequisites: Docker Desktop, the AWS SAM CLI, a free LocalStack account (auth token), Python 3.

```powershell
# one-time setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt aws-sam-cli-local
Copy-Item .env.example .env        # then put your LOCALSTACK_AUTH_TOKEN in .env

# unit tests + template lint (no Docker needed)
pytest
cfn-lint template.yaml

# deploy into LocalStack and run
docker compose up -d
.\scripts\deploy_local.ps1
python scripts/local_run.py --dev
```

**Dev mode.** The `Stage=dev` template parameter sets `RESTORECHECK_DEV=true` on the Lambda. In dev mode every boto3 client is created with an explicit LocalStack endpoint (`http://localhost:4566`, or the `AWS_ENDPOINT_URL` LocalStack injects) and dummy credentials, and the code refuses to start if that endpoint is an `amazonaws.com` host.

## Open design decisions
- **Lambda's 15-minute limit.** A real RDS restore often takes longer than one Lambda invocation may run. Before the real-AWS deploy the pipeline needs to be split (start restore → poll → check → teardown), e.g. with Step Functions.
- **Network path to the temporary database.** To run SQL checks the Lambda must reach the restored instance, which means running it inside the VPC (plus VPC endpoints or NAT for the AWS APIs).
- **Encrypted snapshots.** Snapshots encrypted with a customer-managed KMS key need `kms:CreateGrant`/`kms:DescribeKey` on that key added to the policy.

## Deploying to AWS
```bash
sam build
sam deploy --guided
```

## SDGs addressed
- **SDG 9 (Industry, Innovation and Infrastructure)** — builds resilient, reliable digital infrastructure.
- **SDG 11 (Sustainable Cities and Communities)** — strengthens disaster recovery for essential services.

## Status
MVP in development. Future work: EC2/EBS disk-backup verification, multi-region restore testing, web dashboard.
