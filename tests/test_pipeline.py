import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import checker
import handler
import pipeline
import restore

NOW = datetime(2026, 10, 16, 2, 0, 0, tzinfo=timezone.utc)
TEMP_ID = "restorecheck-tmp-20261016020000"


def clock_at(seconds_after_now):
    return lambda: NOW.timestamp() + seconds_after_now


def caught(err):
    """What a Step Functions Catch stores for an exception raised in a Lambda."""
    return {
        "Error": type(err).__name__,
        "Cause": json.dumps({"errorMessage": str(err), "errorType": type(err).__name__}),
    }


def execute(fake_aws, db=None, connect=None):
    """Follow statemachine/restorecheck.asl.json step by step, the way Step
    Functions would: any failure is caught and the run goes to Teardown."""
    settings, rds, state = fake_aws.settings, fake_aws.rds, {}
    try:
        state["run"] = pipeline.prepare(settings, rds, state, NOW, clock=clock_at(0))
        state["restore"] = pipeline.poll(settings, rds, state, clock=clock_at(420))
        assert state["restore"]["ready"]
        state["checks"] = checker.run(state, connect=connect or (lambda instance: db))
    except Exception as err:
        state["error"] = caught(err)
    try:
        state["teardown"] = pipeline.teardown(settings, rds, state)
    except Exception as err:
        state["teardown_error"] = caught(err)
    state["result"] = pipeline.record(
        settings, fake_aws.clients, state, NOW, clock=clock_at(480)
    )
    return state


def history_row(fake_aws):
    (item,) = fake_aws.dynamodb.scan(TableName="results-table")["Items"]
    return item


def stored_report(fake_aws, key):
    body = fake_aws.s3.get_object(Bucket="reports-bucket", Key=key)["Body"].read()
    return json.loads(body)


# --- prepare --------------------------------------------------------------


def test_prepare_restores_latest_snapshot_into_private_network(fake_aws, snapshot):
    sent = {}
    fake_aws.rds.meta.events.register(
        "provide-client-params.rds.RestoreDBInstanceFromDBSnapshot",
        lambda params, **kwargs: sent.update(params),
    )

    run = pipeline.prepare(fake_aws.settings, fake_aws.rds, {}, NOW, clock=clock_at(0))

    assert run["temp_instance_id"] == TEMP_ID
    assert run["run_timestamp"] == "2026-10-16T02:00:00Z"
    assert run["source_db_id"] == "orders-db"
    json.dumps(run)  # must be JSON-safe: Step Functions stores it between steps

    temp = restore.describe_instance(fake_aws.rds, TEMP_ID)
    assert temp["DBSubnetGroup"]["DBSubnetGroupName"] == "restorecheck-subnets"
    assert [g["VpcSecurityGroupId"] for g in temp["VpcSecurityGroups"]] == [
        fake_aws.restored_db_security_group
    ]
    # Flags moto accepts but doesn't echo back: check what was sent to RDS.
    assert sent["PubliclyAccessible"] is False
    assert sent["EnableIAMDatabaseAuthentication"] is True
    assert sent["DeletionProtection"] is False
    assert {"Key": "restorecheck:temporary", "Value": "true"} in sent["Tags"]


def test_prepare_can_target_another_database(fake_aws):
    with pytest.raises(restore.NoSnapshotError, match="never-backed-up-db"):
        pipeline.prepare(
            fake_aws.settings, fake_aws.rds, {"source_db_id": "never-backed-up-db"}, NOW
        )


def test_prepare_sweeps_leftovers_from_earlier_runs(fake_aws, snapshot):
    fake_aws.rds.restore_db_instance_from_db_snapshot(
        DBInstanceIdentifier="restorecheck-tmp-20261015020000", DBSnapshotIdentifier=snapshot
    )
    # Past MaxRestoreMinutes + margin, so that instance is certainly abandoned.
    next_run = datetime.now(timezone.utc) + timedelta(hours=2)

    run = pipeline.prepare(fake_aws.settings, fake_aws.rds, {}, next_run)

    assert run["stragglers_deleted"] == ["restorecheck-tmp-20261015020000"]
    assert fake_aws.instance_ids() == ["orders-db", run["temp_instance_id"]]


def test_prepare_leaves_a_concurrent_runs_instance_alone(fake_aws, snapshot):
    fake_aws.rds.restore_db_instance_from_db_snapshot(
        DBInstanceIdentifier="restorecheck-tmp-concurrent", DBSnapshotIdentifier=snapshot
    )

    run = pipeline.prepare(fake_aws.settings, fake_aws.rds, {}, datetime.now(timezone.utc))

    assert run["stragglers_deleted"] == []
    assert "restorecheck-tmp-concurrent" in fake_aws.instance_ids()


# --- poll -------------------------------------------------------------------


def fake_status(monkeypatch, status):
    monkeypatch.setattr(
        restore,
        "describe_instance",
        lambda rds, instance_id: {"DBInstanceIdentifier": instance_id, "DBInstanceStatus": status},
    )


RUN_STATE = {"run": {"temp_instance_id": TEMP_ID, "restore_started_at": NOW.timestamp()}}


def test_poll_reports_progress_while_restoring(fake_aws, monkeypatch):
    fake_status(monkeypatch, "creating")

    result = pipeline.poll(fake_aws.settings, None, RUN_STATE, clock=clock_at(300))

    assert result == {"ready": False, "status": "creating", "elapsed_seconds": 300.0}


def test_poll_gives_up_after_max_restore_minutes(fake_aws, monkeypatch):
    fake_status(monkeypatch, "creating")

    with pytest.raises(restore.RestoreTimeoutError):
        pipeline.poll(fake_aws.settings, None, RUN_STATE, clock=clock_at(61 * 60))


def test_poll_fails_fast_when_key_is_unusable(fake_aws, monkeypatch):
    fake_status(monkeypatch, "inaccessible-encryption-credentials")

    with pytest.raises(restore.RestoreFailedError, match="inaccessible-encryption-credentials"):
        pipeline.poll(fake_aws.settings, None, RUN_STATE, clock=clock_at(60))


# --- teardown ---------------------------------------------------------------


def test_teardown_without_a_restore_does_nothing(fake_aws):
    assert pipeline.teardown(fake_aws.settings, fake_aws.rds, {}) == {"deleted": None}


# --- whole runs ---------------------------------------------------------------


def test_healthy_backup_passes_and_leaves_nothing_running(fake_aws, snapshot, healthy_db):
    state = execute(fake_aws, db=healthy_db)

    assert state["result"]["status"] == "PASSED"
    assert state["result"]["teardown_ok"] is True
    assert fake_aws.instance_ids() == ["orders-db"]
    assert fake_aws.alerts() == []

    report = stored_report(fake_aws, state["result"]["report_key"])
    assert state["result"]["report_key"] == "reports/orders-db/2026-10-16T02:00:00Z.json"
    assert report["restore_seconds"] == 420.0
    assert report["total_seconds"] == 480.0
    assert len(report["checks"]) == 6

    row = history_row(fake_aws)
    assert row["status"] == {"S": "PASSED"}
    assert row["checks_passed"] == {"N": "6"}
    assert row["restore_seconds"] == {"N": "420.0"}


def test_missing_table_fails_alerts_and_still_tears_down(fake_aws, snapshot, healthy_db):
    del healthy_db.tables["order_items"]

    state = execute(fake_aws, db=healthy_db)

    assert state["result"]["status"] == "FAILED"
    assert fake_aws.instance_ids() == ["orders-db"]
    (alert,) = fake_aws.alerts()
    assert alert["Subject"] == "RestoreCheck FAILED: orders-db"
    assert "missing tables: order_items" in alert["Message"]


def test_unreachable_database_fails_and_still_tears_down(fake_aws, snapshot):
    def refuse(instance):
        raise TimeoutError("timed out")

    state = execute(fake_aws, connect=refuse)

    assert state["result"]["status"] == "FAILED"
    assert fake_aws.instance_ids() == ["orders-db"]


def test_database_without_backups_is_an_error_and_alerts(fake_aws, monkeypatch):
    monkeypatch.setattr(
        fake_aws, "settings", replace(fake_aws.settings, source_db_instance_id="never-backed-up-db")
    )

    state = execute(fake_aws)

    assert state["result"]["status"] == "ERROR"
    assert state["result"]["teardown_ok"] is None  # nothing was created
    (alert,) = fake_aws.alerts()
    assert alert["Subject"] == "RestoreCheck ERROR: never-backed-up-db"
    assert "NoSnapshotError: No available snapshot found for never-backed-up-db" in alert["Message"]


def test_failed_teardown_alerts_even_when_backup_passed(fake_aws, snapshot, healthy_db, monkeypatch):
    def broken_delete(*args, **kwargs):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(restore, "delete_temp_instance", broken_delete)

    state = execute(fake_aws, db=healthy_db)

    assert state["result"]["status"] == "PASSED"
    assert state["result"]["teardown_ok"] is False
    (alert,) = fake_aws.alerts()
    assert "teardown failed: RuntimeError: AccessDenied" in alert["Message"]


def test_no_check_results_is_not_a_pass(fake_aws):
    report = pipeline.build_report(
        fake_aws.settings, {"run": {"temp_instance_id": TEMP_ID}, "checks": {"results": []}}, NOW
    )

    assert report["status"] == "FAILED"


def test_error_cause_that_is_not_json_is_kept_as_is():
    assert pipeline.describe_error({"Error": "States.Timeout", "Cause": "took too long"}) == (
        "States.Timeout: took too long"
    )


# --- Lambda entry point -----------------------------------------------------


def test_handler_dispatches_steps(fake_aws, snapshot):
    run = handler.lambda_handler(
        {"action": "prepare", "state": {}, "execution_start": "2026-10-16T02:00:00.123Z"}, None
    )
    assert run["temp_instance_id"] == TEMP_ID

    torn_down = handler.lambda_handler({"action": "teardown", "state": {"run": run}}, None)
    assert torn_down == {"deleted": TEMP_ID}


def test_handler_rejects_unknown_actions(fake_aws):
    with pytest.raises(ValueError, match="Unknown action"):
        handler.lambda_handler({"action": "explode"}, None)
