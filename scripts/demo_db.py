"""Manage the demo source database (the one RestoreCheck verifies).

    python scripts/demo_db.py seed                    # (re)create the healthy shop data
    python scripts/demo_db.py show                    # print what is in it right now
    python scripts/demo_db.py break missing-table     # damage it on purpose (see BREAKS)
    python scripts/demo_db.py snapshot --label broken # take a manual snapshot, wait for it
    python scripts/demo_db.py cleanup-snapshots       # delete the manual demo snapshots

Typical demo: seed -> snapshot -> run RestoreCheck (PASSED); break -> snapshot ->
run RestoreCheck (FAILED); seed again to repair.

The master password is read from Secrets Manager at run time and never printed.
"""
import argparse
import json
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import demo_data  # noqa: E402
from checks import canary  # noqa: E402

CA_BUNDLE = ROOT / "src" / "certs" / "rds-global-bundle.pem"
SNAPSHOT_PREFIX = "restorecheck-demo-"
VERIFIER_USER = "restorecheck_verifier"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="restorecheck", help="AWS CLI profile")
    parser.add_argument("--region", default=None, help="default: the profile's region")
    parser.add_argument("--stack-name", default="restorecheck-demo-db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="drop and recreate the healthy demo data")
    sub.add_parser("show", help="print row counts and the canary rows the corrupt-data break changes")
    breaker = sub.add_parser("break", help="damage the data in one specific way")
    breaker.add_argument("scenario", choices=sorted(demo_data.BREAKS))
    snap = sub.add_parser("snapshot", help="take a manual snapshot and wait until it's ready")
    snap.add_argument("--label", default="manual", help="word to put in the snapshot name")
    sub.add_parser("cleanup-snapshots", help="delete the manual snapshots this script took")
    return parser.parse_args()


def stack_outputs(session, stack_name):
    stack = session.client("cloudformation").describe_stacks(StackName=stack_name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def connect(session, outputs):
    import pg8000.dbapi

    secret = json.loads(
        session.client("secretsmanager").get_secret_value(SecretId=outputs["MasterSecretArn"])[
            "SecretString"
        ]
    )
    db = pg8000.dbapi.connect(
        user=secret["username"],
        password=secret["password"],
        host=outputs["Endpoint"],
        port=int(outputs["Port"]),
        database=outputs["DbName"],
        ssl_context=ssl.create_default_context(cafile=str(CA_BUNDLE)),
        timeout=20,
    )
    db.autocommit = True
    return db


def run_sql(db, statements):
    cursor = db.cursor()
    try:
        for statement in statements:
            if isinstance(statement, tuple):
                cursor.execute(*statement)
            else:
                cursor.execute(statement)
    finally:
        cursor.close()


def seed(db, outputs):
    data = demo_data.generate()
    run_sql(db, demo_data.SCHEMA)
    for table in demo_data.TABLE_ORDER:
        run_sql(db, list(demo_data.insert_statements(table, data[table])))
        print(f"  {table}: {len(data[table])} rows")
    run_sql(db, demo_data.verifier_user_sql(VERIFIER_USER, outputs["DbName"]))
    print(f"  user {VERIFIER_USER}: read-only, IAM authentication only")


CANARY_WINDOW = (40, 44)  # rows shown by `show`; corrupt-data changes row 42


def format_show(name, counts, canary_rows, checksum):
    """The `show` report. counts: {table: rows or None if missing}; canary_rows: [(id, payload)]."""
    expected = dict(canary.ROWS)
    lines = [f"Database {name}", "", f"  {'Table':<22}{'Rows':>6}"]
    for table, rows in counts.items():
        lines.append(f"  {table:<22}{'MISSING' if rows is None else rows:>6}")
    lines += ["", f"  Canary rows {CANARY_WINDOW[0]}-{CANARY_WINDOW[1]} (the corrupt-data break changes row 42):"]
    for row_id, payload in canary_rows:
        mark = "" if expected.get(row_id) == payload else "   <-- CHANGED"
        lines.append(f"    {row_id:>3}  {payload}{mark}")
    if checksum is None:
        lines += ["", "  Canary fingerprint: no canary table"]
    elif checksum == canary.expected_checksum():
        lines += ["", f"  Canary fingerprint: {checksum}  (matches: data intact)"]
    else:
        lines += ["", f"  Canary fingerprint: {checksum}  (DOES NOT MATCH {canary.expected_checksum()})"]
    return "\n".join(lines)


def show(db, name):
    cursor = db.cursor()
    try:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        present = {r[0] for r in cursor.fetchall()}
        counts = {}
        for table in demo_data.TABLE_ORDER:
            if table in present:
                cursor.execute(f"SELECT count(*) FROM {table}")  # names from our own constant list
                counts[table] = cursor.fetchone()[0]
            else:
                counts[table] = None
        canary_rows, checksum = [], None
        if canary.TABLE in present:
            cursor.execute(f"SELECT id, payload FROM {canary.TABLE} WHERE id BETWEEN %s AND %s ORDER BY id", CANARY_WINDOW)
            canary_rows = [tuple(r) for r in cursor.fetchall()]
            cursor.execute(canary.SQL)
            checksum = cursor.fetchone()[0]
    finally:
        cursor.close()
    print(format_show(name, counts, canary_rows, checksum))


def take_snapshot(rds, db_instance_id, label):
    snapshot_id = f"{SNAPSHOT_PREFIX}{label}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    rds.create_db_snapshot(
        DBInstanceIdentifier=db_instance_id,
        DBSnapshotIdentifier=snapshot_id,
        Tags=[{"Key": "project", "Value": "restorecheck-demo"}],
    )
    print(f"Creating snapshot {snapshot_id} (usually a few minutes)...")
    rds.get_waiter("db_snapshot_available").wait(
        DBSnapshotIdentifier=snapshot_id, WaiterConfig={"Delay": 20, "MaxAttempts": 90}
    )
    print("Snapshot ready. It is now the newest backup RestoreCheck will verify.")


def cleanup_snapshots(rds, db_instance_id):
    snapshots = rds.describe_db_snapshots(
        DBInstanceIdentifier=db_instance_id, SnapshotType="manual"
    )["DBSnapshots"]
    mine = [s["DBSnapshotIdentifier"] for s in snapshots if s["DBSnapshotIdentifier"].startswith(SNAPSHOT_PREFIX)]
    for snapshot_id in mine:
        rds.delete_db_snapshot(DBSnapshotIdentifier=snapshot_id)
        print(f"  deleted {snapshot_id}")
    print(f"Deleted {len(mine)} manual demo snapshot(s).")


def main():
    args = parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    outputs = stack_outputs(session, args.stack_name)
    rds = session.client("rds")

    if args.command == "seed":
        print(f"Seeding {outputs['DbInstanceIdentifier']}...")
        db = connect(session, outputs)
        try:
            seed(db, outputs)
        finally:
            db.close()
        print("Done. Take a snapshot next: python scripts/demo_db.py snapshot --label healthy")
    elif args.command == "show":
        db = connect(session, outputs)
        try:
            show(db, f"{outputs['DbInstanceIdentifier']} ({outputs['DbName']})")
        finally:
            db.close()
    elif args.command == "break":
        scenario = demo_data.BREAKS[args.scenario]
        db = connect(session, outputs)
        try:
            run_sql(db, scenario["sql"])
        finally:
            db.close()
        print(f"Applied '{args.scenario}'. Expect the '{scenario['trips']}' check to fail.")
        print("Take a snapshot next: python scripts/demo_db.py snapshot --label " + args.scenario)
    elif args.command == "snapshot":
        take_snapshot(rds, outputs["DbInstanceIdentifier"], args.label)
    elif args.command == "cleanup-snapshots":
        cleanup_snapshots(rds, outputs["DbInstanceIdentifier"])


if __name__ == "__main__":
    main()
