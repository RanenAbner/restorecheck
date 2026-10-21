"""RDS operations: find the latest snapshot, restore it, check on it, tear it down."""
import logging

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

TEMP_TAG_KEY = "restorecheck:temporary"
RUN_TAG_KEY = "restorecheck:run-id"

# Statuses a restoring instance can end up in that it will never recover from.
# "inaccessible-encryption-credentials" is the deleted/disabled KMS key case:
# a perfectly durable snapshot that can no longer be decrypted.
FAILED_STATES = frozenset(
    {
        "failed",
        "inaccessible-encryption-credentials",
        "incompatible-network",
        "incompatible-option-group",
        "incompatible-parameters",
        "incompatible-restore",
        "restore-error",
        "storage-full",
    }
)


class NoSnapshotError(RuntimeError):
    """The source database has no snapshot that can be restored."""


class RestoreFailedError(RuntimeError):
    """The restored instance ended up in a state it will never recover from."""


class RestoreTimeoutError(RuntimeError):
    """The restore took longer than the configured maximum."""


def latest_available(snapshots):
    """Return the newest snapshot whose status is 'available', or None."""
    available = [s for s in snapshots if s.get("Status") == "available"]
    if not available:
        return None
    return max(available, key=lambda s: s["SnapshotCreateTime"])


def find_latest_snapshot(rds, source_db_instance_id):
    # With no SnapshotType filter, RDS returns both automated and manual snapshots.
    snapshots = []
    paginator = rds.get_paginator("describe_db_snapshots")
    for page in paginator.paginate(DBInstanceIdentifier=source_db_instance_id):
        snapshots.extend(page["DBSnapshots"])
    snapshot = latest_available(snapshots)
    if snapshot is None:
        raise NoSnapshotError(f"No available snapshot found for {source_db_instance_id}")
    return snapshot


def temp_instance_id(prefix, run_time):
    # e.g. restorecheck-tmp-20261016020000 - predictable, so leftovers are easy to find.
    return f"{prefix}{run_time:%Y%m%d%H%M%S}"


def start_restore(
    rds,
    snapshot,
    instance_id,
    instance_class,
    run_id,
    subnet_group=None,
    security_group_id=None,
):
    kwargs = {}
    if subnet_group:
        kwargs["DBSubnetGroupName"] = subnet_group
    if security_group_id:
        kwargs["VpcSecurityGroupIds"] = [security_group_id]
    rds.restore_db_instance_from_db_snapshot(
        DBInstanceIdentifier=instance_id,
        DBSnapshotIdentifier=snapshot["DBSnapshotIdentifier"],
        DBInstanceClass=instance_class,
        MultiAZ=False,
        PubliclyAccessible=False,
        DeletionProtection=False,
        # Lets the checker log in with a short-lived IAM token instead of a password.
        EnableIAMDatabaseAuthentication=True,
        Tags=[
            {"Key": TEMP_TAG_KEY, "Value": "true"},
            {"Key": RUN_TAG_KEY, "Value": run_id},
        ],
        **kwargs,
    )


def describe_instance(rds, instance_id):
    return rds.describe_db_instances(DBInstanceIdentifier=instance_id)["DBInstances"][0]


def instance_summary(instance):
    """The JSON-safe subset of an instance description that later steps need."""
    endpoint = instance.get("Endpoint") or {}
    return {
        "DBInstanceIdentifier": instance["DBInstanceIdentifier"],
        "DBInstanceStatus": instance["DBInstanceStatus"],
        "Engine": instance.get("Engine"),
        "EngineVersion": instance.get("EngineVersion"),
        "Endpoint": {"Address": endpoint.get("Address"), "Port": endpoint.get("Port")},
    }


def snapshot_summary(snapshot):
    """The JSON-safe subset of a snapshot description that later steps need."""
    return {
        "DBSnapshotIdentifier": snapshot["DBSnapshotIdentifier"],
        "Engine": snapshot.get("Engine"),
        "SnapshotCreateTime": snapshot["SnapshotCreateTime"].isoformat(),
    }


def delete_temp_instance(rds, instance_id, prefix):
    """Delete a temporary instance. Already-gone instances are not an error."""
    # The IAM policy already forbids deleting anything else; this check makes the
    # code refuse too, so a bug fails loudly instead of being caught only by IAM.
    if not instance_id.startswith(prefix):
        raise ValueError(f"Refusing to delete {instance_id}: not a {prefix}* temporary instance")
    try:
        rds.delete_db_instance(
            DBInstanceIdentifier=instance_id,
            SkipFinalSnapshot=True,
            DeleteAutomatedBackups=True,
        )
    except ClientError as err:
        if err.response["Error"]["Code"] != "DBInstanceNotFound":
            raise
    logger.info("Deleted temporary instance %s", instance_id)


def cleanup_stragglers(rds, prefix, min_age_seconds, now):
    """Delete temporary instances left behind by earlier runs.

    A run whose teardown failed (or was cut short) leaves its instance behind, so
    every run starts by sweeping up whatever a previous run could not. Instances
    younger than min_age_seconds may belong to a run that is still in progress
    (e.g. a manual run overlapping the scheduled one), so they are left alone.
    """
    deleted = []
    for page in rds.get_paginator("describe_db_instances").paginate():
        for instance in page["DBInstances"]:
            instance_id = instance["DBInstanceIdentifier"]
            if not instance_id.startswith(prefix) or instance["DBInstanceStatus"] == "deleting":
                continue
            created = instance.get("InstanceCreateTime")  # absent while still 'creating'
            if created is None or (now - created).total_seconds() < min_age_seconds:
                logger.info("Leaving %s alone: it may belong to a run in progress", instance_id)
                continue
            try:
                delete_temp_instance(rds, instance_id, prefix)
                deleted.append(instance_id)
            except ClientError:
                # e.g. in a state that can't be deleted yet: leave it for the next run.
                logger.warning("Could not delete straggler %s yet", instance_id, exc_info=True)
    return deleted
