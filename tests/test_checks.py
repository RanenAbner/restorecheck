import pytest

from checks import SQL_CHECKS, canary
from checks.base import CheckResult, RestoreTarget, quote_identifier, run_checks
from checks.instance_status import check_instance_available

SNAPSHOT = {"DBSnapshotIdentifier": "snap-1", "Engine": "postgres"}
INSTANCE = {
    "DBInstanceIdentifier": "restorecheck-tmp-1",
    "DBInstanceStatus": "available",
    "Engine": "postgres",
    "EngineVersion": "16.4",
    "Endpoint": {"Address": "tmp.example.internal", "Port": 5432},
}


def results_for(db, expectations):
    target = RestoreTarget(SNAPSHOT, INSTANCE, db=db, expectations=expectations)
    return {r.name: r for r in run_checks(SQL_CHECKS, target)}


def test_healthy_database_passes_every_check(healthy_db, expectations):
    results = results_for(healthy_db, expectations)

    assert set(results) == {"tables_present", "row_counts", "canary_checksum", "test_queries"}
    assert all(r.passed for r in results.values()), results


def test_missing_table_is_named(healthy_db, expectations):
    del healthy_db.tables["order_items"]

    results = results_for(healthy_db, expectations)

    assert not results["tables_present"].passed
    assert results["tables_present"].detail == "missing tables: order_items"
    assert "order_items: could not count" in results["row_counts"].detail


def test_truncated_table_fails_row_counts(healthy_db, expectations):
    healthy_db.tables["orders"] = healthy_db.tables["orders"][:10]

    result = results_for(healthy_db, expectations)["row_counts"]

    assert not result.passed
    assert result.detail == "orders has 10 rows, expected at least 200"


def test_altered_canary_row_fails_checksum(healthy_db, expectations):
    healthy_db.tables[canary.TABLE][41] = (42, "tampered")

    result = results_for(healthy_db, expectations)["canary_checksum"]

    assert not result.passed
    assert "does not match" in result.detail


def test_empty_canary_table_fails_checksum(healthy_db, expectations):
    healthy_db.tables[canary.TABLE] = []

    result = results_for(healthy_db, expectations)["canary_checksum"]

    assert (result.passed, result.detail) == (False, "restorecheck_canary is empty")


def test_false_and_broken_test_queries_are_both_reported(healthy_db, expectations):
    first, second = expectations["queries"][:2]
    healthy_db.query_results[first["sql"]] = False
    healthy_db.query_results[second["sql"]] = RuntimeError("syntax error")

    result = results_for(healthy_db, expectations)["test_queries"]

    assert not result.passed
    assert f"{first['name']}: returned False" in result.detail
    assert f"{second['name']}: query failed" in result.detail


def test_canary_checksum_matches_postgres_serialisation():
    # What PostgreSQL computes for: md5(string_agg(id::text || ':' || payload, ',' ORDER BY id))
    rows = [(1, "a"), (2, "b")]
    import hashlib

    assert canary.expected_checksum(rows) == hashlib.md5(b"1:a,2:b").hexdigest()


def test_expectations_file_is_consistent(expectations):
    for table in expectations["tables"]:
        quote_identifier(table)  # raises if a name could not be safely used in SQL
    assert expectations["tables"][canary.TABLE] == len(canary.ROWS)
    assert all({"name", "sql"} <= set(q) for q in expectations["queries"])


@pytest.mark.parametrize("name", ['orders"; DROP TABLE x; --', "Orders", "1table", ""])
def test_quote_identifier_rejects_unsafe_names(name):
    with pytest.raises(ValueError):
        quote_identifier(name)


def test_instance_check_catches_engine_mismatch():
    target = RestoreTarget(SNAPSHOT, dict(INSTANCE, Engine="mysql"))

    result = check_instance_available(target)

    assert not result.passed
    assert "engine is 'mysql' but snapshot is 'postgres'" in result.detail


def test_crashing_check_counts_as_failed():
    def crashing_check(target):
        raise ConnectionError("lost connection")

    (result,) = run_checks([crashing_check], RestoreTarget(SNAPSHOT, INSTANCE))

    assert result == CheckResult(
        "crashing_check", False, "check raised ConnectionError: lost connection"
    )


def test_database_errors_are_reduced_to_the_server_message():
    from checks.base import describe_db_error

    driver_error = RuntimeError(
        {"S": "ERROR", "C": "42P01", "M": 'relation "order_items" does not exist', "F": "parse_relation.c"}
    )

    assert describe_db_error(driver_error) == 'relation "order_items" does not exist [42P01]'
    assert describe_db_error(TimeoutError("timed out")) == "TimeoutError: timed out"
