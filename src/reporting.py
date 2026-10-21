"""Recording a run: S3 report, DynamoDB history row, CloudWatch metrics, SNS alert."""
import json
from decimal import Decimal

from boto3.dynamodb.types import TypeSerializer

_serializer = TypeSerializer()


def report_key(source_db_id, run_timestamp):
    return f"reports/{source_db_id}/{run_timestamp}.json"


def write_report(s3, bucket, key, report):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(report, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )


def _to_dynamo(value):
    # DynamoDB has no float type; boto3 requires Decimal for non-integer numbers.
    return Decimal(str(value)) if isinstance(value, float) else value


def record_result(dynamodb, table, item):
    dynamodb.put_item(
        TableName=table,
        Item={k: _serializer.serialize(_to_dynamo(v)) for k, v in item.items() if v is not None},
    )


def publish_metrics(cloudwatch, namespace, report):
    dimensions = [{"Name": "SourceDbId", "Value": report["source_db_id"]}]
    data = [
        {
            "MetricName": "VerificationSucceeded",
            "Value": 1 if report["status"] == "PASSED" else 0,
            "Unit": "Count",
            "Dimensions": dimensions,
        }
    ]
    if report["restore_seconds"] is not None:
        data.append(
            {
                "MetricName": "RestoreDurationSeconds",
                "Value": report["restore_seconds"],
                "Unit": "Seconds",
                "Dimensions": dimensions,
            }
        )
    cloudwatch.put_metric_data(Namespace=namespace, MetricData=data)


def send_alert(sns, topic_arn, report, report_uri):
    failed = [c for c in report["checks"] if not c["passed"]]
    lines = [
        f"Status:            {report['status']}",
        f"Source database:   {report['source_db_id']}",
        f"Run at:            {report['run_timestamp']}",
        f"Snapshot:          {report['snapshot_id'] or '-'}",
        f"Temporary copy:    {report['temp_instance_id'] or '-'}",
        f"Teardown OK:       {report['teardown_ok']}",
    ]
    if report["error"]:
        lines.append(f"Error:             {report['error']}")
    for check in failed:
        lines.append(f"Failed check:      {check['name']} - {check['detail']}")
    lines.append(f"Full report:       {report_uri}")

    sns.publish(
        TopicArn=topic_arn,
        Subject=f"RestoreCheck {report['status']}: {report['source_db_id']}"[:100],
        Message="\n".join(lines),
    )
