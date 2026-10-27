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
  EventBridge (cron) --starts--> Step Functions workflow
                                   |
   +-------------------------------+--------------------------------------+
   | 1 PrepareRestore   Lambda: sweep leftovers, find newest snapshot,    |
   |                    start restore into a temporary instance           |
   | 2 Wait 60s  <-+                                                      |
   | 3 CheckStatus |    Lambda: still restoring? -> back to 2             |
   |               +--  (fails on a broken restore or MaxRestoreMinutes)  |
   | 4 RunChecks        Lambda INSIDE the VPC: log in with an IAM token,  |
   |                    run SQL integrity checks                          |
   | 5 Teardown         Lambda: delete the temporary instance             |
   |                    (every failure in 1-4 jumps straight here)        |
   | 6 RecordResult     Lambda: report -> S3, history -> DynamoDB,        |
   |                    metrics -> CloudWatch, alert -> SNS (email)       |
   +----------------------------------------------------------------------+

   VPC:  [checker Lambda] --5432/TLS--> [temporary RDS instance]
         (security group allows only the checker; instance is not public)

   Security:   IAM least privilege - one custom JSON policy per Lambda
   Deployment: AWS SAM / CloudFormation (Infrastructure as Code)
```

**Why Step Functions?** A real RDS restore often takes 10–20+ minutes, longer than the 15-minute maximum of one Lambda invocation. The workflow runs short Lambda steps and waits between them (waiting costs nothing), and its wiring guarantees that every path that may have started a restore passes through Teardown. `tests/test_state_machine.py` checks that guarantee.

**Why IAM database authentication?** The checker logs in with a 15-minute token signed by its own IAM role, so no database password is stored anywhere, and its policy allows logging in as exactly one read-only user. The token is computed locally, so the checker makes no AWS API calls. That means the VPC needs no NAT gateway or VPC endpoints (≈ $7–32/month avoided).

## Integrity checks
| Check | Catches |
|---|---|
| `instance_available` | Restore produced no usable instance, or the wrong engine |
| `connect` | Restored database unreachable or login broken |
| `tables_present` | A table silently missing from the backup |
| `row_counts` | Truncated / incomplete data |
| `canary_checksum` | Data altered or corrupted (a known table must match byte-for-byte) |
| `test_queries` | Application-level breakage, e.g. orphaned rows |

The expected tables, minimum row counts and test queries live in `src/checks/expectations.json`. A restore that hits an unrecoverable state (e.g. `inaccessible-encryption-credentials`, the deleted-KMS-key case) fails immediately.

Each run ends as **PASSED** (all checks passed), **FAILED** (restored, but a check failed) or **ERROR** (the pipeline itself broke, e.g. no snapshot). FAILED and ERROR send an alert.

## AWS services used
| Service | Role in the system |
|---|---|
| EventBridge | Schedules the periodic verification runs |
| Step Functions | Orchestrates restore → wait → check → teardown → record |
| Lambda | The individual steps (verifier) and the SQL checks (checker, in the VPC) |
| RDS | Temporary database restored from a snapshot for testing |
| VPC / security groups | Private network path from the checker to the temporary database only |
| S3 | Stores detailed verification reports |
| DynamoDB | Stores pass/fail history for fast lookups |
| SNS | Sends failure alerts (email) |
| CloudWatch | Logs, metrics and dashboards for backup health & RTO |
| IAM | Least-privilege roles, custom JSON policies, IAM database authentication |
| CloudFormation (via SAM) | Reproducible, automated deployment |

## Repository layout
| Path | Purpose |
|---|---|
| `template.yaml` | SAM/CloudFormation template — all infrastructure |
| `statemachine/restorecheck.asl.json` | The Step Functions workflow (Amazon States Language) |
| `samconfig.toml` | Saved `sam` options; the `dev` environment targets LocalStack |
| `src/handler.py` | Verifier Lambda: routes each workflow step to `pipeline.py` |
| `src/pipeline.py` | The steps: prepare, poll, teardown, record |
| `src/checker.py` | Checker Lambda: IAM-token login + integrity checks |
| `src/restore.py` | RDS operations: latest snapshot, restore, status, delete, straggler sweep |
| `src/reporting.py` | S3 report, DynamoDB history row, CloudWatch metrics, SNS alert |
| `src/checks/` | Integrity checks, one module each, plus `expectations.json` |
| `src/config.py`, `src/aws_clients.py` | Settings + boto3 client factory (dev mode lives here) |
| `tests/` | pytest tests, run against an in-process fake of AWS (moto) |
| `demo/source-db.yaml` | The demo PostgreSQL database RestoreCheck verifies (separate stack) |
| `scripts/` | `deploy_aws.ps1` / `teardown_aws.ps1`, `demo_db.py` (seed, break, snapshot the demo DB), `run_pipeline.py` (start a run and wait), `run_scenarios.py` (run every demo scenario, write `results/`), `export_runs.py` (export the run history as JSON, account details removed), `build_site.py` (a static summary page of the results), `deploy_local.ps1` (LocalStack) |
| `docs/` | Architecture diagram (`architecture.drawio`) and the references list |
| `dataset/` | The demo dataset for publishing (CSV tables, expectations, scenario results); built by `scripts/export_dataset.py` |
| `docker-compose.yml` | Starts LocalStack (optional) |

## Development
No AWS account or Docker is needed for the tests.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

pytest                    # unit tests (moto fakes AWS in-process)
cfn-lint template.yaml    # template lint
sam build                 # package both Lambdas (needs Python 3.12)
```

**Optional: LocalStack.** With Docker, a LocalStack auth token in `.env` (see `.env.example`) and `pip install aws-sam-cli-local`:
```powershell
docker compose up -d
.\scripts\deploy_local.ps1
python scripts/run_pipeline.py --dev
```

**Dev mode.** The `Stage=dev` template parameter sets `RESTORECHECK_DEV=true` on the verifier. In dev mode every boto3 client is created with an explicit LocalStack endpoint (`http://localhost:4566`, or the `AWS_ENDPOINT_URL` LocalStack injects) and dummy credentials, and the code refuses to start if that endpoint is an `amazonaws.com` host.

## Before the AWS deployment
- **Source database.** The verified database must be PostgreSQL, contain the `restorecheck_verifier` user with the `rds_iam` role, and match `expectations.json`. `scripts/demo_db.py seed` sets this up for the demo database.
- **Encrypted snapshots.** Snapshots encrypted with a customer-managed KMS key need `kms:CreateGrant`/`kms:DescribeKey` on that key added to the verifier policy.
- **Stack deletion.** Lambda's network interfaces in the VPC can take up to ~20–40 minutes to be released after the checker is deleted, so deleting the stack can be slow.

## Deploying to AWS (final demo)
The project's AWS account only allows the Sydney region (`ap-southeast-2`); the `restorecheck` CLI profile defaults to it.

```powershell
.\scripts\deploy_aws.ps1 -AlertEmail you@example.com   # demo DB + RestoreCheck (~15 min the first time)

python scripts/demo_db.py seed                          # healthy shop data + verifier user
python scripts/demo_db.py snapshot --label healthy
python scripts/run_pipeline.py --aws                    # -> PASSED

python scripts/demo_db.py break missing-table           # or truncated-table / corrupt-data / orphaned-rows
python scripts/demo_db.py snapshot --label missing-table
python scripts/run_pipeline.py --aws                    # -> FAILED, alert email

python scripts/run_pipeline.py --aws --source-db ghost-db   # -> ERROR (no backups exist)

.\scripts\teardown_aws.ps1                              # delete everything afterwards
```

Or run every scenario in one go (about an hour) and get a results table in `results/scenarios.md`:

```powershell
python scripts/run_scenarios.py
```

Each break scenario makes a different check fail: `missing-table` → `tables_present`, `truncated-table` → `row_counts`, `corrupt-data` → `canary_checksum`, `orphaned-rows` → `test_queries`. `demo_db.py seed` repairs the data.

**Cost.** The demo database (db.t3.micro) is the main cost while it exists; each verification run adds a temporary db.t3.micro for roughly 15–30 minutes. Everything else is within free usage. Run `teardown_aws.ps1` when the demo is recorded.

## SDGs addressed
- **SDG 9 (Industry, Innovation and Infrastructure)** — builds resilient, reliable digital infrastructure.
- **SDG 11 (Sustainable Cities and Communities)** — strengthens disaster recovery for essential services.

## Status
MVP in development. Future work: EC2/EBS disk-backup verification, multi-region restore testing, a web interface for browsing the run history.
