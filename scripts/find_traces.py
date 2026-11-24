"""Print the traces of one agent session from CloudWatch, with failures and guard decisions marked.

Usage: uv run python scripts/find_traces.py SESSION_ID [--hours 6]
Spans reach CloudWatch a minute or two after a request.
"""

import argparse
import json
import sys
import time
from collections import defaultdict

import boto3

from stack_outputs import REGION, get_stack_outputs

AGENT_STACK = "AgentCore-SupportAgent-default"
RUNTIME_ID_OUTPUT_PREFIX = "ApplicationRuntimeSupportAgentRuntimeIdOutput"
# Spans that only add noise to a failure review, unless they failed.
HIDDEN_SPANS = ("Bedrock AgentCore.CreateEvent", "Bedrock AgentCore.ListEvents")


def runtime_log_group() -> str:
    outputs = get_stack_outputs(AGENT_STACK)
    runtime_id = next(v for k, v in outputs.items() if k.startswith(RUNTIME_ID_OUTPUT_PREFIX))
    return f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"


def query_spans(log_group: str, session_id: str, hours: float) -> list[dict]:
    logs = boto3.client("logs", region_name=REGION)
    # The session ID is passed as a JSON string literal, so it cannot change the query.
    query = (
        f"filter @logStream = 'spans' and attributes.session.id = {json.dumps(session_id)}"
        " | fields @message | limit 10000"
    )
    now = int(time.time())
    query_id = logs.start_query(
        logGroupName=log_group,
        startTime=now - int(hours * 3600),
        endTime=now,
        queryString=query,
    )["queryId"]
    while (result := logs.get_query_results(queryId=query_id))["status"] in (
        "Scheduled",
        "Running",
    ):
        time.sleep(1)
    return [
        json.loads(field["value"])
        for row in result["results"]
        for field in row
        if field["field"] == "@message"
    ]


def tool_error_code(span: dict) -> str | None:
    """The error code a tool returned, from the Strands tool span's gen_ai.choice event."""
    if not span.get("name", "").startswith("execute_tool"):
        return None
    for event in span.get("events", []):
        if event.get("name") != "gen_ai.choice":
            continue
        try:
            blocks = json.loads(event.get("attributes", {}).get("message", "[]"))
            payload = json.loads(blocks[0]["text"])
        except ValueError, LookupError, TypeError:
            continue
        if isinstance(payload, dict) and payload.get("ok") is False:
            return str((payload.get("error") or {}).get("code", "UNKNOWN"))
    return None


def describe(span: dict) -> list[str]:
    """One line for the span, plus one per support event recorded on it."""
    status = span.get("status", {}).get("code", "UNSET")
    duration_ms = int(span.get("durationNano", 0)) // 1_000_000
    flags = []
    if status == "ERROR":
        flags.append("ERROR " + span.get("status", {}).get("message", "")[:120])
    if code := tool_error_code(span):
        flags.append(f"tool returned {code}")
    # The model call ended because the Bedrock Guardrail blocked or masked something.
    if "guardrail_intervened" in str(
        span.get("attributes", {}).get("gen_ai.response.finish_reasons")
    ):
        flags.append("guardrail intervened")
    line = f"{span['name']} ({duration_ms} ms)" + (f"  <-- {'; '.join(flags)}" if flags else "")
    lines = [line]
    for event in span.get("events", []):
        name = event.get("name", "")
        attributes = event.get("attributes", {})
        if name == "exception":
            # The type and message are enough; stack traces stay in CloudWatch.
            attributes = {k: attributes.get(k) for k in ("exception.type", "exception.message")}
        if name.startswith("support.") or name == "exception":
            details = ", ".join(f"{k}={v}" for k, v in attributes.items())
            lines.append(f"  * {name}: {details[:200]}")
    return lines


def walk(children: dict, parent: str | None, depth: int, counts: dict[str, int]) -> None:
    """Print a span subtree and count its failures and support events."""
    for span in children[parent]:
        failed = span.get("status", {}).get("code") == "ERROR"
        if failed or span["name"] not in HIDDEN_SPANS:
            for i, line in enumerate(describe(span)):
                print("  " * (depth + 1) + ("" if i == 0 else "  ") + line)
        for event in span.get("events", []):
            counts[event.get("name", "")] += 1
        counts["error spans"] += failed
        counts["tool errors"] += tool_error_code(span) is not None
        finish = str(span.get("attributes", {}).get("gen_ai.response.finish_reasons"))
        counts["guardrail interventions"] += "guardrail_intervened" in finish
        walk(children, span["spanId"], depth + 1, counts)


def print_trees(spans: list[dict]) -> dict[str, int]:
    by_trace: dict[str, list[dict]] = defaultdict(list)
    for span in spans:
        by_trace[span["traceId"]].append(span)
    counts: dict[str, int] = defaultdict(int)

    for trace_id, trace_spans in sorted(
        by_trace.items(), key=lambda item: min(s["startTimeUnixNano"] for s in item[1])
    ):
        ids = {s["spanId"] for s in trace_spans}
        children: dict[str | None, list[dict]] = defaultdict(list)
        for span in sorted(trace_spans, key=lambda s: s["startTimeUnixNano"]):
            parent = span.get("parentSpanId")
            children[parent if parent in ids else None].append(span)

        print(f"\nTrace {trace_id}")
        walk(children, None, 0, counts)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session_id")
    parser.add_argument("--hours", type=float, default=6)
    args = parser.parse_args()

    spans = query_spans(runtime_log_group(), args.session_id, args.hours)
    if not spans:
        sys.exit(f"No spans for {args.session_id} yet. Spans arrive 1-2 minutes after a request.")
    print(f"Session {args.session_id}: {len(spans)} spans")
    counts = print_trees(spans)
    summary = {
        "error spans": counts["error spans"],
        "tool errors": counts["tool errors"],
        "retries": counts["support.tool_retry"],
        "loop guard blocks": counts["support.loop_guard_blocked"],
        "guardrail interventions": counts["guardrail interventions"],
        "refunds blocked": counts["support.refund_amount_blocked"],
        "failed requests": counts["support.request_failed"],
    }
    print("\nSummary: " + ", ".join(f"{name} {value}" for name, value in summary.items()))


if __name__ == "__main__":
    main()
