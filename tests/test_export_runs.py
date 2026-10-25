import json

import boto3

import export_runs

ITEM = {
    "source_db_id": "orders-db",
    "run_timestamp": "2026-10-21T12:43:43Z",
    "status": "FAILED",
    "snapshot_id": "restorecheck-demo-corrupt-data-20261021-124053",
    "temp_instance_id": "restorecheck-tmp-20261021124343",
    "restore_seconds": 424.9,
    "total_seconds": 437.0,
    "checks_passed": 5,
    "checks_total": 6,
    "teardown_ok": True,
    "report_key": "reports/orders-db/2026-10-21T12:43:43Z.json",
    "error": None,
}
REPORT = {
    "snapshot_time": "2026-10-21T12:40:58+00:00",
    "checks": [
        {"name": "instance_available", "passed": True,
         "detail": "postgres 17.9 available at restorecheck-tmp-1.cfg4o8mow6yt.ap-southeast-2.rds.amazonaws.com:5432"},
        {"name": "canary_checksum", "passed": False, "detail": "checksum abc does not match expected def"},
    ],
}


def test_account_details_are_masked():
    text = (
        "arn:aws:states:ap-southeast-2:751597036307:execution:sm:run-1 "
        "s3://restorecheck-reportsbucket-wgxnqsmqbfyf/reports/x.json "
        "db.cfg4o8mow6yt.ap-southeast-2.rds.amazonaws.com account 751597036307"
    )

    masked = export_runs.mask(text)

    assert "751597036307" not in masked
    assert "wgxnqsmqbfyf" not in masked
    assert "cfg4o8mow6yt" not in masked
    assert "arn:aws:states:ap-southeast-2:<account>:execution" in masked
    assert "db.<id>.ap-southeast-2.rds.amazonaws.com" in masked


def test_md5_checksums_are_not_mistaken_for_account_ids():
    detail = "100 canary rows intact (md5 c2ccd15b4107e750ceda7aed4d5af6e4)"

    assert export_runs.mask(detail) == detail


def test_scenario_comes_from_recorded_results_then_snapshot_name():
    recorded = {ITEM["report_key"]: "corrupt-data"}
    rerun = {**ITEM, "report_key": "reports/orders-db/other.json",
             "snapshot_id": "restorecheck-demo-missing-table-20261021-114733"}
    manual = {**ITEM, "report_key": "reports/orders-db/manual.json", "snapshot_id": "rds:orders-db-2026-10-21"}

    assert export_runs.scenario_of(ITEM, recorded) == ("corrupt-data", True)
    assert export_runs.scenario_of(rerun, recorded) == ("missing-table", False)
    assert export_runs.scenario_of(manual, recorded) == ("manual", False)


def test_build_sorts_runs_and_merges_report_details():
    later = {**ITEM, "run_timestamp": "2026-10-22T00:00:00Z", "report_key": "reports/orders-db/late.json"}
    no_backup = {"source_db_id": "ghost-db", "run_timestamp": "2026-10-21T13:00:00Z", "status": "ERROR",
                 "checks_passed": 0, "checks_total": 0, "teardown_ok": None,
                 "report_key": "reports/ghost-db/x.json", "error": "NoSnapshotError: none"}

    data = export_runs.build([later, no_backup, ITEM], {ITEM["report_key"]: REPORT}, [], "2026-10-25T00:00:00Z")

    runs = data["runs"]
    assert [r["run_timestamp"] for r in runs] == [
        "2026-10-21T12:43:43Z", "2026-10-21T13:00:00Z", "2026-10-22T00:00:00Z"]
    assert runs[0]["checks"][1]["passed"] is False
    assert "cfg4o8mow6yt" not in json.dumps(data)
    assert runs[1]["restore_seconds"] is None and runs[1]["teardown_ok"] is None
    assert runs[2]["report_available"] is False and runs[2]["checks"] == []


def test_reads_history_and_reports_from_aws(fake_aws):
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.Table("results-table").put_item(Item={
        k: v for k, v in ITEM.items() if k not in ("restore_seconds", "total_seconds", "error")})
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(Bucket="reports-bucket", Key=ITEM["report_key"], Body=json.dumps(REPORT))

    items = export_runs.scan_all(boto3.client("dynamodb", region_name="us-east-1"), "results-table")

    assert [i["run_timestamp"] for i in items] == [ITEM["run_timestamp"]]
    assert export_runs.load_report(s3, "reports-bucket", ITEM["report_key"]) == REPORT
    assert export_runs.load_report(s3, "reports-bucket", "reports/missing.json") is None
