"""Start a RestoreCheck verification run now and wait for its result.

    python scripts/run_pipeline.py --dev                          # LocalStack
    python scripts/run_pipeline.py --aws                          # your AWS account
    python scripts/run_pipeline.py --aws --source-db ghost-db     # demo: a DB with no backups

A run is a Step Functions execution, exactly like the scheduled ones, so it also
appears (with its step-by-step diagram) in the Step Functions console.
"""
import argparse
import json
import sys
import time

import boto3

LOCALSTACK_ENDPOINT = "http://localhost:4566"
POLL_SECONDS = 15


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--dev", action="store_true", help="run against LocalStack")
    target.add_argument("--aws", action="store_true", help="run against real AWS")
    parser.add_argument("--stack-name", help="default: restorecheck-dev (--dev) / restorecheck (--aws)")
    parser.add_argument("--source-db", help="verify this RDS instance instead of the configured one")
    parser.add_argument("--profile", help="AWS CLI profile to use (--aws only)")
    parser.add_argument("--region", default=None, help="AWS region (default: from your profile)")
    return parser.parse_args()


def make_session(args):
    if args.dev:
        return boto3.Session(
            aws_access_key_id="test",  # LocalStack accepts anything; not a secret
            aws_secret_access_key="test",
            region_name=args.region or "us-east-1",
        ), {"endpoint_url": LOCALSTACK_ENDPOINT}
    return boto3.Session(profile_name=args.profile, region_name=args.region), {}


def stack_output(cloudformation, stack_name, key):
    stack = cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]
    for output in stack.get("Outputs", []):
        if output["OutputKey"] == key:
            return output["OutputValue"]
    sys.exit(f"Stack {stack_name} has no output {key}. Is it deployed?")


def record_result(sfn, execution_arn):
    """The RecordResult step's return value, read from the execution history
    (a run that ends in the red 'BackupNotVerified' state has no output)."""
    history = sfn.get_execution_history(executionArn=execution_arn, reverseOrder=True)
    for event in history["events"]:
        output = (event.get("lambdaFunctionSucceededEventDetails") or {}).get("output")
        if output and '"report_key"' in output:
            return json.loads(output)
    return None


def start_and_wait(session, stack_name, source_db=None, endpoint=None, on_started=None):
    """Start one verification run and block until it ends.

    Returns (execution status, RecordResult output or None, execution ARN)."""
    endpoint = endpoint or {}
    state_machine_arn = stack_output(
        session.client("cloudformation", **endpoint), stack_name, "StateMachineArn"
    )
    sfn = session.client("stepfunctions", **endpoint)

    execution_input = {"trigger": "manual"}
    if source_db:
        execution_input["source_db_id"] = source_db
    execution_arn = sfn.start_execution(
        stateMachineArn=state_machine_arn, input=json.dumps(execution_input)
    )["executionArn"]
    if on_started:
        on_started(execution_arn)

    started = time.monotonic()
    while True:
        status = sfn.describe_execution(executionArn=execution_arn)["status"]
        if status != "RUNNING":
            break
        print(f"  {status}  {int(time.monotonic() - started)}s elapsed", flush=True)
        time.sleep(POLL_SECONDS)
    return status, record_result(sfn, execution_arn), execution_arn


def main():
    args = parse_args()
    session, endpoint = make_session(args)
    stack_name = args.stack_name or ("restorecheck-dev" if args.dev else "restorecheck")

    def announce(execution_arn):
        print(f"Started {execution_arn}", flush=True)
        if args.aws:
            print(
                "Watch it live: https://console.aws.amazon.com/states/home"
                f"?region={session.region_name}#/v2/executions/details/{execution_arn}",
                flush=True,
            )

    status, result, _ = start_and_wait(
        session, stack_name, args.source_db, endpoint, on_started=announce
    )
    print(f"\nExecution {status}")
    if result is None:
        sys.exit("No result was recorded - check the execution in the Step Functions console.")
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
