from pathlib import Path

from tools.validate_sovereign_release import validate


def test_sovereign_release_contracts_pass() -> None:
    root = Path(__file__).resolve().parents[1]
    failures = [item for item in validate(root, include_cleanliness=False) if not item.passed]
    assert not failures, failures
