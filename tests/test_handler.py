import handler


def test_skeleton_handler_reports_mode(base_env, monkeypatch):
    base_env["RESTORECHECK_DEV"] = "true"
    for name, value in base_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)

    result = handler.lambda_handler({}, None)

    assert result == {
        "status": "NOT_IMPLEMENTED",
        "dev_mode": True,
        "source_db_instance_id": "orders-db",
    }
