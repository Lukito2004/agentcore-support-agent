import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from approval import handler as approval_handler
from common import dynamo, workflow

SEED_FILE = Path(__file__).resolve().parents[2] / "backend" / "seed" / "seed_data.json"
STATE_MACHINE = "test-refund-review"
TABLES = {
    "CUSTOMERS_TABLE": ("test-customers", "customer_id"),
    "ORDERS_TABLE": ("test-orders", "order_id"),
    "REFUNDS_TABLE": ("test-refunds", "idempotency_key"),
}


def _clear_clients() -> None:
    dynamo.clear_caches()
    workflow.client.cache_clear()
    approval_handler._sns.cache_clear()


@pytest.fixture(autouse=True)
def fresh_clients():
    """Drop cached boto3 clients so each test talks to its own moto sandbox."""
    _clear_clients()
    yield
    _clear_clients()


@pytest.fixture
def aws(monkeypatch):
    """Fake AWS credentials, region and table names, inside a moto sandbox."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for env_var, (name, _key) in TABLES.items():
        monkeypatch.setenv(env_var, name)
    with mock_aws():
        yield


@pytest.fixture
def review_workflow(aws, monkeypatch):
    """An empty Step Functions state machine; tests check which reviews were started."""
    sfn = boto3.client("stepfunctions")
    arn = sfn.create_state_machine(
        name=STATE_MACHINE,
        definition=json.dumps({"StartAt": "Done", "States": {"Done": {"Type": "Succeed"}}}),
        roleArn="arn:aws:iam::123456789012:role/test-review",
    )["stateMachineArn"]
    monkeypatch.setenv("STATE_MACHINE_ARN", arn)
    return lambda: sfn.list_executions(stateMachineArn=arn)["executions"]


@pytest.fixture
def seeded_tables(aws, review_workflow):
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"), parse_float=Decimal)
    dynamodb = boto3.resource("dynamodb")
    for name, key in TABLES.values():
        dynamodb.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
    for env_var, items in (
        ("CUSTOMERS_TABLE", seed["customers"]),
        ("ORDERS_TABLE", seed["orders"]),
    ):
        table = dynamodb.Table(TABLES[env_var][0])
        for item in items:
            table.put_item(Item=item)
    return seed


@pytest.fixture
def table(seeded_tables):
    """Return the moto table behind an env var name, e.g. table("REFUNDS_TABLE")."""
    return lambda env_var: boto3.resource("dynamodb").Table(TABLES[env_var][0])


@pytest.fixture
def lambda_context():
    """Build a fake Lambda context carrying the Gateway's tool name."""

    def build(tool_name: str):
        return SimpleNamespace(
            aws_request_id="test-request",
            client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name}),
        )

    return build
