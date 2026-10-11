"""Single place where boto3 clients are created, so dev mode cannot be bypassed."""
import boto3

# LocalStack accepts any credentials; "test" is its documented convention.
# These are not secrets and are never used outside dev mode.
_LOCALSTACK_DUMMY_KEY = "test"


def get_client(service, settings):
    """Return a boto3 client for `service`, pointed at LocalStack in dev mode."""
    kwargs = {}
    if settings.region:
        kwargs["region_name"] = settings.region
    if settings.dev_mode:
        kwargs.update(
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=_LOCALSTACK_DUMMY_KEY,
            aws_secret_access_key=_LOCALSTACK_DUMMY_KEY,
        )
    return boto3.client(service, **kwargs)
