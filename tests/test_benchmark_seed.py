from pathlib import Path

from tools.evaluate_seed import evaluate


def test_phase0_seed_regression_suite_is_green():
    result = evaluate(Path("benchmarks/seed_v0.jsonl"))
    assert result["cases"] >= 20
    assert result["false_positives"] == 0
    assert result["false_negatives"] == 0
