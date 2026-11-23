import os
from functools import cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from common.errors import from_aws_error

# boto3 retries throttling and 5xx with exponential backoff before a call fails.
RETRY_CONFIG = Config(
    retries={"mode": "standard", "max_attempts": 3}, connect_timeout=2, read_timeout=5
)


@cache
def client():
    return boto3.client("dynamodb", config=RETRY_CONFIG)


@cache
def table(env_var: str):
    return boto3.resource("dynamodb", config=RETRY_CONFIG).Table(os.environ[env_var])


def get_item(env_var: str, key: dict) -> dict | None:
    """Strongly consistent read, so a refund always sees the latest order state."""
    try:
        return table(env_var).get_item(Key=key, ConsistentRead=True).get("Item")
    except (ClientError, BotoCoreError) as exc:
        raise from_aws_error(exc) from exc


def clear_caches() -> None:
    client.cache_clear()
    table.cache_clear()
