# RestoreCheck — Project Context for Claude Code

## What this project is
RestoreCheck is a cloud-architecture course project: an **automated backup-verification and disaster-recovery testing system on AWS**.

Core thesis: AWS guarantees backup **durability** (11 nines — your bytes won't be lost) but NOT **recoverability** (that the backup can actually be restored into a working system). A backup can be perfectly durable yet unrestorable because it is incomplete, application-inconsistent, encrypted with a deleted key, or because the restore *process* itself is broken. RestoreCheck periodically performs a real **test restore** to prove backups are recoverable, alerts on failure, and tears down temporary resources to control cost.

Industry principle: *"A backup isn't real until you've tested the restore"* (Schrödinger's backup).

## MVP scope (build this first)
Verify **RDS database backups**:
1. **EventBridge** schedule (cron) triggers the pipeline.
2. **Lambda** (Python 3.12 + Boto3) orchestrates the test:
   - Find the latest **RDS snapshot**.
   - Restore it into a **temporary** RDS instance.
   - Run **integrity checks**: connect, confirm expected tables exist, run test queries, check row counts / basic checksums.
   - Record pass/fail + timestamp in **DynamoDB**; write a detailed report to **S3**.
   - On failure, publish to an **SNS** topic (email alert).
   - **Delete the temporary RDS instance** (cost control — this is a key feature, not an afterthought).
3. **CloudWatch** metrics + dashboard for backup health and restore-time (RTO) trends.
4. **IAM** least-privilege execution role, including a **custom JSON policy** (course requirement).

## Future extensions (note, don't build yet)
- EC2/EBS snapshot verification (server-disk backups).
- Multi-region restore testing.
- Simple web dashboard (static site on S3 + CloudFront) reading from DynamoDB.

## Tech decisions (and why — the prof may ask)
- **Language:** Python 3.12 + Boto3 (AWS SDK for Python).
- **IaC:** **AWS SAM** — compiles to CloudFormation under the hood, so it satisfies the "Automating Infrastructure with CloudFormation" requirement while being far less verbose for serverless resources.
- **Local dev/testing:** **LocalStack** (emulates AWS locally) so the whole system can be built and tested for free; deploy to real AWS only for the final demo to stay inside free tier.
- **Backup type for MVP:** RDS snapshots. EC2/EBS is a documented future extension.

## Repo conventions
- `template.yaml` — SAM/CloudFormation template (all infra).
- `src/` — Lambda function code (handler + check modules).
- `src/checks/` — individual integrity-check functions, each independently testable.
- `tests/` — unit tests (pytest), runnable against LocalStack.
- `scripts/` — helper scripts (deploy, seed test data, local run).
- `README.md` — architecture overview (also used for the project report).
- Keep secrets/keys OUT of the repo. Use IAM roles, never hardcoded credentials.

## Guardrails (important)
- **Cost safety:** the Lambda MUST delete any temporary RDS/EC2 resource it creates, even on failure paths (use try/finally). Never leave an instance running.
- **Least privilege:** the Lambda role gets only the specific actions it needs (describe/restore/delete snapshots, write to one DynamoDB table + one S3 bucket, publish to one SNS topic). Include the custom JSON policy in the template.
- **Idempotency:** re-running the scheduled job should not pile up orphaned resources; name/tag temp resources predictably and clean up stragglers.
- **Dev mode:** support a `--dev` / env flag that targets LocalStack endpoints so nothing hits real AWS during development.

## Suggested build order
1. Repo structure + SAM template skeleton (EventBridge, Lambda, DynamoDB, S3, SNS, IAM role + custom policy).
2. Lambda handler happy path (restore → check → record → teardown).
3. Integrity-check modules + unit tests against LocalStack.
4. Failure handling + SNS alerting + guaranteed teardown.
5. CloudWatch metrics/dashboard.
6. Deploy to real AWS, run a live demo, capture screenshots/recording for the report.
