"""The verifier's pipeline steps.

Step Functions (statemachine/restorecheck.asl.json) runs them in order and keeps
the run's state between them. Each step receives that state and returns its own
piece of it, which Step Functions stores under a key:

    run       <- prepare()    which snapshot, which temporary instance
    restore   <- poll()       restore progress; the instance once it's available
    checks    <- checker.py   integrity check results (runs inside the VPC)
    error     <- any failure caught by the state machine
    teardown  <- teardown()   always runs once a restore may have started
    result    <- record()     PASSED / FAILED / ERROR
"""
import json
import logging
import time
from datetime import datetime, timezone

import reporting
import restore

logger = logging.getLogger(__name__)

PASSED, FAILED, ERROR = "PASSED", "FAILED", "ERROR"


def _timestamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def prepare(settings, rds, state, now, clock=time.time):
    """Sweep leftovers, find the newest snapshot and start restoring it."""
    prefix = settings.temp_instance_prefix
    # An execution may name a different database, e.g. to demo the "no backup" case.
    source_db_id = state.get("source_db_id") or settings.source_db_instance_id

    # Older than the longest a run can take = certainly abandoned, not in progress.
    stragglers = restore.cleanup_stragglers(
        rds, prefix, min_age_seconds=(settings.max_restore_minutes + 30) * 60, now=now
    )
    snapshot = restore.find_latest_snapshot(rds, source_db_id)
    temp_id = restore.temp_instance_id(prefix, now)
    restore_started_at = clock()
    restore.start_restore(
        rds,
        snapshot,
        temp_id,
        settings.temp_instance_class,
        _timestamp(now),
        subnet_group=settings.restore_subnet_group,
        security_group_id=settings.restore_security_group_id,
    )
    logger.info("Restoring %s into %s", snapshot["DBSnapshotIdentifier"], temp_id)
    return {
        "source_db_id": source_db_id,
        "run_timestamp": _timestamp(now),
        "snapshot": restore.snapshot_summary(snapshot),
        "temp_instance_id": temp_id,
        "restore_started_at": restore_started_at,
        "stragglers_deleted": stragglers,
    }


def poll(settings, rds, state, clock=time.time):
    """Report restore progress. Raises if the restore failed or is taking too long."""
    run = state["run"]
    instance = restore.describe_instance(rds, run["temp_instance_id"])
    status = instance["DBInstanceStatus"]
    elapsed = round(clock() - run["restore_started_at"], 1)

    if status in restore.FAILED_STATES:
        raise restore.RestoreFailedError(
            f"{run['temp_instance_id']} entered status {status!r} after {elapsed}s"
        )
    if status == "available":
        return {
            "ready": True,
            "status": status,
            "elapsed_seconds": elapsed,
            "instance": restore.instance_summary(instance),
        }
    if elapsed > settings.max_restore_minutes * 60:
        raise restore.RestoreTimeoutError(
            f"{run['temp_instance_id']} still {status!r} after {elapsed}s "
            f"(limit {settings.max_restore_minutes} min)"
        )
    return {"ready": False, "status": status, "elapsed_seconds": elapsed}


def teardown(settings, rds, state):
    """Delete this run's temporary instance, if it got as far as creating one."""
    temp_id = (state.get("run") or {}).get("temp_instance_id")
    if not temp_id:
        return {"deleted": None}
    restore.delete_temp_instance(rds, temp_id, settings.temp_instance_prefix)
    return {"deleted": temp_id}


def describe_error(caught):
    """Turn a Step Functions catch object ({"Error", "Cause"}) into one readable line."""
    if not caught:
        return None
    cause = caught.get("Cause") or ""
    try:
        # A failed Lambda puts its own error as a JSON string in Cause.
        cause = json.loads(cause).get("errorMessage", cause)
    except (ValueError, AttributeError):
        pass
    return f"{caught.get('Error', 'Error')}: {cause}"[:1000]


def build_report(settings, state, now, clock=time.time):
    run = state.get("run") or {}
    restore_state = state.get("restore") or {}
    checks = (state.get("checks") or {}).get("results", [])
    error = describe_error(state.get("error"))
    teardown_error = describe_error(state.get("teardown_error"))

    if error:
        status = ERROR  # the pipeline broke, so the backup was never judged
    elif checks and all(c["passed"] for c in checks):
        status = PASSED
    else:
        status = FAILED  # restored, but did not prove usable (no checks = not proven)

    temp_id = run.get("temp_instance_id")
    snapshot = run.get("snapshot") or {}
    return {
        "source_db_id": run.get("source_db_id")
        or state.get("source_db_id")
        or settings.source_db_instance_id,
        "run_timestamp": run.get("run_timestamp") or _timestamp(now),
        "status": status,
        "snapshot_id": snapshot.get("DBSnapshotIdentifier"),
        "snapshot_time": snapshot.get("SnapshotCreateTime"),
        "temp_instance_id": temp_id,
        "restore_seconds": restore_state.get("elapsed_seconds") if restore_state.get("ready") else None,
        "total_seconds": round(clock() - now.timestamp(), 1),
        "checks": checks,
        "stragglers_deleted": run.get("stragglers_deleted", []),
        "teardown_ok": None if not temp_id else teardown_error is None,
        "error": "; ".join(
            filter(None, [error, teardown_error and f"teardown failed: {teardown_error}"])
        )
        or None,
    }


def record(settings, clients, state, now, clock=time.time):
    """Write the report, history row and metrics; alert if anything went wrong."""
    report = build_report(settings, state, now, clock)
    key = reporting.report_key(report["source_db_id"], report["run_timestamp"])

    reporting.write_report(clients["s3"], settings.reports_bucket, key, report)
    reporting.record_result(
        clients["dynamodb"],
        settings.results_table,
        {
            "source_db_id": report["source_db_id"],
            "run_timestamp": report["run_timestamp"],
            "status": report["status"],
            "snapshot_id": report["snapshot_id"],
            "temp_instance_id": report["temp_instance_id"],
            "restore_seconds": report["restore_seconds"],
            "total_seconds": report["total_seconds"],
            "checks_passed": sum(c["passed"] for c in report["checks"]),
            "checks_total": len(report["checks"]),
            "teardown_ok": report["teardown_ok"],
            "report_key": key,
            "error": report["error"],
        },
    )
    reporting.publish_metrics(clients["cloudwatch"], settings.metric_namespace, report)
    if report["status"] != PASSED or report["teardown_ok"] is False:
        reporting.send_alert(
            clients["sns"],
            settings.alert_topic_arn,
            report,
            f"s3://{settings.reports_bucket}/{key}",
        )
    logger.info("Run finished: status=%s report=%s", report["status"], key)
    return {
        "status": report["status"],
        "source_db_id": report["source_db_id"],
        "run_timestamp": report["run_timestamp"],
        "teardown_ok": report["teardown_ok"],
        "report_key": key,
    }


def parse_time(value):
    """Parse Step Functions' $$.Execution.StartTime (ISO 8601); default to now."""
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
