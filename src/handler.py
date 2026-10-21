"""Verifier Lambda: runs one pipeline step per invocation, as Step Functions asks.

Event shape (built by statemachine/restorecheck.asl.json):
    {"action": "prepare" | "poll" | "teardown" | "record",
     "state": {...the execution's state so far...},
     "execution_start": "2026-10-16T02:00:00.000Z"}
"""
import logging

import pipeline
from aws_clients import get_client
from config import load_settings

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_RECORD_SERVICES = ("dynamodb", "s3", "sns", "cloudwatch")


def lambda_handler(event, context):
    settings = load_settings()
    action = event.get("action")
    state = event.get("state") or {}
    now = pipeline.parse_time(event.get("execution_start"))
    logger.info(
        "RestoreCheck step=%s mode=%s", action, "dev" if settings.dev_mode else "aws"
    )

    if action == "prepare":
        return pipeline.prepare(settings, get_client("rds", settings), state, now)
    if action == "poll":
        return pipeline.poll(settings, get_client("rds", settings), state)
    if action == "teardown":
        return pipeline.teardown(settings, get_client("rds", settings), state)
    if action == "record":
        clients = {name: get_client(name, settings) for name in _RECORD_SERVICES}
        return pipeline.record(settings, clients, state, now)
    raise ValueError(f"Unknown action: {action!r}")
