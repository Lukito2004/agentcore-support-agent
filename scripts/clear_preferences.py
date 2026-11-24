"""Delete one customer's remembered preferences, so a memory test starts from nothing.

Usage: uv run python scripts/clear_preferences.py --email alex.morgan@example.com [--yes]
Lists what it would delete first and only deletes with --yes.
"""

import argparse

import boto3

from delete_memory_facts import BATCH_SIZE, _memory_id, _pages
from stack_outputs import REGION, get_stack_outputs


def actor_id(email: str) -> str:
    """The memory actor is the Cognito user's sub, the same ID the agent reads from the token."""
    user = boto3.client("cognito-idp", region_name=REGION).admin_get_user(
        UserPoolId=get_stack_outputs()["UserPoolId"], Username=email
    )
    return next(a["Value"] for a in user["UserAttributes"] if a["Name"] == "sub")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--yes", action="store_true", help="actually delete")
    args = parser.parse_args()

    memory_id = _memory_id(boto3.client("bedrock-agentcore-control", region_name=REGION))
    data = boto3.client("bedrock-agentcore", region_name=REGION)
    namespace = f"/users/{actor_id(args.email)}/preferences"
    records = [
        record["memoryRecordId"]
        for record in _pages(
            data.list_memory_records,
            "memoryRecordSummaries",
            memoryId=memory_id,
            namespace=namespace,
        )
    ]
    print(f"Found {len(records)} preference records for {args.email}")
    if not args.yes:
        print("Dry run. Re-run with --yes to delete them.")
        return
    for start in range(0, len(records), BATCH_SIZE):
        batch = [{"memoryRecordId": rid} for rid in records[start : start + BATCH_SIZE]]
        data.batch_delete_memory_records(memoryId=memory_id, records=batch)
    print(f"Deleted {len(records)} records")


if __name__ == "__main__":
    main()
