"""Evaluate Dhad against the small independent Phase-0 seed suite.

This is a regression harness, not a research benchmark. The Phase-2 gold corpus
will replace it for publishable accuracy claims.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dhad import Dhad  # noqa: E402
from dhad.text import tokenize  # noqa: E402


@dataclass(frozen=True)
class Label:
    rule_id: str
    offset: int
    length: int


def _expected_labels(case: dict) -> set[Label]:
    labels: set[Label] = set()
    text = case["text"]
    cursor_by_target: dict[str, int] = {}
    for item in case["expected"]:
        target = item["target"]
        start_at = cursor_by_target.get(target, 0)
        offset = text.find(target, start_at)
        if offset < 0:
            raise ValueError(f"{case['id']}: target {target!r} not found")
        cursor_by_target[target] = offset + len(target)
        labels.add(Label(item["rule_id"], offset, len(target)))
    return labels


def evaluate(path: Path) -> dict[str, float | int]:
    checker = Dhad()
    tp = fp = fn = words = cases = 0
    failures: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        cases += 1
        text = case["text"]
        words += len([token for token in tokenize(text) if token.is_arabic])
        expected = _expected_labels(case)
        actual = {Label(m.rule_id, m.offset, m.length) for m in checker.check(text)}
        tp += len(expected & actual)
        fp += len(actual - expected)
        fn += len(expected - actual)
        if actual != expected:
            failures.append(
                f"{case['id']}: expected={sorted(expected, key=str)} actual={sorted(actual, key=str)}"
            )
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    beta2 = 0.25
    f05 = (
        (1 + beta2) * precision * recall / (beta2 * precision + recall)
        if precision + recall
        else 0.0
    )
    result: dict[str, float | int] = {
        "cases": cases,
        "words": words,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f0.5": f05,
        "false_positives_per_1000_words": fp * 1000 / words if words else 0.0,
    }
    if failures:
        print("\n".join(failures), file=sys.stderr)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=ROOT / "benchmarks" / "seed_v0.jsonl")
    args = parser.parse_args()
    result = evaluate(args.path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["false_positives"] or result["false_negatives"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
