from datetime import datetime, timedelta, timezone

import pytest

import restore


def snap(name, day, status="available"):
    return {
        "DBSnapshotIdentifier": name,
        "Status": status,
        "SnapshotCreateTime": datetime(2026, 10, day, tzinfo=timezone.utc),
    }


def test_latest_available_picks_newest_ready_snapshot():
    snapshots = [snap("old", 1), snap("newest-but-creating", 3, "creating"), snap("new", 2)]

    assert restore.latest_available(snapshots)["DBSnapshotIdentifier"] == "new"


def test_latest_available_with_nothing_ready():
    assert restore.latest_available([snap("x", 1, "creating")]) is None


def test_temp_instance_id_is_predictable():
    run_time = datetime(2026, 10, 16, 2, 0, 0, tzinfo=timezone.utc)

    assert restore.temp_instance_id("restorecheck-tmp-", run_time) == (
        "restorecheck-tmp-20261016020000"
    )


def test_delete_refuses_non_temp_instances():
    with pytest.raises(ValueError, match="Refusing to delete orders-db"):
        restore.delete_temp_instance(rds=None, instance_id="orders-db", prefix="restorecheck-tmp-")


def test_delete_of_already_deleted_instance_is_fine(fake_aws):
    restore.delete_temp_instance(fake_aws.rds, "restorecheck-tmp-gone", "restorecheck-tmp-")


def later(**delta):
    # moto stamps instances with the real current time.
    return datetime.now(timezone.utc) + timedelta(**delta)


def test_cleanup_never_touches_the_source_database(fake_aws):
    swept = restore.cleanup_stragglers(fake_aws.rds, "restorecheck-tmp-", 0, later(days=1))

    assert swept == []
    assert fake_aws.instance_ids() == ["orders-db"]


def test_cleanup_spares_instances_young_enough_to_be_in_use(fake_aws, snapshot):
    fake_aws.rds.restore_db_instance_from_db_snapshot(
        DBInstanceIdentifier="restorecheck-tmp-other-run", DBSnapshotIdentifier=snapshot
    )
    one_hour = 3600

    # 10 minutes later another run may still be using it...
    assert restore.cleanup_stragglers(fake_aws.rds, "restorecheck-tmp-", one_hour, later(minutes=10)) == []
    # ...2 hours later it is certainly abandoned.
    assert restore.cleanup_stragglers(fake_aws.rds, "restorecheck-tmp-", one_hour, later(hours=2)) == [
        "restorecheck-tmp-other-run"
    ]
