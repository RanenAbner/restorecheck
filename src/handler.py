"""RestoreCheck Lambda entry point.

Skeleton only: the restore -> check -> record -> teardown pipeline is build step 2.
"""
import logging

from config import load_settings

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    settings = load_settings()
    logger.info(
        "RestoreCheck invoked: mode=%s endpoint=%s source_db=%s",
        "dev" if settings.dev_mode else "aws",
        settings.endpoint_url or "aws-default",
        settings.source_db_instance_id,
    )
    return {
        "status": "NOT_IMPLEMENTED",
        "dev_mode": settings.dev_mode,
        "source_db_instance_id": settings.source_db_instance_id,
    }
