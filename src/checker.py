"""Checker Lambda: connects to the restored database and runs the integrity checks.

This is the only function inside the VPC, and it makes no AWS API calls at all:
the IAM login token is computed locally from the function's own credentials. So
the VPC needs no NAT gateway or VPC endpoints (no extra cost).

Event shape (from the state machine): {"run": {...}, "restore": {...}}
"""
import json
import logging
import os
import ssl
from dataclasses import asdict, replace
from pathlib import Path

import boto3

from checks import PRE_CONNECT_CHECKS, SQL_CHECKS
from checks.base import CheckResult, RestoreTarget, run_checks

logger = logging.getLogger()
logger.setLevel(logging.INFO)

HERE = Path(__file__).resolve().parent
EXPECTATIONS_FILE = HERE / "checks" / "expectations.json"
# Amazon's public CA bundle for RDS; needed to verify the database's TLS certificate.
# Source: https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
# (docs: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html)
CA_BUNDLE_FILE = HERE / "certs" / "rds-global-bundle.pem"
CONNECT_TIMEOUT_SECONDS = 15


def lambda_handler(event, context):
    return run(event, connect=connect_with_iam_token)


def load_expectations(path=EXPECTATIONS_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(event, connect, expectations=None):
    target = RestoreTarget(
        snapshot=event["run"]["snapshot"],
        instance=event["restore"]["instance"],
        expectations=expectations if expectations is not None else load_expectations(),
    )
    results = run_checks(PRE_CONNECT_CHECKS, target)

    try:
        db = connect(target.instance)
    except Exception as err:
        logger.exception("Could not connect to the restored database")
        results.append(CheckResult("connect", False, f"could not connect: {type(err).__name__}: {err}"))
        return _response(results)

    try:
        results.append(CheckResult("connect", True, "logged in with an IAM auth token over TLS"))
        results.extend(run_checks(SQL_CHECKS, replace(target, db=db)))
    finally:
        db.close()
    return _response(results)


def _response(results):
    for r in results:
        logger.info("check %s: %s - %s", r.name, "PASS" if r.passed else "FAIL", r.detail)
    return {"results": [asdict(r) for r in results]}


def connect_with_iam_token(instance):
    import pg8000.dbapi  # imported here so the unit tests don't need the driver

    host = instance["Endpoint"]["Address"]
    port = instance["Endpoint"]["Port"]
    region = os.environ["AWS_REGION"]
    user = os.environ["DB_USER"]

    # A 15-minute password, signed with this function's IAM role. Computed
    # locally (no network call); RDS checks it against the rds-db:connect policy.
    token = boto3.client("rds", region_name=region).generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername=user, Region=region
    )
    db = pg8000.dbapi.connect(
        user=user,
        password=token,
        host=host,
        port=port,
        database=os.environ["DB_NAME"],
        ssl_context=ssl.create_default_context(cafile=str(CA_BUNDLE_FILE)),
        timeout=CONNECT_TIMEOUT_SECONDS,
    )
    # One failed query must not abort the transaction for the checks that follow.
    db.autocommit = True
    return db
