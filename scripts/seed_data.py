"""Load demo customers and orders into the deployed tables. Safe to re-run (items are overwritten).

Usage: uv run python scripts/seed_data.py
"""

import json
from decimal import Decimal
from pathlib import Path

import boto3

from stack_outputs import REGION, get_stack_outputs

SEED_FILE = Path(__file__).resolve().parents[1] / "backend" / "seed" / "seed_data.json"


def main() -> None:
    seed = json.loads(SEED_FILE.read_text(encoding="utf-8"), parse_float=Decimal)
    outputs = get_stack_outputs()
    dynamodb = boto3.resource("dynamodb", region_name=REGION)

    for key, output in (("customers", "CustomersTableName"), ("orders", "OrdersTableName")):
        table = dynamodb.Table(outputs[output])
        with table.batch_writer() as batch:
            for item in seed[key]:
                batch.put_item(Item=item)
        print(f"Wrote {len(seed[key])} {key} to {table.name}")


if __name__ == "__main__":
    main()
