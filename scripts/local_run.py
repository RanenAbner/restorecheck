"""Run the Lambda handler on this machine against LocalStack.

    python scripts/local_run.py --dev

The handler runs as a normal Python process (so you can use a debugger), with the
same environment variables the deployed dev function has, read back from LocalStack.
--dev is mandatory: there is deliberately no way to point this script at real AWS.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config import LOCALSTACK_DEFAULT_ENDPOINT  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dev", action="store_true", help="target LocalStack (required)")
    parser.add_argument("--stack-name", default="restorecheck-dev")
    parser.add_argument("--event", type=Path, default=ROOT / "events" / "scheduled.json")
    return parser.parse_args()


def check_localstack(endpoint):
    try:
        urllib.request.urlopen(f"{endpoint}/_localstack/health", timeout=3)
    except (urllib.error.URLError, OSError):
        sys.exit(f"LocalStack is not reachable at {endpoint}. Start it with: docker compose up -d")


def deployed_environment(endpoint, function_name):
    client = boto3.client(
        "lambda",
        endpoint_url=endpoint,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    try:
        config = client.get_function_configuration(FunctionName=function_name)
    except ClientError as err:
        if err.response["Error"]["Code"] == "ResourceNotFoundException":
            sys.exit(
                f"Function {function_name} is not deployed in LocalStack. "
                "Run: .\\scripts\\deploy_local.ps1"
            )
        raise
    return config["Environment"]["Variables"]


def main():
    args = parse_args()
    if not args.dev:
        sys.exit("Refusing to run without --dev: this script only targets LocalStack.")

    endpoint = os.environ.get("AWS_ENDPOINT_URL") or LOCALSTACK_DEFAULT_ENDPOINT
    check_localstack(endpoint)

    os.environ.update(deployed_environment(endpoint, f"{args.stack_name}-verifier"))
    os.environ["RESTORECHECK_DEV"] = "true"
    os.environ["AWS_ENDPOINT_URL"] = endpoint

    from handler import lambda_handler

    result = lambda_handler(json.loads(args.event.read_text()), None)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
