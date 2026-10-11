import pytest


@pytest.fixture
def base_env():
    """The environment variables template.yaml gives the Lambda (prod flavour)."""
    return {
        "RESTORECHECK_DEV": "false",
        "SOURCE_DB_INSTANCE_ID": "orders-db",
        "TEMP_INSTANCE_PREFIX": "restorecheck-tmp-",
        "TEMP_INSTANCE_CLASS": "db.t3.micro",
        "RESULTS_TABLE": "results-table",
        "REPORTS_BUCKET": "reports-bucket",
        "ALERT_TOPIC_ARN": "arn:aws:sns:us-east-1:000000000000:alerts",
        "METRIC_NAMESPACE": "RestoreCheck",
        "AWS_REGION": "us-east-1",
    }
