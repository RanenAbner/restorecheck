import checker

EVENT = {
    "run": {
        "temp_instance_id": "restorecheck-tmp-20261016020000",
        "snapshot": {"DBSnapshotIdentifier": "snap-1", "Engine": "postgres"},
    },
    "restore": {
        "ready": True,
        "instance": {
            "DBInstanceIdentifier": "restorecheck-tmp-20261016020000",
            "DBInstanceStatus": "available",
            "Engine": "postgres",
            "EngineVersion": "16.4",
            "Endpoint": {"Address": "tmp.abc.us-east-1.rds.amazonaws.com", "Port": 5432},
        },
    },
}


def names_and_outcomes(response):
    return [(r["name"], r["passed"]) for r in response["results"]]


def test_healthy_restore_passes_all_checks_and_closes_connection(healthy_db):
    response = checker.run(EVENT, connect=lambda instance: healthy_db)

    assert names_and_outcomes(response) == [
        ("instance_available", True),
        ("connect", True),
        ("tables_present", True),
        ("row_counts", True),
        ("canary_checksum", True),
        ("test_queries", True),
    ]
    assert healthy_db.closed


def test_connection_failure_is_a_failed_check_not_a_crash():
    def refuse(instance):
        raise TimeoutError("timed out connecting")

    response = checker.run(EVENT, connect=refuse)

    assert names_and_outcomes(response) == [("instance_available", True), ("connect", False)]
    assert "TimeoutError: timed out connecting" in response["results"][1]["detail"]


def test_connection_is_closed_even_when_checks_fail(healthy_db):
    healthy_db.tables.clear()

    response = checker.run(EVENT, connect=lambda instance: healthy_db)

    assert not all(r["passed"] for r in response["results"])
    assert healthy_db.closed


def test_connects_with_iam_token_over_verified_tls(monkeypatch):
    import pg8000.dbapi

    captured = {}

    class FakeConnection:
        autocommit = False

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return FakeConnection()

    monkeypatch.setattr(pg8000.dbapi, "connect", fake_connect)
    monkeypatch.setattr(checker.ssl, "create_default_context", lambda cafile: ("tls", cafile))
    for name, value in {
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "DB_USER": "restorecheck_verifier",
        "DB_NAME": "appdb",
    }.items():
        monkeypatch.setenv(name, value)

    db = checker.connect_with_iam_token(EVENT["restore"]["instance"])

    assert db.autocommit is True
    assert captured["user"] == "restorecheck_verifier"
    assert captured["database"] == "appdb"
    assert captured["host"] == "tmp.abc.us-east-1.rds.amazonaws.com"
    # The password is a signed IAM auth token, not a stored secret.
    assert "Action=connect" in captured["password"]
    assert "DBUser=restorecheck_verifier" in captured["password"]
    assert captured["ssl_context"] == ("tls", str(checker.CA_BUNDLE_FILE))


def test_rds_ca_bundle_is_packaged_and_loads():
    # Without it the checker cannot verify the database's TLS certificate.
    import ssl

    context = ssl.create_default_context(cafile=str(checker.CA_BUNDLE_FILE))

    assert len(context.get_ca_certs()) > 0
