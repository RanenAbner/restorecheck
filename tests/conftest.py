import json
import re
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from aws_clients import get_client
from config import load_settings

REGION = "us-east-1"
SOURCE_DB = "orders-db"


@pytest.fixture
def base_env():
    """The environment variables template.yaml gives the Lambda (prod flavour)."""
    return {
        "RESTORECHECK_DEV": "false",
        "SOURCE_DB_INSTANCE_ID": SOURCE_DB,
        "TEMP_INSTANCE_PREFIX": "restorecheck-tmp-",
        "TEMP_INSTANCE_CLASS": "db.t3.micro",
        "RESULTS_TABLE": "results-table",
        "REPORTS_BUCKET": "reports-bucket",
        "ALERT_TOPIC_ARN": "arn:aws:sns:us-east-1:000000000000:alerts",
        "METRIC_NAMESPACE": "RestoreCheck",
        "AWS_REGION": REGION,
    }


@pytest.fixture
def fake_aws(monkeypatch, base_env):
    """A moto-faked AWS account holding the stack's resources and one source database.

    moto intercepts boto3 calls in-process, so nothing leaves this machine.
    """
    for name in ("AWS_ENDPOINT_URL", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)

    with mock_aws():
        rds = boto3.client("rds", region_name=REGION)
        ec2 = boto3.client("ec2", region_name=REGION)
        dynamodb = boto3.client("dynamodb", region_name=REGION)
        s3 = boto3.client("s3", region_name=REGION)
        sns = boto3.client("sns", region_name=REGION)
        sqs = boto3.client("sqs", region_name=REGION)

        dynamodb.create_table(
            TableName="results-table",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "source_db_id", "AttributeType": "S"},
                {"AttributeName": "run_timestamp", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "source_db_id", "KeyType": "HASH"},
                {"AttributeName": "run_timestamp", "KeyType": "RANGE"},
            ],
        )
        s3.create_bucket(Bucket="reports-bucket")

        # Subscribe a queue to the alert topic so tests can read what was "emailed".
        topic_arn = sns.create_topic(Name="alerts")["TopicArn"]
        queue_url = sqs.create_queue(QueueName="alert-inbox")["QueueUrl"]
        queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]
        sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)
        base_env["ALERT_TOPIC_ARN"] = topic_arn

        # The network the template creates: two subnets, a DB subnet group and the
        # security group temporary instances are placed in.
        vpc_id = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        subnet_ids = [
            ec2.create_subnet(VpcId=vpc_id, CidrBlock=cidr, AvailabilityZone=az)["Subnet"]["SubnetId"]
            for cidr, az in (("10.0.1.0/24", "us-east-1a"), ("10.0.2.0/24", "us-east-1b"))
        ]
        rds.create_db_subnet_group(
            DBSubnetGroupName="restorecheck-subnets",
            DBSubnetGroupDescription="test",
            SubnetIds=subnet_ids,
        )
        db_sg = ec2.create_security_group(
            GroupName="restored-db", Description="test", VpcId=vpc_id
        )["GroupId"]
        base_env["RESTORE_SUBNET_GROUP"] = "restorecheck-subnets"
        base_env["RESTORE_SECURITY_GROUP_ID"] = db_sg

        rds.create_db_instance(
            DBInstanceIdentifier=SOURCE_DB,
            Engine="postgres",
            DBInstanceClass="db.t3.micro",
            AllocatedStorage=20,
            MasterUsername="admin_user",
            MasterUserPassword="not-a-real-password",
        )

        for name, value in base_env.items():
            monkeypatch.setenv(name, value)
        settings = load_settings(base_env)

        def alerts():
            messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get(
                "Messages", []
            )
            return [json.loads(m["Body"]) for m in messages]

        def instance_ids():
            return sorted(
                i["DBInstanceIdentifier"] for i in rds.describe_db_instances()["DBInstances"]
            )

        yield SimpleNamespace(
            settings=settings,
            clients={
                name: get_client(name, settings)
                for name in ("rds", "dynamodb", "s3", "sns", "cloudwatch")
            },
            rds=rds,
            dynamodb=dynamodb,
            s3=s3,
            alerts=alerts,
            instance_ids=instance_ids,
            restored_db_security_group=db_sg,
        )


@pytest.fixture
def snapshot(fake_aws):
    fake_aws.rds.create_db_snapshot(
        DBInstanceIdentifier=SOURCE_DB, DBSnapshotIdentifier="orders-db-manual-1"
    )
    return "orders-db-manual-1"


class FakeDB:
    """A stand-in for a PostgreSQL connection that answers exactly the SQL the
    checks send, from in-memory tables. Lets the check logic be tested without
    a database server; the SQL itself is exercised for real on AWS."""

    def __init__(self, tables, query_results=None):
        self.tables = tables  # table name -> list of rows
        self.query_results = query_results or {}  # test-query SQL -> value or exception
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


class _FakeCursor:
    def __init__(self, db):
        self.db = db
        self.rows = None

    def execute(self, sql):
        from checks import canary, schema

        count = re.fullmatch(r'SELECT count\(\*\) FROM "(\w+)"', sql)
        if sql == schema.SQL:
            self.rows = [(name,) for name in self.db.tables]
        elif sql == canary.SQL:
            rows = self._table(canary.TABLE)
            self.rows = [(canary.expected_checksum(rows) if rows else None,)]
        elif count:
            self.rows = [(len(self._table(count.group(1))),)]
        elif sql in self.db.query_results:
            value = self.db.query_results[sql]
            if isinstance(value, Exception):
                raise value
            self.rows = [(value,)]
        else:
            raise AssertionError(f"FakeDB got unexpected SQL: {sql}")

    def _table(self, name):
        if name not in self.db.tables:
            raise RuntimeError(f'relation "{name}" does not exist')
        return self.db.tables[name]

    def fetchall(self):
        return self.rows

    def close(self):
        pass


@pytest.fixture
def expectations():
    from checker import load_expectations

    return load_expectations()


@pytest.fixture
def healthy_db(expectations):
    """A database that satisfies expectations.json exactly."""
    from checks import canary

    tables = {name: [()] * min_rows for name, min_rows in expectations["tables"].items()}
    tables[canary.TABLE] = list(canary.ROWS)
    return FakeDB(tables, {q["sql"]: True for q in expectations["queries"]})
