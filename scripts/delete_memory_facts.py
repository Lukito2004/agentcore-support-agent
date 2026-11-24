"""Delete leftover long-term "facts" records (stale copies of orders, refunds and emails).

The SEMANTIC strategy that wrote them is gone; this removes what it already stored.
Lists what it would delete first and only deletes with --yes.

Usage: uv run python scripts/delete_memory_facts.py [--yes]
"""

import argparse

import boto3

from stack_outputs import REGION

MEMORY_NAME_PART = "supportMemory"
BATCH_SIZE = 50


def _memory_id(control) -> str:
    for memory in control.list_memories()["memories"]:
        if MEMORY_NAME_PART in memory["id"]:
            return memory["id"]
    raise SystemExit("supportMemory not found")


def _pages(call, key: str, **kwargs):
    token = None
    while True:
        page = call(**kwargs, **({"nextToken": token} if token else {}))
        yield from page.get(key, [])
        token = page.get("nextToken")
        if not token:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="actually delete")
    args = parser.parse_args()

    memory_id = _memory_id(boto3.client("bedrock-agentcore-control", region_name=REGION))
    data = boto3.client("bedrock-agentcore", region_name=REGION)

    records = []
    for actor in _pages(data.list_actors, "actorSummaries", memoryId=memory_id):
        namespace = f"/users/{actor['actorId']}/facts"
        for record in _pages(
            data.list_memory_records,
            "memoryRecordSummaries",
            memoryId=memory_id,
            namespace=namespace,
        ):
            records.append(record["memoryRecordId"])
    print(f"Found {len(records)} facts records in {memory_id}")

    if not args.yes:
        print("Dry run. Re-run with --yes to delete them.")
        return
    for start in range(0, len(records), BATCH_SIZE):
        batch = [{"memoryRecordId": rid} for rid in records[start : start + BATCH_SIZE]]
        data.batch_delete_memory_records(memoryId=memory_id, records=batch)
    print(f"Deleted {len(records)} records")


if __name__ == "__main__":
    main()
