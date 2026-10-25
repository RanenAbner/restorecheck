# RestoreCheck — Project Context for Claude Code

## What this project is
RestoreCheck is a cloud-architecture course project: an **automated backup-verification and disaster-recovery testing system on AWS**.

Core thesis: AWS guarantees backup **durability** (11 nines — your bytes won't be lost) but NOT **recoverability** (that the backup can actually be restored into a working system). A backup can be perfectly durable yet unrestorable because it is incomplete, application-inconsistent, encrypted with a deleted key, or because the restore *process* itself is broken. RestoreCheck periodically performs a real **test restore** to prove backups are recoverable, alerts on failure, and tears down temporary resources to control cost.

Industry principle: *"A backup isn't real until you've tested the restore"* (Schrödinger's backup).

## MVP scope (build this first)
Verify **RDS database backups**:
1. **EventBridge** schedule (cron) triggers the pipeline.
2. **Step Functions** orchestrates the test through short **Lambda** steps (Python 3.12 + Boto3):
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
- Live web dashboard (S3 + CloudFront) reading DynamoDB directly. For the course, the GitHub Pages dashboard (`docs/index.html`) shows the exported run history instead (`scripts/export_runs.py` -> `docs/data/runs.json`).

## Tech decisions (and why — the prof may ask)
- **Language:** Python 3.12 + Boto3 (AWS SDK for Python).
- **IaC:** **AWS SAM** — compiles to CloudFormation under the hood, so it satisfies the "Automating Infrastructure with CloudFormation" requirement while being far less verbose for serverless resources.
- **Local dev/testing:** **LocalStack** (emulates AWS locally) so the whole system can be built and tested for free.
- **Real AWS deployment is required for the final demo.** (The professor first said it wasn't, then reversed that.) Build and test on moto/LocalStack, deploy to AWS once the system works, capture screenshots and a recording from the real console, then delete everything to stay within free credits.
- **Backup type for MVP:** RDS snapshots of a **PostgreSQL** instance. EC2/EBS is a documented future extension.
- **Orchestration: Step Functions**, not one Lambda. A real RDS restore can outlast Lambda's 15-minute limit; the workflow waits between short Lambda steps, and every path that may have started a restore goes through Teardown (`tests/test_state_machine.py` enforces this).
- **Two Lambdas, two custom policies.** The verifier (prepare/poll/teardown/record) calls AWS APIs from outside the VPC. The checker runs SQL from inside the VPC and calls no AWS APIs, so no NAT gateway or VPC endpoints are needed.
- **IAM database authentication** for the checker: no stored DB password; `rds-db:connect` is scoped to one read-only DB user.

## Repo conventions
- `template.yaml` — SAM/CloudFormation template (all infra).
- `src/` — Lambda function code (handler + check modules).
- `src/checks/` — individual integrity-check functions, each independently testable.
- `tests/` — unit tests (pytest), runnable against LocalStack.
- `statemachine/` — the Step Functions workflow (ASL JSON).
- `demo/` — the demo source database stack (separate from RestoreCheck's own stack).
- `scripts/` — helper scripts (deploy/teardown, seed and break the demo DB, start a run).
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
5. CloudWatch metrics/dashboard (done).
6. Make it AWS-ready: Step Functions orchestration, VPC checker, IAM DB auth (done), plus the items in README "Before the AWS deployment".
7. Deploy to AWS, run PASSED / FAILED / ERROR scenarios, capture screenshots and a recording, then delete the stack and the source database.
8. Project website on GitHub Pages (done): dashboard built from the exported run history, plus the "How it works" page; it is the report's "Project demo link".
