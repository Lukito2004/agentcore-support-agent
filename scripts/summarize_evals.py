"""Turn the raw output of scripts/run_evals.ps1 into a Markdown table: scenarios x evaluators.

Usage: uv run python scripts/summarize_evals.py docs/evidence/evals.txt [--out summary.md]
A scenario with several traces shows its lowest score. n/a means the evaluator does not apply.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

# An evaluator that needs an expected trajectory has nothing to compare for "no tool" scenarios.
NOT_APPLICABLE_ERRORS = ("Expected trajectory not provided",)
EXPLANATION_CHARS = 240


def short_name(evaluator_id: str) -> str:
    name = evaluator_id.removeprefix("Builtin.")
    # Custom evaluators are named <project>_<target>_<name>-<suffix>.
    return name.split("-")[0].removeprefix("SupportAgent_default_")


def load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    return json.loads(text[text.index("{") :])


def cell(result: dict) -> tuple[str, float | None]:
    """What to show for one result, and its numeric score if it has one."""
    message = result.get("errorMessage") or ""
    if result.get("errorCode"):
        if any(marker in message for marker in NOT_APPLICABLE_ERRORS):
            return "n/a", None
        return f"error: {result['errorCode']}", None
    value = result.get("value")
    if not isinstance(value, int | float):
        return "n/a" if result.get("label") == "NotApplicable" else str(result.get("label")), None
    return f"{value:g}", float(value)


def summarize(data: dict) -> str:
    scenario_of = {s["sessionId"]: s["exampleId"] for s in data.get("sessions", [])}
    scenarios = [s["exampleId"] for s in data.get("sessions", [])]
    evaluators: list[str] = []
    cells: dict[tuple[str, str], tuple[str, float | None]] = {}
    scores: dict[str, list[float]] = defaultdict(list)
    low: list[str] = []

    for result in data["results"]:
        evaluator = short_name(result["evaluatorId"])
        if evaluator not in evaluators:
            evaluators.append(evaluator)
        session = result.get("context", {}).get("spanContext", {}).get("sessionId")
        scenario = scenario_of.get(session, session)
        shown, value = cell(result)
        previous = cells.get((scenario, evaluator))
        # Keep the worst trace of a multi-turn scenario.
        if previous is None or (value is not None and (previous[1] is None or value < previous[1])):
            cells[(scenario, evaluator)] = (shown, value)
        if value is not None:
            scores[evaluator].append(value)
            if value < 1:
                explanation = " ".join(str(result.get("explanation", "")).split())
                low.append(
                    f"- **{scenario}**, {evaluator} = {shown}: {explanation[:EXPLANATION_CHARS]}..."
                )

    lines = [
        f"Sessions evaluated: {data.get('sessionsEvaluated')} of {data.get('sessionsRequested')}",
        "",
        "| Scenario | " + " | ".join(evaluators) + " |",
        "|---|" + "---|" * len(evaluators),
    ]
    for scenario in scenarios:
        # No result: a tool-level evaluator on a scenario without tool calls.
        row = [cells.get((scenario, e), ("n/a", None))[0] for e in evaluators]
        lines.append(f"| {scenario} | " + " | ".join(row) + " |")
    averages = [
        f"{sum(scores[e]) / len(scores[e]):.2f}" if scores[e] else "n/a" for e in evaluators
    ]
    lines.append("| **average** | " + " | ".join(averages) + " |")
    if low:
        lines += ["", "Scores below 1:", "", *low]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    summary = summarize(load(args.raw))
    if args.out:
        args.out.write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
