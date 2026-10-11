import pytest

from config import LOCALSTACK_DEFAULT_ENDPOINT, ConfigError, load_settings


def test_prod_mode_uses_default_aws_endpoints(base_env):
    settings = load_settings(base_env)

    assert settings.dev_mode is False
    assert settings.endpoint_url is None
    assert settings.source_db_instance_id == "orders-db"


def test_prod_mode_ignores_endpoint_override(base_env):
    base_env["AWS_ENDPOINT_URL"] = "http://localhost:4566"

    assert load_settings(base_env).endpoint_url is None


@pytest.mark.parametrize("flag", ["true", "TRUE", "1", "yes"])
def test_dev_mode_targets_localstack(base_env, flag):
    base_env["RESTORECHECK_DEV"] = flag

    settings = load_settings(base_env)

    assert settings.dev_mode is True
    assert settings.endpoint_url == LOCALSTACK_DEFAULT_ENDPOINT


def test_dev_mode_honours_endpoint_injected_by_localstack(base_env):
    base_env["RESTORECHECK_DEV"] = "true"
    base_env["AWS_ENDPOINT_URL"] = "http://172.17.0.2:4566"

    assert load_settings(base_env).endpoint_url == "http://172.17.0.2:4566"


def test_dev_mode_refuses_real_aws_endpoint(base_env):
    base_env["RESTORECHECK_DEV"] = "true"
    base_env["AWS_ENDPOINT_URL"] = "https://rds.us-east-1.amazonaws.com"

    with pytest.raises(ConfigError, match="real AWS"):
        load_settings(base_env)


def test_dev_mode_defaults_region_when_unset(base_env):
    base_env["RESTORECHECK_DEV"] = "true"
    del base_env["AWS_REGION"]

    assert load_settings(base_env).region == "us-east-1"


def test_missing_required_variable_is_reported_by_name(base_env):
    del base_env["RESULTS_TABLE"]

    with pytest.raises(ConfigError, match="RESULTS_TABLE"):
        load_settings(base_env)
