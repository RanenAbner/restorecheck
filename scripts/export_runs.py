"""Export RestoreCheck's run history for the dashboard (docs/data/runs.json).

    python scripts/export_runs.py --aws --profile restorecheck
    python scripts/export_runs.py --dev                  # LocalStack

Reads every row of the results table (DynamoDB) and the detailed report of each
run (S3), labels the demo scenarios, and removes account-specific details
(account IDs, bucket names, RDS endpoint IDs) so the file can be published.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "runs.json"
SCENARIOS = ROOT / "results" / "scenarios.json"
LOCALSTACK_ENDPOINT = "http://localhost:4566"

# Demo snapshots are named restorecheck-demo-<scenario>-<YYYYmmdd>-<HHMMSS> (scripts/demo_db.py).
SNAPSHOT_SCENARIO = re.compile(r"^restorecheck-demo-(.+)-\d{8}-\d{6}$")

# Account-specific details that must not be published.
_MASKS = [
    (re.compile(r"(arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:)\d{12}"), r"\1<account>"),
    (re.compile(r"\b\d{12}\b"), "<account>"),
    (re.compile(r"s3://[a-z0-9.-]+/"), "s3://<reports-bucket>/"),
    # host.<12-char id>.<region>.rds.amazonaws.com: the id is unique to the account
    (re.compile(r"\.[a-z0-9]{12}(\.[a-z0-9-]+\.rds\.amazonaws\.com)"), r".<id>\1"),
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--dev", action="store_true", help="read from LocalStack")
    target.add_argument("--aws", action="store_true", help="read from real AWS")
    parser.add_argument("--stack-name", help="default: restorecheck-dev (--dev) / restorecheck (--aws)")
    parser.add_argument("--profile", help="AWS CLI profile to use (--aws only)")
    parser.add_argument("--region", default=None, help="AWS region (default: from your profile)")
    parser.add_argument("--out", type=Path, default=OUT)
    return parser.parse_args()


def mask(text):
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


def sanitize(value):
    """Mask account-specific details in every string of a JSON-like value."""
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    return value


def scan_all(dynamodb, table):
    """Every item of the results table, as plain Python values."""
    deserializer = TypeDeserializer()
    items, kwargs = [], {"TableName": table}
    while True:
        page = dynamodb.scan(**kwargs)
        items += [{k: deserializer.deserialize(v) for k, v in item.items()} for item in page["Items"]]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def load_report(s3, bucket, key):
    """The run's S3 report, or None if it has expired (reports are kept 90 days)."""
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except ClientError as err:
        if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def _number(value):
    return float(value) if value is not None else None


def scenario_of(item, recorded):
    """(scenario name, part of the recorded results?) for one run."""
    if item.get("report_key") in recorded:
        return recorded[item["report_key"]], True
    match = SNAPSHOT_SCENARIO.match(item.get("snapshot_id") or "")
    return (match.group(1) if match else "manual"), False


def build_run(item, report, recorded):
    scenario, is_recorded = scenario_of(item, recorded)
    report = report or {}
    return {
        "source_db_id": item["source_db_id"],
        "run_timestamp": item["run_timestamp"],
        "status": item["status"],
        "scenario": scenario,
        "recorded_result": is_recorded,
        "snapshot_id": item.get("snapshot_id"),
        "snapshot_time": report.get("snapshot_time"),
        "temp_instance_id": item.get("temp_instance_id"),
        "restore_seconds": _number(item.get("restore_seconds")),
        "total_seconds": _number(item.get("total_seconds")),
        "checks_passed": int(item.get("checks_passed") or 0),
        "checks_total": int(item.get("checks_total") or 0),
        "teardown_ok": item.get("teardown_ok"),
        "error": item.get("error"),
        "checks": report.get("checks", []),
        "report_available": bool(report),
    }


def build(items, reports, scenarios, exported_at):
    """The dashboard's data file: runs oldest first, every string sanitized."""
    recorded = {s["report_key"]: s["scenario"] for s in scenarios}
    runs = [build_run(item, reports.get(item.get("report_key")), recorded) for item in items]
    runs.sort(key=lambda r: (r["run_timestamp"], r["source_db_id"]))
    return sanitize({"exported_at": exported_at, "runs": runs})


def stack_output(cloudformation, stack_name, key):
    stack = cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]
    for output in stack.get("Outputs", []):
        if output["OutputKey"] == key:
            return output["OutputValue"]
    sys.exit(f"Stack {stack_name} has no output {key}. Is it deployed?")


def main():
    args = parse_args()
    if args.dev:
        session = boto3.Session(
            aws_access_key_id="test",  # LocalStack accepts anything; not a secret
            aws_secret_access_key="test",
            region_name=args.region or "us-east-1",
        )
        endpoint = {"endpoint_url": LOCALSTACK_ENDPOINT}
    else:
        session, endpoint = boto3.Session(profile_name=args.profile, region_name=args.region), {}
    stack_name = args.stack_name or ("restorecheck-dev" if args.dev else "restorecheck")

    cloudformation = session.client("cloudformation", **endpoint)
    table = stack_output(cloudformation, stack_name, "ResultsTableName")
    bucket = stack_output(cloudformation, stack_name, "ReportsBucketName")
    s3 = session.client("s3", **endpoint)

    items = scan_all(session.client("dynamodb", **endpoint), table)
    reports = {i["report_key"]: load_report(s3, bucket, i["report_key"]) for i in items if i.get("report_key")}
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8")) if SCENARIOS.exists() else []
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = build(items, reports, scenarios, exported_at)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} ({len(data['runs'])} runs)")


if __name__ == "__main__":
    main()
