from aws_clients import get_client
from config import LOCALSTACK_DEFAULT_ENDPOINT, load_settings


def test_dev_client_points_at_localstack(base_env):
    base_env["RESTORECHECK_DEV"] = "true"

    client = get_client("rds", load_settings(base_env))

    assert client.meta.endpoint_url == LOCALSTACK_DEFAULT_ENDPOINT


def test_prod_client_points_at_aws(base_env, monkeypatch):
    # boto3 itself honours AWS_ENDPOINT_URL, so make sure the shell's value can't leak in.
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)

    client = get_client("rds", load_settings(base_env))

    assert client.meta.endpoint_url == "https://rds.us-east-1.amazonaws.com"
