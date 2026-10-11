"""Runtime settings, read from environment variables set in template.yaml.

Dev mode (RESTORECHECK_DEV=true) pins every AWS call to a LocalStack endpoint so
nothing can reach real AWS during development.
"""
import os
from dataclasses import dataclass
from urllib.parse import urlparse

LOCALSTACK_DEFAULT_ENDPOINT = "http://localhost:4566"
DEV_DEFAULT_REGION = "us-east-1"

_TRUTHY = {"1", "true", "yes", "on"}


class ConfigError(RuntimeError):
    """Raised when the environment is missing or has unsafe configuration."""


@dataclass(frozen=True)
class Settings:
    dev_mode: bool
    endpoint_url: str | None  # None = boto3's default (real AWS) endpoints
    region: str | None  # None = let boto3 resolve it (Lambda sets AWS_REGION)
    source_db_instance_id: str
    temp_instance_prefix: str
    temp_instance_class: str
    results_table: str
    reports_bucket: str
    alert_topic_arn: str
    metric_namespace: str


def _required(env, name):
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _dev_endpoint(env):
    # When LocalStack itself runs the Lambda it injects AWS_ENDPOINT_URL, because
    # "localhost" inside the function's container is not the LocalStack container.
    endpoint = env.get("AWS_ENDPOINT_URL", "").strip() or LOCALSTACK_DEFAULT_ENDPOINT
    host = urlparse(endpoint).hostname or ""
    if host == "amazonaws.com" or host.endswith(".amazonaws.com"):
        raise ConfigError(
            f"Dev mode is on but the endpoint is real AWS ({endpoint}). Refusing to continue."
        )
    return endpoint


def load_settings(env=None):
    env = os.environ if env is None else env
    dev_mode = env.get("RESTORECHECK_DEV", "").strip().lower() in _TRUTHY
    region = env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION")

    return Settings(
        dev_mode=dev_mode,
        endpoint_url=_dev_endpoint(env) if dev_mode else None,
        region=region or (DEV_DEFAULT_REGION if dev_mode else None),
        source_db_instance_id=_required(env, "SOURCE_DB_INSTANCE_ID"),
        temp_instance_prefix=env.get("TEMP_INSTANCE_PREFIX", "restorecheck-tmp-"),
        temp_instance_class=env.get("TEMP_INSTANCE_CLASS", "db.t3.micro"),
        results_table=_required(env, "RESULTS_TABLE"),
        reports_bucket=_required(env, "REPORTS_BUCKET"),
        alert_topic_arn=_required(env, "ALERT_TOPIC_ARN"),
        metric_namespace=env.get("METRIC_NAMESPACE", "RestoreCheck"),
    )
