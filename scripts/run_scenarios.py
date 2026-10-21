"""Run every demo scenario against AWS and save a results table for the report.

    python scripts/run_scenarios.py                              # all scenarios (~1 hour)
    python scripts/run_scenarios.py --only healthy corrupt-data  # a subset

For each scenario: reset the demo database to healthy, damage it in one specific
way, snapshot it, run RestoreCheck, and compare the outcome with what should
happen. Leaves the database healthy (with a fresh healthy snapshot) at the end.
Writes results/scenarios.json and results/scenarios.md.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import demo_data  # noqa: E402
import demo_db  # noqa: E402
from run_pipeline import start_and_wait, stack_output  # noqa: E402

RESULTS_DIR = ROOT / "results"
NO_BACKUP_DB = "restorecheck-demo-nobackup"  # never existed, so it has no snapshots

# name -> (break scenario or None, expected status, what it demonstrates)
SCENARIOS = {
    "healthy": (None, "PASSED", "Intact backup restores and passes every check"),
    "missing-table": ("missing-table", "FAILED", "A table silently missing from the backup"),
    "truncated-table": ("truncated-table", "FAILED", "Most rows of a table lost"),
    "corrupt-data": ("corrupt-data", "FAILED", "One value altered (rows and counts unchanged)"),
    "orphaned-rows": ("orphaned-rows", "FAILED", "Referential integrity broken"),
    "no-backup": (None, "ERROR", "Database has no backup at all"),
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="+", choices=list(SCENARIOS), help="run just these")
    parser.add_argument("--profile", default="restorecheck")
    parser.add_argument("--stack-name", default="restorecheck")
    parser.add_argument("--demo-stack-name", default="restorecheck-demo-db")
    return parser.parse_args()


def prepare_database(session, outputs, rds, break_name, label):
    """Reset to healthy, optionally damage, then snapshot (= newest backup)."""
    db = demo_db.connect(session, outputs)
    try:
        demo_db.seed(db, outputs)
        if break_name:
            demo_db.run_sql(db, demo_data.BREAKS[break_name]["sql"])
            print(f"  applied '{break_name}'", flush=True)
    finally:
        db.close()
    demo_db.take_snapshot(rds, outputs["DbInstanceIdentifier"], label)


def read_report(s3, bucket, key):
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def run_scenario(name, session, args, outputs, rds, s3, bucket):
    break_name, expected, meaning = SCENARIOS[name]
    print(f"\n=== {name}: expect {expected} ===", flush=True)
    if name == "no-backup":
        source_db = NO_BACKUP_DB
    else:
        source_db = None
        prepare_database(session, outputs, rds, break_name, name)

    status, result, execution_arn = start_and_wait(session, args.stack_name, source_db)
    report = read_report(s3, bucket, result["report_key"]) if result else {}
    row = {
        "scenario": name,
        "demonstrates": meaning,
        "expected": expected,
        "actual": report.get("status", f"no result ({status})"),
        "failed_checks": [c["name"] for c in report.get("checks", []) if not c["passed"]],
        "restore_seconds": report.get("restore_seconds"),
        "total_seconds": report.get("total_seconds"),
        "teardown_ok": report.get("teardown_ok"),
        "error": report.get("error"),
        # The run ID only: the full ARN embeds the AWS account ID, which this repo does not publish.
        "execution_id": execution_arn.rsplit(":", 1)[-1],
        "report_key": result["report_key"] if result else None,
    }
    row["as_expected"] = row["actual"] == expected
    print(f"  -> {row['actual']} ({'as expected' if row['as_expected'] else 'UNEXPECTED'})", flush=True)
    return row


def merge_results(new_rows, results_file):
    """Update earlier results with this run's, keyed by scenario, in SCENARIOS order."""
    by_name = {}
    if results_file.exists():
        by_name = {r["scenario"]: r for r in json.loads(results_file.read_text(encoding="utf-8"))}
    by_name.update({r["scenario"]: r for r in new_rows})
    return [by_name[name] for name in SCENARIOS if name in by_name]


def write_results(new_rows, results_dir=RESULTS_DIR):
    results_dir.mkdir(exist_ok=True)
    rows = merge_results(new_rows, results_dir / "scenarios.json")
    (results_dir / "scenarios.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    lines = [
        f"Scenario runs on {datetime.now(timezone.utc):%Y-%m-%d} (AWS ap-southeast-2, db.t3.micro, PostgreSQL 17).",
        "",
        "| Scenario | Demonstrates | Expected | Actual | Failed checks | Restore (s) | Teardown OK |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        failed = ", ".join(f"`{c}`" for c in r["failed_checks"]) or ("-" if r["actual"] != "ERROR" else "n/a")
        restore = f"{r['restore_seconds']:.0f}" if r["restore_seconds"] else "-"
        teardown = {True: "yes", False: "NO", None: "n/a (nothing created)"}[r["teardown_ok"]]
        mark = "" if r["as_expected"] else " (UNEXPECTED)"
        lines.append(
            f"| {r['scenario']} | {r['demonstrates']} | {r['expected']} | **{r['actual']}**{mark} "
            f"| {failed} | {restore} | {teardown} |"
        )
    (results_dir / "scenarios.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    session = boto3.Session(profile_name=args.profile)
    outputs = demo_db.stack_outputs(session, args.demo_stack_name)
    rds, s3 = session.client("rds"), session.client("s3")
    bucket = stack_output(session.client("cloudformation"), args.stack_name, "ReportsBucketName")

    rows = []
    try:
        for name in args.only or list(SCENARIOS):
            rows.append(run_scenario(name, session, args, outputs, rds, s3, bucket))
    finally:
        if rows:
            write_results(rows)
        print("\nRestoring the healthy database and snapshot...", flush=True)
        prepare_database(session, outputs, rds, None, "healthy")

    print(f"\nWrote {RESULTS_DIR / 'scenarios.md'}")
    print((RESULTS_DIR / "scenarios.md").read_text(encoding="utf-8"))
    sys.exit(0 if all(r["as_expected"] for r in rows) else 1)


if __name__ == "__main__":
    main()
