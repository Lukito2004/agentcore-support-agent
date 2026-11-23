import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

SEED_FILE = Path(__file__).resolve().parents[2] / "backend" / "seed" / "seed_data.json"
CUSTOMERS_TABLE = "test-customers"
ORDERS_TABLE = "test-orders"


@pytest.fixture
def aws(monkeypatch):
    """Fake AWS credentials, region and table names, inside a moto sandbox."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("CUSTOMERS_TABLE", CUSTOMERS_TABLE)
    monkeypatch.setenv("ORDERS_TABLE", ORDERS_TABLE)
    with mock_aws():
        yield


@pytest.fixture
def seeded_tables(aws):
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"), parse_float=Decimal)
    dynamodb = boto3.resource("dynamodb")
    for name, key, items in (
        (CUSTOMERS_TABLE, "customer_id", seed["customers"]),
        (ORDERS_TABLE, "order_id", seed["orders"]),
    ):
        table = dynamodb.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        for item in items:
            table.put_item(Item=item)
    return seed


@pytest.fixture
def lambda_context():
    """Build a fake Lambda context carrying the Gateway's tool name."""

    def build(tool_name: str):
        return SimpleNamespace(
            aws_request_id="test-request",
            client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name}),
        )

    return build
